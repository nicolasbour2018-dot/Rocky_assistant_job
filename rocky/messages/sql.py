"""SQL access of the messages: the only place where the tables of the module ``messages`` are queried.

Decision ``docs/decisions/E1-collecte.md``: a message is written once, alone in its transaction, and never changed;
``SqlStorage`` opens the transactions and holds the collection lock of a mailbox.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    Engine,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Row,
    Table,
    Text,
    UniqueConstraint,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rocky.messages.model import (
    CollectedMessage,
    Mailbox,
    MailboxStatus,
    MailSync,
    Query,
    StoredMessage,
    SyncCounts,
    SyncStatus,
    Trigger,
)
from rocky.messages.rules import QUERIES_VERSION
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event

# First key of the advisory locks of a mailbox's collection (the second is the mailbox): a hash of this name and of
# the schema, since advisory locks are shared by the whole database (each test worker has its own schema).
COLLECT_LOCK_SPACE = "rocky.messages.collect"
LOCK_KEY = "hashtext(CAST(:space AS text) || current_schema())"


def _in(column: str, values: type[StrEnum]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def _timestamp(name: str, *, nullable: bool = False) -> Column[Any]:
    return Column(name, DateTime(timezone=True), nullable=nullable)


mailboxes = Table(
    "mailboxes",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    # Read at Google after the consent, in lower case (Q2).
    Column("address", Text, nullable=False),
    Column("status", Text, nullable=False),
    # The refresh token sealed with ROCKY_SECRET_KEY (Q3); only a connected mailbox has one.
    Column("sealed_token", LargeBinary),
    _timestamp("connected_at"),
    _timestamp("updated_at"),
    UniqueConstraint("account_id", "address"),
    CheckConstraint(_in("status", MailboxStatus), name="status"),
    CheckConstraint(
        "(status = 'connected') = (sealed_token IS NOT NULL)",
        name="token_when_connected",
    ),
)

mail_syncs = Table(
    "mail_syncs",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("mailbox_id", BigInteger, ForeignKey("mailboxes.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("trigger", Text, nullable=False),
    Column("status", Text, nullable=False),
    _timestamp("started_at"),
    _timestamp("finished_at", nullable=True),
    _timestamp("window_start"),
    Column("queries_version", Text, nullable=False),
    Column("reason", Text),
    Column("listed", Integer, nullable=False, server_default="0"),
    Column("known", Integer, nullable=False, server_default="0"),
    Column("new", Integer, nullable=False, server_default="0"),
    Column("not_written", Integer, nullable=False, server_default="0"),
    CheckConstraint(_in("trigger", Trigger), name="trigger"),
    CheckConstraint(_in("status", SyncStatus), name="status"),
    # A collection is closed exactly when it has a final status.
    CheckConstraint(
        "(status = 'running') = (finished_at IS NULL)", name="closed_when_final"
    ),
    Index("ix_mail_syncs_mailbox_id_started_at", "mailbox_id", "started_at"),
)

email_messages = Table(
    "email_messages",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("mailbox_id", BigInteger, ForeignKey("mailboxes.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    # The collection that wrote it.
    Column("sync_id", BigInteger, ForeignKey("mail_syncs.id"), nullable=False),
    Column("gmail_id", Text, nullable=False),
    Column("thread_id", Text, nullable=False),
    _timestamp("received_at"),
    Column("sender", Text, nullable=False),
    Column("sender_address", Text),
    Column("recipients", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("snippet", Text, nullable=False),
    Column("body_text", Text, nullable=False),
    Column("body_html", Text, nullable=False),
    Column("truncated", Boolean, nullable=False),
    Column("labels", JSONB, nullable=False),
    # [{"name", "mime_type", "size"}]: names only, never the content (Q5).
    Column("attachments", JSONB, nullable=False),
    Column("rfc822_id", Text),
    # The queries that found it (Q4) and their version.
    Column("found_by", JSONB, nullable=False),
    Column("queries_version", Text, nullable=False),
    _timestamp("collected_at"),
    # The idempotence of the collection: a message is stored once per mailbox.
    UniqueConstraint("mailbox_id", "gmail_id"),
    Index("ix_email_messages_account_id_received_at", "account_id", "received_at"),
)


class SqlStore:
    """``Store`` on a connection already inside a transaction; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    # Mailboxes

    def connected_mailboxes(self, account_id: int | None = None) -> list[Mailbox]:
        query = select(mailboxes).where(
            mailboxes.c.status == MailboxStatus.CONNECTED.value
        )
        if account_id is not None:
            query = query.where(mailboxes.c.account_id == account_id)
        return [
            _mailbox(row) for row in self._conn.execute(query.order_by(mailboxes.c.id))
        ]

    def mailboxes(self, account_id: int) -> list[Mailbox]:
        query = (
            select(mailboxes)
            .where(mailboxes.c.account_id == account_id)
            .order_by(mailboxes.c.address)
        )
        return [_mailbox(row) for row in self._conn.execute(query)]

    def mailbox(self, mailbox_id: int) -> Mailbox | None:
        row = self._conn.execute(
            select(mailboxes).where(mailboxes.c.id == mailbox_id)
        ).one_or_none()
        return None if row is None else _mailbox(row)

    def find_mailbox(self, account_id: int, address: str) -> Mailbox | None:
        row = self._conn.execute(
            select(mailboxes).where(
                mailboxes.c.account_id == account_id, mailboxes.c.address == address
            )
        ).one_or_none()
        return None if row is None else _mailbox(row)

    def add_mailbox(
        self, account_id: int, address: str, sealed_token: bytes, now: datetime
    ) -> int:
        return int(
            self._conn.execute(
                insert(mailboxes)
                .values(
                    account_id=account_id,
                    address=address,
                    status=MailboxStatus.CONNECTED.value,
                    sealed_token=sealed_token,
                    connected_at=now,
                    updated_at=now,
                )
                .returning(mailboxes.c.id)
            ).scalar_one()
        )

    def set_mailbox(
        self,
        mailbox_id: int,
        *,
        status: MailboxStatus,
        sealed_token: bytes | None,
        now: datetime,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "sealed_token": sealed_token,
            "updated_at": now,
        }
        if status is MailboxStatus.CONNECTED:
            values["connected_at"] = now
        self._conn.execute(
            update(mailboxes).where(mailboxes.c.id == mailbox_id).values(**values)
        )

    # Messages

    def known_ids(self, mailbox_id: int, gmail_ids: Sequence[str]) -> set[str]:
        if not gmail_ids:
            return set()
        query = select(email_messages.c.gmail_id).where(
            email_messages.c.mailbox_id == mailbox_id,
            email_messages.c.gmail_id.in_(list(gmail_ids)),
        )
        return set(self._conn.execute(query).scalars())

    def add_message(
        self,
        mailbox: Mailbox,
        message: CollectedMessage,
        *,
        found_by: Sequence[Query],
        sync_id: int,
        now: datetime,
    ) -> int | None:
        statement = (
            pg_insert(email_messages)
            .values(
                mailbox_id=mailbox.id,
                account_id=mailbox.account_id,
                sync_id=sync_id,
                gmail_id=message.gmail_id,
                thread_id=message.thread_id,
                received_at=message.received_at,
                sender=message.sender,
                sender_address=message.sender_address,
                recipients=message.recipients,
                subject=message.subject,
                snippet=message.snippet,
                body_text=message.body_text,
                body_html=message.body_html,
                truncated=message.truncated,
                labels=list(message.labels),
                attachments=[asdict(item) for item in message.attachments],
                rfc822_id=message.rfc822_id,
                found_by=[query.value for query in found_by],
                queries_version=QUERIES_VERSION,
                collected_at=now,
            )
            .on_conflict_do_nothing(index_elements=["mailbox_id", "gmail_id"])
            .returning(email_messages.c.id)
        )
        found = self._conn.execute(statement).scalar_one_or_none()
        return None if found is None else int(found)

    def recent_messages(self, account_id: int, limit: int) -> list[StoredMessage]:
        query = (
            select(
                email_messages.c.id,
                mailboxes.c.address,
                email_messages.c.received_at,
                email_messages.c.sender,
                email_messages.c.subject,
                email_messages.c.found_by,
            )
            .join(mailboxes, mailboxes.c.id == email_messages.c.mailbox_id)
            .where(email_messages.c.account_id == account_id)
            .order_by(email_messages.c.received_at.desc(), email_messages.c.id.desc())
            .limit(limit)
        )
        return [
            StoredMessage(
                id=row.id,
                mailbox_address=row.address,
                received_at=row.received_at,
                sender=row.sender,
                subject=row.subject,
                found_by=tuple(Query(value) for value in row.found_by),
            )
            for row in self._conn.execute(query)
        ]

    # Collections

    def start_sync(
        self, mailbox: Mailbox, trigger: Trigger, window_start: datetime, now: datetime
    ) -> int:
        return int(
            self._conn.execute(
                insert(mail_syncs)
                .values(
                    mailbox_id=mailbox.id,
                    account_id=mailbox.account_id,
                    trigger=trigger.value,
                    status=SyncStatus.RUNNING.value,
                    started_at=now,
                    window_start=window_start,
                    queries_version=QUERIES_VERSION,
                )
                .returning(mail_syncs.c.id)
            ).scalar_one()
        )

    def finish_sync(
        self,
        sync_id: int,
        *,
        status: SyncStatus,
        reason: str | None,
        counts: SyncCounts,
        now: datetime,
    ) -> None:
        self._conn.execute(
            update(mail_syncs)
            .where(mail_syncs.c.id == sync_id)
            .values(
                status=status.value, reason=reason, finished_at=now, **asdict(counts)
            )
        )

    def get_sync(self, sync_id: int) -> MailSync | None:
        row = self._conn.execute(
            select(mail_syncs).where(mail_syncs.c.id == sync_id)
        ).one_or_none()
        return None if row is None else _sync(row)

    def running_syncs(self) -> list[MailSync]:
        query = (
            select(mail_syncs)
            .where(mail_syncs.c.status == SyncStatus.RUNNING.value)
            .order_by(mail_syncs.c.id)
        )
        return [_sync(row) for row in self._conn.execute(query)]

    def last_completed_sync(self, mailbox_id: int) -> MailSync | None:
        return self._last(mailbox_id, SyncStatus.COMPLETED)

    def last_sync(self, mailbox_id: int) -> MailSync | None:
        return self._last(mailbox_id, None)

    def _last(self, mailbox_id: int, status: SyncStatus | None) -> MailSync | None:
        query = select(mail_syncs).where(mail_syncs.c.mailbox_id == mailbox_id)
        if status is not None:
            query = query.where(mail_syncs.c.status == status.value)
        row = self._conn.execute(
            query.order_by(
                mail_syncs.c.started_at.desc(), mail_syncs.c.id.desc()
            ).limit(1)
        ).one_or_none()
        return None if row is None else _sync(row)

    def append_event(self, event: NewEvent) -> int:
        return append_event(self._conn, event)


