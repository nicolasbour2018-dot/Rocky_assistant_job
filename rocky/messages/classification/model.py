"""The classification of a message: categories, levels, proofs, verdicts, and the ports it runs on.

Decision ``docs/decisions/E2-classification.md``. A message is decided along two independent axes: what it says (its
category) and whom it concerns (the application it is attached to). Codes are English; French labels are shown only
on screen. A decision is appended, never changed: the one in force is the latest (Q13).
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from rocky.candidatures.model import MailTarget
from rocky.messages.model import Query
from rocky.offres.decisions import Author
from rocky.system.events import NewEvent

# Changes whenever a rule, a list or the model's instructions change: kept with every decision (Q6, D14).
CLASSIFY_VERSION = "mail-classify-2026-10-05.5"


class Category(StrEnum):
    """Q2: what a message says."""

    ACKNOWLEDGEMENT = "acknowledgement"
    REJECTION = "rejection"
    INTERVIEW = "interview"
    ASSESSMENT = "assessment"
    OFFER = "offer"
    EMPLOYER_UPDATE = "employer_update"
    RECRUITER_APPROACH = "recruiter_approach"
    JOB_ALERT = "job_alert"
    UNRELATED = "unrelated"


CATEGORY_LABELS = {
    Category.ACKNOWLEDGEMENT: "Accusé de réception",
    Category.REJECTION: "Refus",
    Category.INTERVIEW: "Entretien",
    Category.ASSESSMENT: "Test ou cas pratique",
    Category.OFFER: "Offre",
    Category.EMPLOYER_UPDATE: "Message de l'employeur",
    Category.RECRUITER_APPROACH: "Approche d'un recruteur",
    Category.JOB_ALERT: "Alerte emploi",
    Category.UNRELATED: "Hors recherche",
}

# What an employer answers about an application: the « Retours d'employeurs » of the screen (Q14).
EMPLOYER_CATEGORIES = frozenset(
    {
        Category.ACKNOWLEDGEMENT,
        Category.REJECTION,
        Category.INTERVIEW,
        Category.ASSESSMENT,
        Category.OFFER,
        Category.EMPLOYER_UPDATE,
    }
)


class Level(StrEnum):
    """Q4, Q9: three levels, each with its reasons; a low decision is shown « À vérifier » (Q10)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


LEVEL_LABELS = {
    Level.HIGH: "Confiance haute",
    Level.MEDIUM: "Confiance moyenne",
    Level.LOW: "À vérifier",
}


class Tier(StrEnum):
    """Where a proof comes from: the stages of the classification."""

    THREAD = "thread"  # the Gmail thread of a message already attached
    SENDER = "sender"  # an exact sender address (alerts, out of the search)
    PLATFORM = "platform"  # a relaying platform and the form of its subject
    DOMAIN = "domain"  # the exact domain of an applied employer
    NAME = "name"  # the exact name of an applied employer, or the title of its offer
    PHRASE = "phrase"  # an explicit sentence of intent
    SIGNAL = "signal"  # a sign of the job search, or its absence
    MODEL = "model"  # the language model, with its quotation checked


TIER_LABELS = {
    Tier.THREAD: "Fil de discussion",
    Tier.SENDER: "Expéditeur",
    Tier.PLATFORM: "Plateforme",
    Tier.DOMAIN: "Domaine de l'employeur",
    Tier.NAME: "Nom de l'employeur",
    Tier.PHRASE: "Phrase du message",
    Tier.SIGNAL: "Signaux de recherche",
    Tier.MODEL: "Modèle de langage",
}


@dataclass(frozen=True)
class Proof:
    """One reason of a decision: ``excerpt`` quotes the message (or names its sender), ``reason`` says it in French."""

    tier: Tier
    rule: str
    excerpt: str
    reason: str


@dataclass(frozen=True)
class Verdict:
    """A decision about a message. ``proofs[0]`` is the one that gave the category (or why there is none)."""

    category: Category | None
    application_id: int | None
    level: Level
    author: Author
    proofs: tuple[Proof, ...]

    def __post_init__(self) -> None:
        if not self.proofs:
            raise ValueError("a decision needs at least one proof")


@dataclass(frozen=True)
class Pending:
    """What the rules found about a message they could not decide alone: it goes to the language model (Q5, Q12).

    ``candidates`` are the applications offered to the model; ``attached`` the one the rules identified, if any, at
    ``attached_level``; ``category`` the one an explicit sentence gave, if any.
    """

    candidates: tuple[MailTarget, ...]
    findings: tuple[Proof, ...]
    attached: int | None = None
    attached_level: Level = Level.MEDIUM
    category: Category | None = None


