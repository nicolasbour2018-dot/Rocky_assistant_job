"""SQL access of the messages: the only place where the tables of the module ``messages`` are queried.

Decision ``docs/decisions/E1-collecte.md``: a message is written once, alone in its transaction, and never changed;
``SqlStorage`` opens the transactions and holds the collection lock of a mailbox. Decision
``docs/decisions/E2-classification.md``: the decisions about a message are appended, the latest in force, each with
its proof; every call to the language model is a row.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
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
    Select,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rocky.messages.classification.model import (
    CLASSIFY_VERSION,
    EMPLOYER_CATEGORIES,
    CallOutcome,
    Category,
    Level,
    MailToClassify,
    Proof,
    SortedMessage,
    StoredDecision,
    Tier,
    Verdict,
    View,
)
from rocky.messages.classification.rules import readable
from rocky.messages.model import (
    CollectedMessage,
    Mailbox,
    MailboxStatus,
    MailSync,
    Query,
    SyncCounts,
    SyncStatus,
    Trigger,
)
from rocky.messages.rules import QUERIES_VERSION
from rocky.offres.decisions import Author
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event

# First key of the advisory locks of a mailbox's collection (the second is the mailbox): a hash of this name and of
# the schema, since advisory locks are shared by the whole database (each test worker has its own schema).
COLLECT_LOCK_SPACE = "rocky.messages.collect"
# The same for the classification of an account's messages (two passes never decide the same message twice).
CLASSIFY_LOCK_SPACE = "rocky.messages.classify"
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


# Q1, Q13: the decisions about a message, appended; the one in force is the latest. The proof is required by the
# schema: a rule, a quotation and at least one reason (exit criterion of E2).
message_decisions = Table(
    "message_decisions",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("message_id", BigInteger, ForeignKey("email_messages.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    # None: nothing could be decided, the message is « À vérifier ».
    Column("category", Text),
    Column("application_id", BigInteger, ForeignKey("applications.id")),
    Column("level", Text, nullable=False),
    Column("author", Text, nullable=False),
    # The rule of the first proof and its quotation, in columns for the training data (D14).
    Column("rule", Text, nullable=False),
    Column("excerpt", Text, nullable=False),
    # [{"tier", "rule", "excerpt", "reason"}], the first one gave the category.
    Column("proofs", JSONB, nullable=False),
    Column("classify_version", Text, nullable=False),
    _timestamp("decided_at"),
    CheckConstraint(
        "category IS NULL OR " + _in("category", Category), name="category"
    ),
    CheckConstraint(_in("level", Level), name="level"),
    CheckConstraint(_in("author", Author), name="author"),
    CheckConstraint("char_length(rule) > 0", name="rule_given"),
    CheckConstraint("char_length(excerpt) > 0", name="excerpt_given"),
    CheckConstraint(
        "jsonb_typeof(proofs) = 'array' AND jsonb_array_length(proofs) > 0",
        name="proofs_given",
    ),
    # Nothing decided is never « confident ».
    CheckConstraint("category IS NOT NULL OR level = 'low'", name="undecided_low"),
    Index("ix_message_decisions_message_id", "message_id", "id"),
    Index("ix_message_decisions_account_id", "account_id", "id"),
)

# Q18: every call to the language model, for its limits per account and the training data (D14).
mail_model_calls = Table(
    "mail_model_calls",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("message_id", BigInteger, ForeignKey("email_messages.id"), nullable=False),
    _timestamp("called_at"),
    Column("classify_version", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("reason", Text),
    Column("duration_ms", Integer, nullable=False),
    CheckConstraint(_in("outcome", CallOutcome), name="outcome"),
    Index("ix_mail_model_calls_account_id_called_at", "account_id", "called_at"),
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

    # Classification (E2)

    def undecided(
        self, account_id: int, after_id: int, limit: int
    ) -> list[MailToClassify]:
        decided = select(message_decisions.c.id).where(
            message_decisions.c.message_id == email_messages.c.id
        )
        query = (
            select(email_messages)
            .where(
                email_messages.c.account_id == account_id,
                email_messages.c.id > after_id,
                ~decided.exists(),
            )
            .order_by(email_messages.c.id)
            .limit(limit)
        )
        return [_to_classify(row) for row in self._conn.execute(query)]

    def messages_of(
        self, account_id: int, after_id: int, limit: int
    ) -> list[MailToClassify]:
        query = (
            select(email_messages)
            .where(
                email_messages.c.account_id == account_id,
                email_messages.c.id > after_id,
            )
            .order_by(email_messages.c.id)
            .limit(limit)
        )
        return [_to_classify(row) for row in self._conn.execute(query)]

    def waiting(self, account_id: int) -> int:
        """Messages of the account without any decision yet."""
        decided = select(message_decisions.c.id).where(
            message_decisions.c.message_id == email_messages.c.id
        )
        return int(
            self._conn.execute(
                select(func.count())
                .select_from(email_messages)
                .where(email_messages.c.account_id == account_id, ~decided.exists())
            ).scalar_one()
        )

    def has_decision(self, message_id: int) -> bool:
        return (
            self._conn.execute(
                select(message_decisions.c.id)
                .where(message_decisions.c.message_id == message_id)
                .limit(1)
            ).first()
            is not None
        )

    def lock_message(self, message_id: int) -> None:
        self._conn.execute(
            select(email_messages.c.id)
            .where(email_messages.c.id == message_id)
            .with_for_update()
        )

    def attached_threads(self, account_id: int) -> dict[tuple[int, str], int]:
        """The threads whose message has an application in its decision in force."""
        current = _current_decisions(account_id).subquery()
        query = (
            select(
                email_messages.c.mailbox_id,
                email_messages.c.thread_id,
                current.c.application_id,
            )
            .join(current, current.c.message_id == email_messages.c.id)
            .where(current.c.application_id.is_not(None))
            .order_by(email_messages.c.received_at)
        )
        return {
            (row.mailbox_id, row.thread_id): row.application_id
            for row in self._conn.execute(query)
        }

    def current_author(self, message_id: int) -> Author | None:
        author = self._conn.execute(
            select(message_decisions.c.author)
            .where(message_decisions.c.message_id == message_id)
            .order_by(message_decisions.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return None if author is None else Author(author)

    def add_decision(
        self, account_id: int, message_id: int, verdict: Verdict, now: datetime
    ) -> int:
        first = verdict.proofs[0]
        return int(
            self._conn.execute(
                insert(message_decisions)
                .values(
                    message_id=message_id,
                    account_id=account_id,
                    category=None
                    if verdict.category is None
                    else verdict.category.value,
                    application_id=verdict.application_id,
                    level=verdict.level.value,
                    author=verdict.author.value,
                    rule=first.rule,
                    excerpt=first.excerpt,
                    proofs=[asdict(proof) for proof in verdict.proofs],
                    classify_version=CLASSIFY_VERSION,
                    decided_at=now,
                )
                .returning(message_decisions.c.id)
            ).scalar_one()
        )

    def add_call(
        self,
        account_id: int,
        message_id: int,
        *,
        outcome: CallOutcome,
        reason: str | None,
        duration_ms: int,
        now: datetime,
    ) -> None:
        self._conn.execute(
            insert(mail_model_calls).values(
                account_id=account_id,
                message_id=message_id,
                called_at=now,
                classify_version=CLASSIFY_VERSION,
                outcome=outcome.value,
                reason=reason,
                duration_ms=duration_ms,
            )
        )

    def calls_since(self, account_id: int, since: datetime) -> int:
        return int(
            self._conn.execute(
                select(func.count())
                .select_from(mail_model_calls)
                .where(
                    mail_model_calls.c.account_id == account_id,
                    mail_model_calls.c.called_at > since,
                )
            ).scalar_one()
        )

    def last_failure(self, account_id: int, since: datetime) -> str | None:
        """The reason of the last call that gave no answer since ``since``, if the last call failed."""
        row = self._conn.execute(
            select(mail_model_calls.c.outcome, mail_model_calls.c.reason)
            .where(
                mail_model_calls.c.account_id == account_id,
                mail_model_calls.c.called_at > since,
            )
            .order_by(mail_model_calls.c.id.desc())
            .limit(1)
        ).one_or_none()
        if row is None or row.outcome != CallOutcome.FAILED.value:
            return None
        reason: str | None = row.reason
        return reason

    def sorted_messages(
        self, account_id: int, view: View, limit: int
    ) -> list[SortedMessage]:
        """The last messages of ``view`` with their decision in force (Q14)."""
        current = _current_decisions(account_id).subquery()
        query = (
            select(
                email_messages.c.id,
                mailboxes.c.address,
                email_messages.c.received_at,
                email_messages.c.sender,
                email_messages.c.subject,
                email_messages.c.found_by,
                current.c.id.label("decision_id"),
                current.c.message_id,
                current.c.category,
                current.c.application_id,
                current.c.level,
                current.c.author,
                current.c.proofs,
                current.c.classify_version,
                current.c.decided_at,
            )
            .join(mailboxes, mailboxes.c.id == email_messages.c.mailbox_id)
            .outerjoin(current, current.c.message_id == email_messages.c.id)
            .where(email_messages.c.account_id == account_id)
            .order_by(email_messages.c.received_at.desc(), email_messages.c.id.desc())
            .limit(limit)
        )
        employers = [category.value for category in EMPLOYER_CATEGORIES]
        low = current.c.level == Level.LOW.value
        match view:
            case View.TO_LOOK_AT:
                waiting = current.c.id.is_(None)
                query = query.where(current.c.category.in_(employers) | low | waiting)
            case View.TO_CHECK:
                query = query.where(low)
            case View.EMPLOYERS:
                query = query.where(current.c.category.in_(employers))
            case View.ALERTS:
                query = query.where(current.c.category == Category.JOB_ALERT.value)
            case View.APPROACHES:
                query = query.where(
                    current.c.category == Category.RECRUITER_APPROACH.value
                )
            case View.UNRELATED:
                query = query.where(current.c.category == Category.UNRELATED.value)
            case View.WAITING:
                query = query.where(current.c.id.is_(None))
            case View.ALL:
                pass
        return [
            SortedMessage(
                id=row.id,
                mailbox_address=row.address,
                received_at=row.received_at,
                sender=row.sender,
                subject=row.subject,
                found_by=tuple(Query(value) for value in row.found_by),
                decision=None if row.level is None else _decision(row),
            )
            for row in self._conn.execute(query)
        ]

    def append_event(self, event: NewEvent) -> int:
        return append_event(self._conn, event)


class SqlStorage:
    """``Storage`` on an engine: one transaction per call, and the advisory locks of a mailbox's collection and of an
    account's classification."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[SqlStore]:
        with self._engine.begin() as connection:
            yield SqlStore(connection)

    def lock(self, mailbox_id: int) -> AbstractContextManager[bool]:
        return self._advisory(COLLECT_LOCK_SPACE, mailbox_id)

    def classify_lock(self, account_id: int) -> AbstractContextManager[bool]:
        return self._advisory(CLASSIFY_LOCK_SPACE, account_id)

    @contextmanager
    def _advisory(self, space: str, key: int) -> Iterator[bool]:
        """A session lock on its own connection, held while open: a killed process releases it with its session."""
        with self._engine.connect() as connection:
            locked = bool(
                connection.execute(
                    text(
                        f"SELECT pg_try_advisory_lock({LOCK_KEY}, CAST(:id AS integer))"
                    ),
                    {"space": space, "id": key},
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
                        {"space": space, "id": key},
                    )
                    connection.commit()


def _current_decisions(account_id: int) -> Select[Any]:
    """The decision in force of each message of the account: its latest."""
    return (
        select(message_decisions)
        .where(message_decisions.c.account_id == account_id)
        .distinct(message_decisions.c.message_id)
        .order_by(message_decisions.c.message_id, message_decisions.c.id.desc())
    )


def _to_classify(row: Row[Any]) -> MailToClassify:
    return MailToClassify(
        id=row.id,
        mailbox_id=row.mailbox_id,
        thread_id=row.thread_id,
        received_at=row.received_at,
        sender=row.sender,
        sender_address=row.sender_address,
        subject=row.subject,
        body_text=readable(row.body_text),
        found_by=tuple(Query(value) for value in row.found_by),
    )


def _decision(row: Row[Any]) -> StoredDecision:
    return StoredDecision(
        id=row.decision_id,
        message_id=row.message_id,
        category=None if row.category is None else Category(row.category),
        application_id=row.application_id,
        level=Level(row.level),
        author=Author(row.author),
        proofs=tuple(
            Proof(Tier(item["tier"]), item["rule"], item["excerpt"], item["reason"])
            for item in row.proofs
        ),
        version=row.classify_version,
        decided_at=row.decided_at,
    )


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
