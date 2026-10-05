"""SQL access of the messages: the only place where the tables of the module ``messages`` are queried.

Decision ``docs/decisions/E1-collecte.md``: a message is written once, alone in its transaction, and never changed;
``SqlStorage`` opens the transactions and holds the collection lock of a mailbox. Decision
``docs/decisions/E2-classification.md``: the decisions about a message are appended, the latest in force, each with
its proof; every call to the language model is a row. Decision ``docs/decisions/E4-decisions-ecran.md``: the
transitions a decision gives, their settlements and the account's rules per sender are appended too.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
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
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rocky.candidatures.model import Stage
from rocky.messages.alerts.model import (
    ALERTS_VERSION,
    AlertMessage,
    AlertOffer,
    AlertSummary,
    CardResult,
    LinkOutcome,
    NotTried,
    Platform,
    ReadingStatus,
)
from rocky.messages.classification.model import (
    ACTION_RULES,
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
from rocky.messages.decisions.model import (
    RULE_CATEGORIES,
    Gesture,
    Label,
    MessageRef,
    Moved,
    Outcome,
    SenderRule,
    Transition,
)
from rocky.messages.links import AlertOffersLink, CandidaturesLink, OffresLink
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
from rocky.offres.analysis.text import fold
from rocky.offres.decisions import Author
from rocky.profil import web as profil_web
from rocky.profil.model import Profile
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event

# First key of the advisory locks of a mailbox's collection (the second is the mailbox): a hash of this name and of
# the schema, since advisory locks are shared by the whole database (each test worker has its own schema).
COLLECT_LOCK_SPACE = "rocky.messages.collect"
# The same for the classification of an account's messages (two passes never decide the same message twice).
CLASSIFY_LOCK_SPACE = "rocky.messages.classify"
# The same for the reading of an account's job alerts (decision E3).
ALERTS_LOCK_SPACE = "rocky.messages.alerts"
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
    # Decision E4 (Q6): the decision a user's decision reviews (corrects or confirms), the pair is a label of D14.
    Column("reviews_id", BigInteger, ForeignKey("message_decisions.id")),
    CheckConstraint(
        "category IS NULL OR " + _in("category", Category), name="category"
    ),
    CheckConstraint("reviews_id IS NULL OR author = 'user'", name="reviews_by_user"),
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


# Decision E4 (Q1): the transition a decision gives its application, recorded with it: applied (the change of the
# application) or proposed (until the user applies it).
mail_transitions = Table(
    "mail_transitions",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column(
        "decision_id",
        BigInteger,
        ForeignKey("message_decisions.id"),
        nullable=False,
        unique=True,
    ),
    Column("message_id", BigInteger, ForeignKey("email_messages.id"), nullable=False),
    Column("application_id", BigInteger, ForeignKey("applications.id"), nullable=False),
    Column("from_stage", Text, nullable=False),
    Column("to_stage", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("change_id", BigInteger, ForeignKey("application_changes.id"), unique=True),
    _timestamp("created_at"),
    CheckConstraint(_in("from_stage", Stage), name="from_stage"),
    CheckConstraint(_in("to_stage", Stage), name="to_stage"),
    CheckConstraint(_in("outcome", Outcome), name="outcome"),
    CheckConstraint("from_stage <> to_stage", name="moves"),
    CheckConstraint(
        "(outcome = 'applied') = (change_id IS NOT NULL)", name="change_when_applied"
    ),
    Index("ix_mail_transitions_account_id", "account_id", "id"),
    Index("ix_mail_transitions_message_id", "message_id", "id"),
)

# Q5: how a transition left « Ce qui a bougé »; one row per gesture, a transition without any is still to settle.
mail_transition_settlements = Table(
    "mail_transition_settlements",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "transition_id", BigInteger, ForeignKey("mail_transitions.id"), nullable=False
    ),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("gesture", Text, nullable=False),
    # The change of the application the gesture made (applied) or undid (cancelled, corrected).
    Column("change_id", BigInteger, ForeignKey("application_changes.id")),
    _timestamp("settled_at"),
    UniqueConstraint(
        "transition_id",
        "gesture",
        name="uq_mail_transition_settlements_transition_id",
    ),
    CheckConstraint(_in("gesture", Gesture), name="gesture"),
    CheckConstraint(
        "gesture <> 'applied' OR change_id IS NOT NULL", name="change_when_applied"
    ),
)

# Q7: the account's rules « adresse exacte → catégorie », appended; a removal is a row of its own.
mail_sender_rules = Table(
    "mail_sender_rules",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("sender_address", Text, nullable=False),
    Column("category", Text),
    # The correction the rule was born of.
    Column("decision_id", BigInteger, ForeignKey("message_decisions.id")),
    Column("removes_id", BigInteger, ForeignKey("mail_sender_rules.id"), unique=True),
    _timestamp("created_at"),
    CheckConstraint(
        "(category IS NULL) = (removes_id IS NOT NULL)", name="rule_or_removal"
    ),
    CheckConstraint(
        "category IS NULL OR category IN ({})".format(
            ", ".join(f"'{category.value}'" for category in sorted(RULE_CATEGORIES))
        ),
        name="category",
    ),
    CheckConstraint(
        "char_length(sender_address) > 0 AND sender_address = lower(sender_address)",
        name="sender_address",
    ),
    Index("ix_mail_sender_rules_account_id", "account_id", "id"),
)

# Decision E3 (Q4, Q5): the reading of a job alert, once per message, and the offers it gave with what became of the
# link of each card. The card's title and employer are kept here: the screen of the messages never reads ``offres``.
alert_readings = Table(
    "alert_readings",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column(
        "message_id",
        BigInteger,
        ForeignKey("email_messages.id"),
        nullable=False,
        unique=True,
    ),
    # None: no reader for this sender (« Format d'alerte non lu »).
    Column("platform", Text),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    Column("cards", Integer, nullable=False),
    Column("alerts_version", Text, nullable=False),
    _timestamp("read_at"),
    CheckConstraint(
        "platform IS NULL OR " + _in("platform", Platform), name="platform"
    ),
    CheckConstraint(_in("status", ReadingStatus), name="status"),
    CheckConstraint("status <> 'unknown_format' OR platform IS NULL", name="no_reader"),
    # A reading fails before its reader is known only by an error (its trace is in the log); an alert too old is not
    # read at all (Q8).
    CheckConstraint(
        "platform IS NOT NULL OR status IN ('unknown_format', 'failed', 'too_old')",
        name="reader_known",
    ),
    CheckConstraint("(status = 'read') = (cards > 0)", name="cards_read"),
    CheckConstraint("(status = 'read') = (reason IS NULL)", name="reason_unless_read"),
    Index("ix_alert_readings_account_id", "account_id", "id"),
)

alert_offers = Table(
    "alert_offers",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("reading_id", BigInteger, ForeignKey("alert_readings.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("offer_id", BigInteger, ForeignKey("job_offers.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("company", Text),
    Column("created", Boolean, nullable=False),
    Column("link_outcome", Text, nullable=False),
    Column("not_tried", Text),
    # French; never the link (it may carry a tracking token).
    Column("reason", Text),
    UniqueConstraint("reading_id", "position", name="uq_alert_offers_reading_id"),
    CheckConstraint(_in("link_outcome", LinkOutcome), name="link_outcome"),
    CheckConstraint(
        "not_tried IS NULL OR " + _in("not_tried", NotTried), name="not_tried"
    ),
    CheckConstraint(
        "(link_outcome = 'not_tried') = (not_tried IS NOT NULL)", name="why_not_tried"
    ),
    CheckConstraint(
        "(link_outcome = 'read') = (reason IS NULL)", name="reason_unless_read"
    ),
    CheckConstraint("position > 0", name="position"),
    Index("ix_alert_offers_offer_id", "offer_id"),
)

# Decision E4: what follows a decision inside its transaction (``decisions.usecases.follow_decision``), given by the
# composition; none for the collection and classification alone.
type FollowHook = Callable[
    [SqlStore, int, MailToClassify, int, Verdict, datetime], None
]


def _follow_nothing(
    store: SqlStore,
    account_id: int,
    message: MailToClassify,
    decision_id: int,
    verdict: Verdict,
    now: datetime,
) -> None:
    """No transition: the hook of a storage built without one."""


class SqlStore:
    """``Store`` on a connection already inside a transaction; never commits."""

    def __init__(
        self, connection: Connection, follow: FollowHook = _follow_nothing
    ) -> None:
        self._conn = connection
        self._follow = follow

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

    def messages_among(
        self, account_id: int, message_ids: Sequence[int]
    ) -> list[MailToClassify]:
        if not message_ids:
            return []
        query = (
            select(email_messages)
            .where(
                email_messages.c.account_id == account_id,
                email_messages.c.id.in_(list(message_ids)),
            )
            .order_by(email_messages.c.id)
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
        self,
        account_id: int,
        message_id: int,
        verdict: Verdict,
        now: datetime,
        *,
        reviews_id: int | None = None,
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
                    reviews_id=reviews_id,
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

    def acknowledgements(self, account_id: int) -> int:
        """Messages of the account whose decision in force is an acknowledgement (Q19: counted, not listed)."""
        current = _current_decisions(account_id).subquery()
        return int(
            self._conn.execute(
                select(func.count())
                .select_from(current)
                .where(current.c.category == Category.ACKNOWLEDGEMENT.value)
            ).scalar_one()
        )

    def to_check(self, account_id: int) -> int:
        """Messages of the account whose decision in force is of low confidence: the view « À vérifier » (Q14)."""
        current = _current_decisions(account_id).subquery()
        return int(
            self._conn.execute(
                select(func.count())
                .select_from(current)
                .where(current.c.level == Level.LOW.value)
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
        self,
        account_id: int,
        view: View,
        limit: int,
        *,
        application_id: int | None = None,
    ) -> list[SortedMessage]:
        """The last messages of ``view`` with their decision in force (Q14); ``application_id``: the messages attached
        to that application, whatever the view (decision E4, Q8: the dossier shows them)."""
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
        if application_id is not None:
            query = query.where(current.c.application_id == application_id)
            view = View.ALL
        match view:
            case View.TO_LOOK_AT:
                answers = [
                    category
                    for category in employers
                    if category != Category.ACKNOWLEDGEMENT.value
                ]
                query = query.where(
                    current.c.category.in_(
                        [*answers, Category.RECRUITER_APPROACH.value]
                    )
                    | current.c.rule.in_(ACTION_RULES)
                    | low
                    | current.c.id.is_(None)
                )
            case View.ACKNOWLEDGEMENTS:
                query = query.where(
                    current.c.category == Category.ACKNOWLEDGEMENT.value
                )
            case View.PLATFORM:
                query = query.where(
                    current.c.category == Category.PLATFORM_NOTICE.value
                )
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

    # Job alerts (E3)

    def alerts_to_read(self, account_id: int) -> list[AlertMessage]:
        """The messages whose decision in force is « Alerte emploi » and that were never read as an alert (Q4: the
        alerts already collected are read by the first pass)."""
        current = _current_decisions(account_id).subquery()
        read = select(literal(1)).where(
            alert_readings.c.message_id == email_messages.c.id
        )
        query = (
            select(email_messages, mailboxes.c.address)
            .join(mailboxes, mailboxes.c.id == email_messages.c.mailbox_id)
            .join(current, current.c.message_id == email_messages.c.id)
            .where(
                email_messages.c.account_id == account_id,
                current.c.category == Category.JOB_ALERT.value,
                ~read.exists(),
            )
            .order_by(email_messages.c.received_at.desc(), email_messages.c.id.desc())
        )
        return [
            AlertMessage(
                id=row.id,
                received_at=row.received_at,
                mailbox_address=row.address,
                gmail_id=row.gmail_id,
                sender_address=row.sender_address,
                subject=row.subject,
                body_text=row.body_text,
                body_html=row.body_html,
            )
            for row in self._conn.execute(query)
        ]

    def alerts_read_since(self, account_id: int, since: datetime) -> int:
        return int(
            self._conn.execute(
                select(func.count())
                .select_from(alert_readings)
                .where(
                    alert_readings.c.account_id == account_id,
                    alert_readings.c.status == ReadingStatus.READ.value,
                    alert_readings.c.read_at >= since,
                )
            ).scalar_one()
        )

    def alert_offers(self, account_id: int) -> AlertOffersLink | None:
        profile = profil_web.stored_profile(self._conn, account_id)
        return None if profile is None else AlertOffersLink(self._conn, profile)

    def add_reading(
        self,
        account_id: int,
        message_id: int,
        *,
        platform: Platform | None,
        status: ReadingStatus,
        reason: str | None,
        cards: int,
        now: datetime,
    ) -> int | None:
        reading_id: int | None = self._conn.execute(
            pg_insert(alert_readings)
            .values(
                account_id=account_id,
                message_id=message_id,
                platform=None if platform is None else platform.value,
                status=status.value,
                reason=reason,
                cards=cards,
                alerts_version=ALERTS_VERSION,
                read_at=now,
            )
            .on_conflict_do_nothing(index_elements=["message_id"])
            .returning(alert_readings.c.id)
        ).scalar_one_or_none()
        return reading_id

    def add_alert_offer(
        self,
        account_id: int,
        reading_id: int,
        result: CardResult,
        *,
        offer_id: int,
        created: bool,
    ) -> None:
        self._conn.execute(
            insert(alert_offers).values(
                reading_id=reading_id,
                account_id=account_id,
                position=result.card.position,
                offer_id=offer_id,
                title=result.card.title,
                company=result.card.company,
                created=created,
                link_outcome=result.outcome.value,
                not_tried=None if result.not_tried is None else result.not_tried.value,
                reason=result.reason,
            )
        )

    def alert_summaries(
        self, account_id: int, message_ids: Sequence[int]
    ) -> dict[int, AlertSummary]:
        """What the alerts among ``message_ids`` gave (Q5), by message."""
        if not message_ids:
            return {}
        readings = self._conn.execute(
            select(alert_readings).where(
                alert_readings.c.account_id == account_id,
                alert_readings.c.message_id.in_(list(message_ids)),
            )
        ).all()
        offers: dict[int, list[AlertOffer]] = {}
        if readings:
            rows = self._conn.execute(
                select(alert_offers)
                .where(alert_offers.c.reading_id.in_([row.id for row in readings]))
                .order_by(alert_offers.c.reading_id, alert_offers.c.position)
            )
            for row in rows:
                offers.setdefault(row.reading_id, []).append(
                    AlertOffer(
                        position=row.position,
                        offer_id=row.offer_id,
                        title=row.title,
                        company=row.company,
                        created=row.created,
                        outcome=LinkOutcome(row.link_outcome),
                        reason=row.reason,
                    )
                )
        return {
            row.message_id: AlertSummary(
                status=ReadingStatus(row.status),
                platform=None if row.platform is None else Platform(row.platform),
                offers=tuple(offers.get(row.id, ())),
                reason=row.reason,
            )
            for row in readings
        }

    # Decisions on the messages (E4)

    def follow(
        self,
        account_id: int,
        message: MailToClassify,
        decision_id: int,
        verdict: Verdict,
        now: datetime,
    ) -> None:
        self._follow(self, account_id, message, decision_id, verdict, now)

    def applications(self) -> CandidaturesLink:
        return CandidaturesLink(self._conn)

    def offers(self, profile: Profile) -> OffresLink:
        return OffresLink(self._conn, profile)

    def message(self, account_id: int, message_id: int) -> MessageRef | None:
        row = self._conn.execute(
            select(email_messages, mailboxes.c.address)
            .join(mailboxes, mailboxes.c.id == email_messages.c.mailbox_id)
            .where(
                email_messages.c.id == message_id,
                email_messages.c.account_id == account_id,
            )
        ).one_or_none()
        if row is None:
            return None
        return MessageRef(
            id=row.id,
            mailbox_address=row.address,
            gmail_id=row.gmail_id,
            received_at=row.received_at,
            sender=row.sender,
            sender_address=row.sender_address,
            subject=row.subject,
            body_text=readable(row.body_text),
        )

    def current_decision(self, message_id: int) -> StoredDecision | None:
        row = self._conn.execute(
            select(
                message_decisions,
                message_decisions.c.id.label("decision_id"),
            )
            .where(message_decisions.c.message_id == message_id)
            .order_by(message_decisions.c.id.desc())
            .limit(1)
        ).one_or_none()
        return None if row is None else _decision(row)

    def add_transition(
        self,
        account_id: int,
        *,
        decision_id: int,
        message_id: int,
        application_id: int,
        from_stage: Stage,
        to_stage: Stage,
        outcome: Outcome,
        change_id: int | None,
        now: datetime,
    ) -> int:
        return int(
            self._conn.execute(
                insert(mail_transitions)
                .values(
                    account_id=account_id,
                    decision_id=decision_id,
                    message_id=message_id,
                    application_id=application_id,
                    from_stage=from_stage.value,
                    to_stage=to_stage.value,
                    outcome=outcome.value,
                    change_id=change_id,
                    created_at=now,
                )
                .returning(mail_transitions.c.id)
            ).scalar_one()
        )

    def transition(self, account_id: int, transition_id: int) -> Transition | None:
        found = self._conn.execute(
            select(mail_transitions.c.id)
            .where(
                mail_transitions.c.id == transition_id,
                mail_transitions.c.account_id == account_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if found is None:
            return None
        rows = self._conn.execute(
            _transitions().where(mail_transitions.c.id == transition_id)
        )
        return next((_transition(row) for row in rows), None)

    def transitions_of_message(self, message_id: int) -> list[Transition]:
        query = _transitions().where(mail_transitions.c.message_id == message_id)
        return [
            _transition(row)
            for row in self._conn.execute(query.order_by(mail_transitions.c.id))
        ]

    def settle(
        self,
        account_id: int,
        transition_id: int,
        gesture: Gesture,
        *,
        change_id: int | None,
        now: datetime,
    ) -> None:
        self._conn.execute(
            insert(mail_transition_settlements).values(
                transition_id=transition_id,
                account_id=account_id,
                gesture=gesture.value,
                change_id=change_id,
                settled_at=now,
            )
        )

    def pending_moves(self, account_id: int) -> list[Moved]:
        """« Ce qui a bougé » (Q5): the transitions of the account without a settlement, the latest first."""
        query = (
            _transitions()
            .add_columns(
                email_messages.c.subject,
                email_messages.c.sender,
                email_messages.c.received_at,
                message_decisions.c.author,
                message_decisions.c.category,
            )
            .join(email_messages, email_messages.c.id == mail_transitions.c.message_id)
            .join(
                message_decisions,
                message_decisions.c.id == mail_transitions.c.decision_id,
            )
            .where(mail_transitions.c.account_id == account_id, _unsettled())
            .order_by(mail_transitions.c.id.desc())
        )
        return [
            Moved(
                transition=_transition(row),
                subject=row.subject,
                sender=row.sender,
                received_at=row.received_at,
                author=Author(row.author),
                category=None if row.category is None else Category(row.category),
            )
            for row in self._conn.execute(query)
        ]

    def pending_count(self, account_id: int) -> int:
        return int(
            self._conn.execute(
                select(func.count())
                .select_from(mail_transitions)
                .where(mail_transitions.c.account_id == account_id, _unsettled())
            ).scalar_one()
        )

    def sender_rules(self, account_id: int) -> dict[str, Category]:
        return {
            rule.sender_address: rule.category
            for rule in self.sender_rule_list(account_id)
        }

    def sender_rule_list(self, account_id: int) -> list[SenderRule]:
        """The account's rules in force (not removed), the latest first."""
        removal = mail_sender_rules.alias("removal")
        removed = select(removal.c.id).where(
            removal.c.removes_id == mail_sender_rules.c.id
        )
        query = (
            select(mail_sender_rules)
            .where(
                mail_sender_rules.c.account_id == account_id,
                mail_sender_rules.c.category.is_not(None),
                ~removed.exists(),
            )
            .order_by(mail_sender_rules.c.id.desc())
        )
        return [
            SenderRule(
                id=row.id,
                sender_address=row.sender_address,
                category=Category(row.category),
                created_at=row.created_at,
            )
            for row in self._conn.execute(query)
        ]

    def add_sender_rule(
        self,
        account_id: int,
        sender_address: str,
        category: Category,
        *,
        decision_id: int | None,
        now: datetime,
    ) -> int:
        return int(
            self._conn.execute(
                insert(mail_sender_rules)
                .values(
                    account_id=account_id,
                    sender_address=sender_address,
                    category=category.value,
                    decision_id=decision_id,
                    created_at=now,
                )
                .returning(mail_sender_rules.c.id)
            ).scalar_one()
        )

    def remove_sender_rule(
        self, account_id: int, rule: SenderRule, now: datetime
    ) -> None:
        self._conn.execute(
            insert(mail_sender_rules).values(
                account_id=account_id,
                sender_address=rule.sender_address,
                category=None,
                removes_id=rule.id,
                created_at=now,
            )
        )

    def messages_from(self, account_id: int, sender_address: str) -> list[int]:
        """The account's messages from this exact address whose decision in force is not the user's (Q7: a new rule
        classifies them again)."""
        current = _current_decisions(account_id).subquery()
        query = (
            select(email_messages.c.id)
            .outerjoin(current, current.c.message_id == email_messages.c.id)
            .where(
                email_messages.c.account_id == account_id,
                func.lower(email_messages.c.sender_address) == sender_address,
                or_(current.c.id.is_(None), current.c.author != Author.USER.value),
            )
            .order_by(email_messages.c.id)
        )
        return list(self._conn.execute(query).scalars())

    def messages_citing(self, account_id: int, company: str) -> list[int]:
        """The account's messages whose decision in force (not the user's) names ``company`` as the employer a
        platform cites (``employer.cited``, Q4: classified again once its application exists)."""
        current = _current_decisions(account_id).subquery()
        query = (
            select(current.c.message_id, current.c.proofs)
            .where(
                current.c.author != Author.USER.value,
                current.c.application_id.is_(None),
                current.c.proofs.contains([{"rule": "employer.cited"}]),
            )
            .order_by(current.c.message_id)
        )
        wanted = fold(company).text
        return [
            row.message_id
            for row in self._conn.execute(query)
            if any(
                proof.get("rule") == "employer.cited"
                and fold(str(proof.get("excerpt", ""))).text == wanted
                for proof in row.proofs
            )
        ]

    def labels(self, account_id: int) -> list[Label]:
        """The user's decisions about the account's messages, with the decision each reviewed (Q6, D14)."""
        reviewed = message_decisions.alias("reviewed")
        query = (
            select(
                message_decisions.c.message_id,
                email_messages.c.received_at,
                email_messages.c.sender_address,
                email_messages.c.subject,
                message_decisions.c.rule,
                message_decisions.c.category,
                message_decisions.c.application_id,
                message_decisions.c.decided_at,
                reviewed.c.category.label("reviewed_category"),
                reviewed.c.application_id.label("reviewed_application_id"),
                reviewed.c.level.label("reviewed_level"),
                reviewed.c.author.label("reviewed_author"),
                reviewed.c.rule.label("reviewed_rule"),
                reviewed.c.classify_version.label("reviewed_version"),
            )
            .join(email_messages, email_messages.c.id == message_decisions.c.message_id)
            .outerjoin(reviewed, reviewed.c.id == message_decisions.c.reviews_id)
            .where(
                message_decisions.c.account_id == account_id,
                message_decisions.c.author == Author.USER.value,
            )
            .order_by(message_decisions.c.id)
        )
        return [
            Label(
                message_id=row.message_id,
                received_at=row.received_at,
                sender_address=row.sender_address,
                subject=row.subject,
                gesture=row.rule,
                category=None if row.category is None else Category(row.category),
                application_id=row.application_id,
                decided_at=row.decided_at,
                reviewed_category=None
                if row.reviewed_category is None
                else Category(row.reviewed_category),
                reviewed_application_id=row.reviewed_application_id,
                reviewed_level=None
                if row.reviewed_level is None
                else Level(row.reviewed_level),
                reviewed_author=None
                if row.reviewed_author is None
                else Author(row.reviewed_author),
                reviewed_rule=row.reviewed_rule,
                reviewed_version=row.reviewed_version,
            )
            for row in self._conn.execute(query)
        ]


