"""The mail collection and classification assembled on the database, Google and the language model: used by the
planner, the screen and ``rocky-admin``.

Decision ``docs/decisions/E1-collecte.md``. After each collection, the hook ``on_collected`` receives the ids of the
messages it wrote, once they are committed: the only way in for what decides about a message (E2, E4). Decision
``docs/decisions/E2-classification.md``: the classification takes every message of the account without a decision,
so that a message a pass could not decide is taken up by the next one.

Decision ``docs/decisions/E4-decisions-ecran.md``: each decision gives its application's transition in its own
transaction; the user's gestures (« Ce qui a bougé », corrections, « Créer la candidature ») run here, one transaction
each, then classify again by the rules what a new rule or a new application concerns.

Decision ``docs/decisions/E3-alertes.md``: after the classification, the job alerts never read give their offers; the
postings of their links are read on a public HTTP client opened for the pass (``pages``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import timedelta

import httpx2
from sqlalchemy import Engine

from rocky.candidatures import web as candidatures_web
from rocky.candidatures.model import MailTarget
from rocky.messages.alerts.model import (
    AlertsBusyError,
    AlertsReport,
    AlertSummary,
    PageReading,
)
from rocky.messages.alerts.usecases import read_alerts
from rocky.messages.classification.model import (
    Category,
    Limits,
    SortedMessage,
    StoredDecision,
    View,
)
from rocky.messages.classification.usecases import (
    DAY_LIMIT_REASON,
    NOT_CONFIGURED_REASON,
    WITHOUT_MODEL_REASON,
    ClassifyBusyError,
    ClassifyReport,
    classify_messages,
)
from rocky.messages.decisions import usecases as decisions
from rocky.messages.decisions.model import (
    Corrected,
    Label,
    MessageGroup,
    MessageRef,
    Moved,
    SenderRule,
)
from rocky.messages.decisions.rules import (
    cited_employer,
    domain_offered,
    grouped,
    rule_possible,
    written_title,
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
from rocky.profil.model import Profile
from rocky.system.config import GmailSettings, LlmSettings
from rocky.system.crypto import TokenCipher
from rocky.system.llm import JsonModel

logger = logging.getLogger(__name__)

# The messages a collection wrote, after its commit: (account id, message ids), an empty list when nothing is new.
type CollectedHook = Callable[[int, Sequence[int]], None]
# Decision E3: what reads the postings of the alerts' links during one pass (a public HTTP client, closed after it).
type PagesFactory = Callable[[], AbstractContextManager[PageReading]]
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
    # Decision E4: « Ce qui a bougé » (Q5), the messages grouped by application (Q8), the account's rules (Q7).
    moved: tuple[Moved, ...] = ()
    groups: tuple[MessageGroup, ...] = ()
    rules: tuple[SenderRule, ...] = ()
    # Decision E3 (Q5): what each shown alert gave, by message; an alert without one is not read yet.
    alerts: dict[int, AlertSummary] = field(default_factory=dict)

    @property
    def running(self) -> bool:
        return any(
            view.last is not None and view.last.status is SyncStatus.RUNNING
            for view in self.mailboxes
        )


@dataclass(frozen=True)
class Attention:
    """What 🏠 Aujourd'hui shows of the messages (decision F1, Q7): what moved, and how many decisions to check."""

    moved: tuple[Moved, ...]
    to_check: int
    # « Employeur — intitulé » of the applications that moved.
    applications: dict[int, str]


