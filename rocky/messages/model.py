"""The mail collection: mailboxes, collected messages, collections and the ports they run on.

Decision ``docs/decisions/E1-collecte.md``. Codes are English; French labels are shown only on screen.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from rocky.system.events import NewEvent

# Q7: one collection an hour, for every connected mailbox.
COLLECT_EVERY = timedelta(hours=1)


class Query(StrEnum):
    """The two Gmail queries (Q4)."""

    REPLIES = "replies"
    ALERTS = "alerts"


# Where a message comes from, never what it is (recette of E1): the sorting is step E2.
QUERY_LABELS = {
    Query.REPLIES: "Boîte principale",
    Query.ALERTS: "Expéditeur d'alertes",
}


class MailboxStatus(StrEnum):
    CONNECTED = "connected"
    # Google refused the refresh token (revoked, expired in the "Testing" mode of Google, password changed).
    ACCESS_LOST = "access_lost"
    DISCONNECTED = "disconnected"


MAILBOX_STATUS_LABELS = {
    MailboxStatus.CONNECTED: "Connectée",
    MailboxStatus.ACCESS_LOST: "À reconnecter",
    MailboxStatus.DISCONNECTED: "Déconnectée",
}


class Trigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class SyncStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


SYNC_STATUS_LABELS = {
    SyncStatus.RUNNING: "En cours",
    SyncStatus.COMPLETED: "Terminée",
    SyncStatus.PARTIAL: "Partielle",
    SyncStatus.FAILED: "Échouée",
    SyncStatus.INTERRUPTED: "Interrompue",
}


@dataclass(frozen=True)
class Mailbox:
    id: int
    account_id: int
    address: str
    status: MailboxStatus
    connected_at: datetime
    # The refresh token, sealed with ``ROCKY_SECRET_KEY``; None once disconnected.
    sealed_token: bytes | None


@dataclass(frozen=True)
class Attachment:
    name: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class CollectedMessage:
    """A Gmail message as Rocky keeps it (Q5); never changed once written."""

    gmail_id: str
    thread_id: str
    received_at: datetime
    sender: str
    sender_address: str | None
    recipients: str
    subject: str
    snippet: str
    body_text: str
    body_html: str
    truncated: bool
    labels: tuple[str, ...]
    attachments: tuple[Attachment, ...]
    rfc822_id: str | None


@dataclass(frozen=True)
class SyncCounts:
    """``listed``: identifiers the queries gave; ``known`` among them were already stored (never downloaded again);
    ``new``: messages written; ``not_written``: messages a failure stopped (taken up again by the next collection).
    """

    listed: int = 0
    known: int = 0
    new: int = 0
    not_written: int = 0


@dataclass(frozen=True)
class MailSync:
    id: int
    mailbox_id: int
    account_id: int
    trigger: Trigger
    status: SyncStatus
    started_at: datetime
    finished_at: datetime | None
    window_start: datetime
    reason: str | None
    counts: SyncCounts


@dataclass(frozen=True)
class StoredMessage:
    """A stored message as the raw list shows it (Q8)."""

    id: int
    mailbox_address: str
    received_at: datetime
    sender: str
    subject: str
    found_by: tuple[Query, ...]


class GmailError(Exception):
    """Gmail or Google gave no usable answer; ``reason`` is shown as is (French), without any token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AccessLostError(GmailError):
    """Google refused the refresh token: the mailbox must be connected again."""


class MessageUnreadableError(Exception):
    """A message whose content Rocky cannot read; ``reason`` is French."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MailReader(Protocol):
    """One mailbox, read only, for one collection."""

    def list_ids(self, query: str) -> list[str]:
        """Identifiers of every message matching ``query`` (all pages)."""
        ...

    def get(self, gmail_id: str) -> dict[str, object]:
        """The whole message (``format=full``), as Gmail gives it."""
        ...


class Gmail(Protocol):
    """Google, for the mailboxes: opens a reader on a refresh token."""

    def reader(self, refresh_token: str) -> AbstractContextManager[MailReader]:
        """Raises ``AccessLostError`` when Google refuses the token, ``GmailError`` otherwise."""
        ...


class Store(Protocol):
    """The SQL of the module ``messages``, on a connection inside the caller's transaction; never commits."""

    def connected_mailboxes(self, account_id: int | None = None) -> list[Mailbox]: ...

    def mailboxes(self, account_id: int) -> list[Mailbox]: ...

    def mailbox(self, mailbox_id: int) -> Mailbox | None: ...

    def find_mailbox(self, account_id: int, address: str) -> Mailbox | None: ...

    def add_mailbox(
        self, account_id: int, address: str, sealed_token: bytes, now: datetime
    ) -> int: ...

    def set_mailbox(
        self,
        mailbox_id: int,
        *,
        status: MailboxStatus,
        sealed_token: bytes | None,
        now: datetime,
    ) -> None: ...

    def known_ids(self, mailbox_id: int, gmail_ids: Sequence[str]) -> set[str]: ...

    def add_message(
        self,
        mailbox: Mailbox,
        message: CollectedMessage,
        *,
        found_by: Sequence[Query],
        sync_id: int,
        now: datetime,
    ) -> int | None:
        """The new row's id, or None when the message is already stored (written by another collection)."""
        ...

    def start_sync(
        self, mailbox: Mailbox, trigger: Trigger, window_start: datetime, now: datetime
    ) -> int: ...

    def finish_sync(
        self,
        sync_id: int,
        *,
        status: SyncStatus,
        reason: str | None,
        counts: SyncCounts,
        now: datetime,
    ) -> None: ...

    def get_sync(self, sync_id: int) -> MailSync | None: ...

    def running_syncs(self) -> list[MailSync]: ...

    def last_completed_sync(self, mailbox_id: int) -> MailSync | None: ...

    def last_sync(self, mailbox_id: int) -> MailSync | None: ...

    def recent_messages(self, account_id: int, limit: int) -> list[StoredMessage]: ...

    def append_event(self, event: NewEvent) -> int: ...


class Storage(Protocol):
    """Transactions and the lock of a mailbox's collection."""

    def transaction(self) -> AbstractContextManager[Store]:
        """One transaction: committed on exit, rolled back on error."""
        ...

    def lock(self, mailbox_id: int) -> AbstractContextManager[bool]:
        """Holds the mailbox's collection lock while open; False when another process holds it."""
        ...


@dataclass
class SyncResult:
    """A closed collection and the ids of the messages it wrote (the only ones a decision may follow)."""

    sync_id: int
    mailbox_id: int
    account_id: int
    status: SyncStatus = SyncStatus.RUNNING
    reason: str | None = None
    counts: SyncCounts = field(default_factory=SyncCounts)
    written: list[int] = field(default_factory=list)