class SqlStorage:
    """``Storage`` on an engine: one transaction per call, and the advisory locks of a mailbox's collection and of an
    account's classification. ``follow``: what follows a decision in its transaction (decision E4)."""

    def __init__(self, engine: Engine, follow: FollowHook = _follow_nothing) -> None:
        self._engine = engine
        self._follow = follow

    @contextmanager
    def transaction(self) -> Iterator[SqlStore]:
        with self._engine.begin() as connection:
            yield SqlStore(connection, self._follow)

    def lock(self, mailbox_id: int) -> AbstractContextManager[bool]:
        return self._advisory(COLLECT_LOCK_SPACE, mailbox_id)

    def classify_lock(self, account_id: int) -> AbstractContextManager[bool]:
        return self._advisory(CLASSIFY_LOCK_SPACE, account_id)

    def alerts_lock(self, account_id: int) -> AbstractContextManager[bool]:
        return self._advisory(ALERTS_LOCK_SPACE, account_id)

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


def _settled() -> Any:
    """The gestures of each settled transition, and the change a user's « Appliquer » made."""
    return (
        select(
            mail_transition_settlements.c.transition_id,
            func.array_agg(mail_transition_settlements.c.gesture).label("gestures"),
            func.max(mail_transition_settlements.c.change_id)
            .filter(mail_transition_settlements.c.gesture == Gesture.APPLIED.value)
            .label("applied_change"),
        )
        .group_by(mail_transition_settlements.c.transition_id)
        .subquery("settled")
    )


def _transitions() -> Select[Any]:
    settled = _settled()
    return select(
        mail_transitions,
        settled.c.gestures,
        settled.c.applied_change,
    ).outerjoin(settled, settled.c.transition_id == mail_transitions.c.id)


def _unsettled() -> Any:
    return ~(
        select(literal(1))
        .where(mail_transition_settlements.c.transition_id == mail_transitions.c.id)
        .exists()
    )


def _transition(row: Row[Any]) -> Transition:
    return Transition(
        id=row.id,
        message_id=row.message_id,
        decision_id=row.decision_id,
        application_id=row.application_id,
        from_stage=Stage(row.from_stage),
        to_stage=Stage(row.to_stage),
        outcome=Outcome(row.outcome),
        change_id=row.change_id if row.change_id is not None else row.applied_change,
        created_at=row.created_at,
        settled=frozenset(Gesture(gesture) for gesture in row.gestures or ()),
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