class SqlStorage:
    """``Storage`` on an engine: one transaction per call, and the advisory lock of a mailbox's collection."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[SqlStore]:
        with self._engine.begin() as connection:
            yield SqlStore(connection)

    @contextmanager
    def lock(self, mailbox_id: int) -> Iterator[bool]:
        """A session lock on its own connection, held while open: a killed process releases it with its session."""
        with self._engine.connect() as connection:
            locked = bool(
                connection.execute(
                    text(
                        f"SELECT pg_try_advisory_lock({LOCK_KEY}, CAST(:id AS integer))"
                    ),
                    {"space": COLLECT_LOCK_SPACE, "id": mailbox_id},
                ).scalar_one()
            )
            connection.commit()
            try:
                yield locked
            finally:
                if locked:
                    connection.execute(
                        text(
                            f"SELECT pg_advisory_unlock({LOCK_KEY}, CAST(:id AS integer))"
                        ),
                        {"space": COLLECT_LOCK_SPACE, "id": mailbox_id},
                    )
                    connection.commit()


def _mailbox(row: Row[Any]) -> Mailbox:
    return Mailbox(
        id=row.id,
        account_id=row.account_id,
        address=row.address,
        status=MailboxStatus(row.status),
        connected_at=row.connected_at,
        sealed_token=row.sealed_token,
    )


def _sync(row: Row[Any]) -> MailSync:
    return MailSync(
        id=row.id,
        mailbox_id=row.mailbox_id,
        account_id=row.account_id,
        trigger=Trigger(row.trigger),
        status=SyncStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        window_start=row.window_start,
        reason=row.reason,
        counts=SyncCounts(
            listed=row.listed, known=row.known, new=row.new, not_written=row.not_written
        ),
    )