@dataclass(frozen=True)
class CorrectionView:
    """What the panel « Corriger » shows (decision E4, Q6, Q7)."""

    message: MessageRef
    decision: StoredDecision | None
    # « Employeur — intitulé » of the open applications of the account.
    applications: dict[int, str]
    rule_possible: bool
    domain: str | None
    cited_employer: str | None
    # Q13 (acceptance): the offer's title the platform writes in the message.
    title: str | None = None


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
        pages: PagesFactory | None = None,
    ) -> None:
        self.engine = engine
        # E4: every decision gives the transition of its application, in its transaction.
        self.storage = SqlStorage(engine, follow=decisions.follow_decision)
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
        # None: the alerts give their offers from their cards alone (a service without network, in the tests).
        self._pages = pages

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
        only: Sequence[int] | None = None,
    ) -> ClassifyReport:
        """The messages of the account without a decision (``again``: all of them; ``only``: these alone). Raises
        ``ClassifyBusyError``."""
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
            only=only,
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
        """The hook after a collection (E2): every message of the account still without a decision, not only these;
        then the job alerts never read (E3)."""
        try:
            self.classify(account_id)
        except ClassifyBusyError:
            logger.info("account %s is already being classified", account_id)
        try:
            self.read_alerts(account_id)
        except AlertsBusyError:
            logger.info("alerts of account %s are already being read", account_id)

    def read_alerts(self, account_id: int, *, links: bool = True) -> AlertsReport:
        """The job alerts of the account never read give their offers (decision E3); ``links`` False: no posting is
        read. Raises ``AlertsBusyError``."""
        if not links or self._pages is None:
            report = read_alerts(
                self.storage, None, account_id=account_id, clock=self._clock
            )
        else:
            with self._pages() as page:
                report = read_alerts(
                    self.storage, page, account_id=account_id, clock=self._clock
                )
        logger.info(
            "alerts of account %s: %s read, %s offers (%s new), %s postings read, %s unread, %s waiting",
            account_id,
            report.alerts,
            report.offers,
            report.created,
            report.pages_read,
            report.pages_unread,
            report.postponed,
        )
        return report

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
            moved = store.pending_moves(account_id)
            rules = store.sender_rule_list(account_id)
            alerts = store.alert_summaries(
                account_id,
                [
                    message.id
                    for message in messages
                    if message.decision is not None
                    and message.decision.category is Category.JOB_ALERT
                ],
            )
        attached = {
            message.decision.application_id
            for message in messages
            if message.decision is not None
            and message.decision.application_id is not None
        } | {line.transition.application_id for line in moved}
        return MessagesState(
            mailboxes=views,
            view=view,
            messages=messages,
            applications=self._labels(account_id, attached),
            waiting=waiting,
            waiting_reason=reason,
            acknowledgements=acknowledgements,
            moved=tuple(moved),
            groups=tuple(grouped(messages)),
            rules=tuple(rules),
            alerts=alerts,
        )

    def attention(self, account_id: int) -> Attention:
        with self.storage.transaction() as store:
            moved = store.pending_moves(account_id)
            to_check = store.to_check(account_id)
        return Attention(
            moved=tuple(moved),
            to_check=to_check,
            applications=self._labels(
                account_id, {line.transition.application_id for line in moved}
            ),
        )

    def _labels(self, account_id: int, application_ids: set[int]) -> dict[int, str]:
        with self.engine.connect() as connection:
            return candidatures_web.application_labels(
                connection, account_id, application_ids
            )

    # Decisions on the messages (E4)

    def pending_count(self, account_id: int) -> int:
        """The lines of « Ce qui a bougé » (Q5): the counter of the navigation."""
        with self.storage.transaction() as store:
            return store.pending_count(account_id)

    def application_messages(
        self, account_id: int, application_id: int
    ) -> list[SortedMessage]:
        """The messages attached to an application (Q8: the block « Messages » of its dossier)."""
        with self.storage.transaction() as store:
            return store.sorted_messages(
                account_id, View.ALL, SHOWN_MESSAGES, application_id=application_id
            )

    def mark_seen(self, account_id: int, transition_id: int) -> None:
        with self.storage.transaction() as store:
            decisions.mark_seen(
                store,
                account_id=account_id,
                transition_id=transition_id,
                now=self._clock(),
            )

    def dismiss(self, account_id: int, transition_id: int) -> None:
        with self.storage.transaction() as store:
            decisions.dismiss(
                store,
                account_id=account_id,
                transition_id=transition_id,
                now=self._clock(),
            )

    def apply_proposal(self, account_id: int, transition_id: int) -> None:
        with self.storage.transaction() as store:
            decisions.apply_proposal(
                store,
                account_id=account_id,
                transition_id=transition_id,
                now=self._clock(),
            )

    def cancel_transition(self, account_id: int, transition_id: int) -> None:
        with self.storage.transaction() as store:
            decisions.cancel_transition(
                store,
                account_id=account_id,
                transition_id=transition_id,
                now=self._clock(),
            )

    def correction(self, account_id: int, message_id: int) -> CorrectionView:
        """What « Corriger » shows. Raises ``LookupError`` for a message of another account."""
        with self.storage.transaction() as store:
            message = store.message(account_id, message_id)
            if message is None:
                raise LookupError(decisions.UNKNOWN_MESSAGE)
            decision = store.current_decision(message_id)
        with self.engine.connect() as connection:
            applications = candidatures_web.open_application_labels(
                connection, account_id
            )
        return CorrectionView(
            message=message,
            decision=decision,
            applications=applications,
            rule_possible=rule_possible(message.sender_address),
            domain=domain_offered(message.sender_address),
            cited_employer=cited_employer(decision),
            title=written_title(message),
        )

    def correct(
        self,
        account_id: int,
        message_id: int,
        *,
        category: Category,
        application_id: int | None,
        remember_sender: bool,
        remember_domain: bool,
    ) -> Corrected:
        """« Corriger » (Q6), then the messages of a sender the user made a rule for, classified again (Q7)."""
        with self.storage.transaction() as store:
            result = decisions.correct(
                store,
                account_id=account_id,
                message_id=message_id,
                category=category,
                application_id=application_id,
                now=self._clock(),
                remember_sender=remember_sender,
                remember_domain=remember_domain,
            )
            again = (
                []
                if result.rule_address is None
                else store.messages_from(account_id, result.rule_address)
            )
        self._classify_again(account_id, again)
        return result

    def confirm(self, account_id: int, message_id: int) -> None:
        with self.storage.transaction() as store:
            decisions.confirm(
                store, account_id=account_id, message_id=message_id, now=self._clock()
            )

    def create_application(
        self,
        account_id: int,
        message_id: int,
        *,
        company: str,
        title: str,
        link: str,
        profile: Profile,
    ) -> int:
        """« Créer la candidature » (Q4), then the messages citing the same employer, classified again."""
        with self.storage.transaction() as store:
            application_id = decisions.create_application(
                store,
                store.offers(profile),
                account_id=account_id,
                message_id=message_id,
                company=company,
                title=title,
                link=link,
                now=self._clock(),
            )
            again = store.messages_citing(account_id, company)
        self._classify_again(account_id, again)
        return application_id

    def create_in_one_click(
        self, account_id: int, message_id: int, *, profile: Profile
    ) -> tuple[int, str, str] | None:
        """Q13: « Créer la candidature » in one click, with the employer the platform cites and the title it writes:
        the application's id, the employer and the title; None when either cannot be read (the form, prefilled, asks
        the user)."""
        view = self.correction(account_id, message_id)
        if not view.cited_employer or not view.title:
            return None
        application_id = self.create_application(
            account_id,
            message_id,
            company=view.cited_employer,
            title=view.title,
            link="",
            profile=profile,
        )
        return application_id, view.cited_employer, view.title

    def remove_rule(self, account_id: int, rule_id: int) -> None:
        with self.storage.transaction() as store:
            decisions.remove_sender_rule(
                store, account_id=account_id, rule_id=rule_id, now=self._clock()
            )

    def labels(self, account_id: int) -> list[Label]:
        """The user's decisions with the decision each reviewed (Q6, D14): ``rocky-admin messages-etiquettes``."""
        with self.storage.transaction() as store:
            return store.labels(account_id)

    def _classify_again(self, account_id: int, message_ids: Sequence[int]) -> None:
        """By the rules alone, never over the user's decisions; a pass in progress leaves them as they are."""
        if not message_ids:
            return
        try:
            self.classify(account_id, use_model=False, again=True, only=message_ids)
        except ClassifyBusyError:
            logger.warning(
                "account %s is being classified: %s messages not classified again",
                account_id,
                len(message_ids),
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
