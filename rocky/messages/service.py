"""The mail collection and classification assembled on the database, Google and the language model: used by the
planner, the screen and ``rocky-admin``.

Decision ``docs/decisions/E1-collecte.md``. After each collection, the hook ``on_collected`` receives the ids of the
messages it wrote, once they are committed: the only way in for what decides about a message (E2, E4). Decision
``docs/decisions/E2-classification.md``: the classification takes every message of the account without a decision,
so that a message a pass could not decide is taken up by the next one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

import httpx2
from sqlalchemy import Engine

from rocky.candidatures import web as candidatures_web
from rocky.candidatures.model import MailTarget
from rocky.messages.classification.model import Limits, SortedMessage, View
from rocky.messages.classification.usecases import (
    DAY_LIMIT_REASON,
    NOT_CONFIGURED_REASON,
    WITHOUT_MODEL_REASON,
    ClassifyBusyError,
    ClassifyReport,
    classify_messages,
)
from rocky.messages.gmail import GoogleGmail
from rocky.messages.model import (
    Gmail,
    Mailbox,
    MailSync,
    SyncResult,
    SyncStatus,
    Trigger,
)
from rocky.messages.oauth import GoogleOAuth, Grant
from rocky.messages.sql import SqlStorage, SqlStore
from rocky.messages.usecases import (
    Clock,
    CollectBusyError,
    MailboxNotConnectedError,
    collect,
    connect_mailbox,
    disconnect_mailbox,
    recover_interrupted,
)
from rocky.system.config import GmailSettings, LlmSettings
from rocky.system.crypto import TokenCipher
from rocky.system.llm import JsonModel

logger = logging.getLogger(__name__)

# The messages a collection wrote, after its commit: (account id, message ids), an empty list when nothing is new.
type CollectedHook = Callable[[int, Sequence[int]], None]
SHOWN_MESSAGES = 50
NEXT_ROUND_REASON = "Classement au prochain passage (toutes les heures)."


class GmailNotConfiguredError(Exception):
    """The Google client or ROCKY_SECRET_KEY is missing (decision E1, Q3)."""


@dataclass(frozen=True)
class MailboxView:
    mailbox: Mailbox
    last: MailSync | None


@dataclass(frozen=True)
class MessagesState:
    mailboxes: list[MailboxView]
    view: View
    messages: list[SortedMessage]
    # « Employeur — intitulé » of the applications the shown messages are attached to.
    applications: dict[int, str]
    # Messages without a decision yet, and why (Q14).
    waiting: int
    waiting_reason: str | None
    # Acknowledgements, out of the default view (Q19).
    acknowledgements: int = 0

    @property
    def running(self) -> bool:
        return any(
            view.last is not None and view.last.status is SyncStatus.RUNNING
            for view in self.mailboxes
        )


def nothing_decided(account_id: int, message_ids: Sequence[int]) -> None:
    """No decision: the hook of a service built without one (the collection alone, in its tests)."""


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
        llm: LlmSettings | None = None,
        model: JsonModel | None = None,
    ) -> None:
        self.engine = engine
        self.storage = SqlStorage(engine)
        # The language model of the classification (E2); None: the rules only, the others wait for a key.
        self.model = model
        settings_llm = llm or LlmSettings()
        self.limits = Limits(
            per_hour=settings_llm.mail_per_hour, per_day=settings_llm.mail_per_day
        )
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

    def targets(self, account_id: int) -> list[MailTarget]:
        """The applications a message of the account may concern (the module ``candidatures``, Q11)."""
        with self.engine.connect() as connection:
            return candidatures_web.mail_targets(connection, account_id)

    def classify(
        self,
        account_id: int,
        *,
        use_model: bool = True,
        max_calls: int | None = None,
        again: bool = False,
    ) -> ClassifyReport:
        """The messages of the account without a decision (``again``: all of them). Raises ``ClassifyBusyError``."""
        report = classify_messages(
            self.storage,
            account_id=account_id,
            targets=self.targets,
            model=self.model if use_model else None,
            clock=self._clock,
            limits=self.limits,
            max_calls=max_calls,
            again=again,
            no_model_reason=NOT_CONFIGURED_REASON
            if use_model
            else WITHOUT_MODEL_REASON,
        )
        logger.info(
            "classification of account %s: %s by the rules, %s by the model, %s calls, %s waiting",
            account_id,
            report.by_rules,
            report.by_model,
            report.calls,
            report.waiting,
        )
        return report

    def classify_after_collection(
        self, account_id: int, message_ids: Sequence[int]
    ) -> None:
        """The hook after a collection (E2): every message of the account still without a decision, not only these."""
        try:
            self.classify(account_id)
        except ClassifyBusyError:
            logger.info("account %s is already being classified", account_id)

    def state(self, account_id: int, view: View = View.TO_LOOK_AT) -> MessagesState:
        with self.storage.transaction() as store:
            mailboxes = store.mailboxes(account_id)
            messages = store.sorted_messages(account_id, view, SHOWN_MESSAGES)
            waiting = store.waiting(account_id)
            acknowledgements = store.acknowledgements(account_id)
            reason = self._waiting_reason(store, account_id) if waiting else None
            views = [
                MailboxView(mailbox, store.last_sync(mailbox.id))
                for mailbox in mailboxes
            ]
        attached = {
            message.decision.application_id
            for message in messages
            if message.decision is not None
            and message.decision.application_id is not None
        }
        with self.engine.connect() as connection:
            labels = candidatures_web.application_labels(
                connection, account_id, attached
            )
        return MessagesState(
            mailboxes=views,
            view=view,
            messages=messages,
            applications=labels,
            waiting=waiting,
            waiting_reason=reason,
            acknowledgements=acknowledgements,
        )

    def _waiting_reason(self, store: SqlStore, account_id: int) -> str:
        if self.model is None:
            return NOT_CONFIGURED_REASON
        now = self._clock()
        if (
            store.calls_since(account_id, now - timedelta(days=1))
            >= self.limits.per_day
        ):
            return DAY_LIMIT_REASON
        return (
            store.last_failure(account_id, now - timedelta(days=1)) or NEXT_ROUND_REASON
        )
