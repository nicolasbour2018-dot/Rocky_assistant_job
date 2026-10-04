"""The mail collection assembled on the database and Google: used by the planner, the screen and ``rocky-admin``.

Decision ``docs/decisions/E1-collecte.md``. After each collection, the hook ``on_collected`` receives the ids of the
messages it wrote, once they are committed: the only way in for what decides about a message (E2, E4).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx2
from sqlalchemy import Engine

from rocky.messages.gmail import GoogleGmail
from rocky.messages.model import (
    Gmail,
    Mailbox,
    MailSync,
    StoredMessage,
    SyncResult,
    SyncStatus,
    Trigger,
)
from rocky.messages.oauth import GoogleOAuth, Grant
from rocky.messages.sql import SqlStorage
from rocky.messages.usecases import (
    Clock,
    CollectBusyError,
    MailboxNotConnectedError,
    collect,
    connect_mailbox,
    disconnect_mailbox,
    recover_interrupted,
)
from rocky.system.config import GmailSettings
from rocky.system.crypto import TokenCipher

logger = logging.getLogger(__name__)

# The messages a collection wrote, after its commit: (account id, message ids), an empty list when nothing is new.
type CollectedHook = Callable[[int, Sequence[int]], None]
RECENT_MESSAGES = 50


class GmailNotConfiguredError(Exception):
    """The Google client or ROCKY_SECRET_KEY is missing (decision E1, Q3)."""


@dataclass(frozen=True)
class MailboxView:
    mailbox: Mailbox
    last: MailSync | None


@dataclass(frozen=True)
class MessagesState:
    mailboxes: list[MailboxView]
    recent: list[StoredMessage]

    @property
    def running(self) -> bool:
        return any(
            view.last is not None and view.last.status is SyncStatus.RUNNING
            for view in self.mailboxes
        )


def nothing_decided(account_id: int, message_ids: Sequence[int]) -> None:
    """E1 decides nothing about a message: E2 and E4 install their own hook."""


class MessagesService:
    def __init__(
        self,
        engine: Engine,
        *,
        settings: GmailSettings,
        clock: Clock,
        on_collected: CollectedHook = nothing_decided,
        transport: httpx2.BaseTransport | None = None,
        gmail: Gmail | None = None,
    ) -> None:
        self.storage = SqlStorage(engine)
        self.settings = settings
        self.oauth = GoogleOAuth(settings, transport=transport)
        self._gmail = gmail or GoogleGmail(self.oauth)
        self._cipher = TokenCipher(settings.secret_key) if settings.secret_key else None
        self._clock = clock
        self._on_collected = on_collected

    @property
    def configured(self) -> bool:
        return self.settings.configured

    @property
    def cipher(self) -> TokenCipher:
        if not self.configured or self._cipher is None:
            raise GmailNotConfiguredError
        return self._cipher

    def connect(self, account_id: int, grant: Grant) -> tuple[int, bool]:
        return connect_mailbox(
            self.storage,
            self.cipher,
            account_id=account_id,
            address=grant.address,
            refresh_token=grant.refresh_token,
            now=self._clock(),
        )

    def disconnect(self, account_id: int, mailbox_id: int) -> str | None:
        return disconnect_mailbox(
            self.storage,
            self.cipher,
            self.oauth.revoke,
            account_id=account_id,
            mailbox_id=mailbox_id,
            now=self._clock(),
        )

    def collect_mailbox(self, mailbox_id: int, trigger: Trigger) -> SyncResult:
        """One collection, then the hook with what it wrote. Raises ``CollectBusyError``,
        ``MailboxNotConnectedError``."""
        result = collect(
            self.storage,
            self._gmail,
            self.cipher,
            mailbox_id=mailbox_id,
            trigger=trigger,
            clock=self._clock,
        )
        logger.info(
            "collection %s of mailbox %s: %s, %s new",
            result.sync_id,
            mailbox_id,
            result.status,
            result.counts.new,
        )
        try:
            self._on_collected(result.account_id, list(result.written))
        except Exception:
            # The messages are stored; what follows them is told by its own trace.
            logger.exception("hook after collection %s failed", result.sync_id)
        return result

    def collect_account(self, account_id: int, trigger: Trigger) -> list[SyncResult]:
        """Every connected mailbox of the account, one after the other (« Relever maintenant », ``rocky-admin``)."""
        with self.storage.transaction() as store:
            mailboxes = store.connected_mailboxes(account_id)
        return self._collect_each(mailboxes, trigger)

    def collect_all(self) -> list[SyncResult]:
        """The hourly collection (Q7): every connected mailbox. Nothing while Gmail is not configured."""
        if not self.configured:
            return []
        with self.storage.transaction() as store:
            mailboxes = store.connected_mailboxes()
        return self._collect_each(mailboxes, Trigger.SCHEDULED)

    def _collect_each(
        self, mailboxes: Sequence[Mailbox], trigger: Trigger
    ) -> list[SyncResult]:
        results: list[SyncResult] = []
        for mailbox in mailboxes:
            try:
                results.append(self.collect_mailbox(mailbox.id, trigger))
            except CollectBusyError:
                logger.info("mailbox %s is already being collected", mailbox.id)
            except MailboxNotConnectedError:
                logger.info("mailbox %s was disconnected meanwhile", mailbox.id)
        return results

    def recover(self) -> list[int]:
        closed = recover_interrupted(self.storage, clock=self._clock)
        for sync_id in closed:
            logger.warning(
                "collection %s was left running: closed as interrupted", sync_id
            )
        return closed

    def state(self, account_id: int) -> MessagesState:
        with self.storage.transaction() as store:
            mailboxes = store.mailboxes(account_id)
            return MessagesState(
                mailboxes=[
                    MailboxView(mailbox, store.last_sync(mailbox.id))
                    for mailbox in mailboxes
                ],
                recent=store.recent_messages(account_id, RECENT_MESSAGES),
            )