@dataclass(frozen=True)
class MailToClassify:
    """A stored message, as the classification reads it."""

    id: int
    mailbox_id: int
    thread_id: str
    received_at: datetime
    sender: str
    sender_address: str | None
    subject: str
    body_text: str
    found_by: tuple[Query, ...] = ()


@dataclass(frozen=True)
class Context:
    """What the rules know of the account: its applications that may receive mail, and the threads already attached."""

    targets: tuple[MailTarget, ...] = ()
    # (mailbox id, thread id) -> the application a message of that thread is attached to.
    threads: dict[tuple[int, str], int] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredDecision:
    """The decision in force of a message, as the screen shows it."""

    id: int
    message_id: int
    category: Category | None
    application_id: int | None
    level: Level
    author: Author
    proofs: tuple[Proof, ...]
    version: str
    decided_at: datetime


@dataclass(frozen=True)
class SortedMessage:
    """A message of the list « Messages triés » (Q14) with its decision in force (None: waiting for one)."""

    id: int
    mailbox_address: str
    received_at: datetime
    sender: str
    subject: str
    found_by: tuple[Query, ...]
    decision: StoredDecision | None


class View(StrEnum):
    """The filters of the screen (Q14)."""

    # Employers' replies, decisions to check and messages waiting: the default view.
    TO_LOOK_AT = "a-regarder"
    TO_CHECK = "a-verifier"
    EMPLOYERS = "retours"
    ALERTS = "alertes"
    APPROACHES = "approches"
    UNRELATED = "hors-recherche"
    WAITING = "en-attente"
    ALL = "tous"


VIEW_LABELS = {
    View.TO_LOOK_AT: "À regarder",
    View.TO_CHECK: "À vérifier",
    View.EMPLOYERS: "Retours d'employeurs",
    View.ALERTS: "Alertes",
    View.APPROACHES: "Approches",
    View.UNRELATED: "Hors recherche",
    View.WAITING: "En attente",
    View.ALL: "Tous",
}


class CallOutcome(StrEnum):
    """What came of a call to the language model (Q18: every call is a row, for the limits and D14)."""

    ACCEPTED = "accepted"  # the answer is the decision
    REFUSED = (
        "refused"  # an answer that failed its checks: the decision says « À vérifier »
    )
    FAILED = "failed"  # no usable answer: no decision, the message waits


@dataclass(frozen=True)
class Limits:
    """Q18: calls to the language model per account, over the last hour and the last day."""

    per_hour: int = 20
    per_day: int = 60


class ClassificationStore(Protocol):
    """The SQL of the classification, inside the caller's transaction; never commits."""

    def undecided(
        self, account_id: int, after_id: int, limit: int
    ) -> list[MailToClassify]:
        """Messages of the account without any decision, after ``after_id``, in the order they were collected."""
        ...

    def messages_of(
        self, account_id: int, after_id: int, limit: int
    ) -> list[MailToClassify]: ...

    def has_decision(self, message_id: int) -> bool: ...

    def lock_message(self, message_id: int) -> None:
        """Holds the message's row until the end of the transaction (two writers decide once)."""
        ...

    def attached_threads(self, account_id: int) -> dict[tuple[int, str], int]: ...

    def current_author(self, message_id: int) -> Author | None: ...

    def add_decision(
        self, account_id: int, message_id: int, verdict: Verdict, now: datetime
    ) -> int: ...

    def add_call(
        self,
        account_id: int,
        message_id: int,
        *,
        outcome: CallOutcome,
        reason: str | None,
        duration_ms: int,
        now: datetime,
    ) -> None: ...

    def calls_since(self, account_id: int, since: datetime) -> int: ...

    def append_event(self, event: NewEvent) -> int: ...


class ClassificationStorage(Protocol):
    def transaction(self) -> AbstractContextManager[ClassificationStore]: ...

    def classify_lock(self, account_id: int) -> AbstractContextManager[bool]:
        """Holds the account's classification lock while open; False when another process holds it."""
        ...


class Targets(Protocol):
    """The applications of the account that may receive mail (the module ``candidatures``, Q11)."""

    def __call__(self, account_id: int) -> Sequence[MailTarget]: ...
