"""The decisions on the messages (step E4): the transitions a decision gives, how the user settles them, the account's
rules per sender, and the ports they run on.

Decision ``docs/decisions/E4-decisions-ecran.md``. A transition is recorded with the decision that gave it, applied
(the application changed stage, Q1) or proposed (one gesture applies it). « Ce qui a bougé » is the transitions not
settled yet (Q5): nothing leaves it without a gesture. Everything is appended, never changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from rocky.candidatures.model import Stage
from rocky.messages.classification.model import (
    Category,
    Level,
    SortedMessage,
    StoredDecision,
    Verdict,
)
from rocky.offres.decisions import Author
from rocky.system.events import NewEvent


class Outcome(StrEnum):
    """Q1: a transition applied by a rule (confidence high), or proposed to the user (confidence medium, Q10)."""

    APPLIED = "applied"
    PROPOSED = "proposed"


class Gesture(StrEnum):
    """How a transition left « Ce qui a bougé » (Q5)."""

    SEEN = "seen"  # « Vu »: an applied transition, acknowledged
    APPLIED = "applied"  # « Appliquer »: a proposal the user applied
    DISMISSED = "dismissed"  # « Ignorer »: a proposal the user declined
    CANCELLED = "cancelled"  # « Annuler »: an applied transition the user undid
    CORRECTED = "corrected"  # the message was corrected (Q3)
    REPLACED = "replaced"  # a later decision about the message proposes something else


GESTURE_LABELS = {
    Gesture.SEEN: "Vu",
    Gesture.APPLIED: "Appliquée",
    Gesture.DISMISSED: "Ignorée",
    Gesture.CANCELLED: "Annulée",
    Gesture.CORRECTED: "Message corrigé",
    Gesture.REPLACED: "Remplacée",
}

# Q7: a rule per sender only gives a category that concerns no application.
RULE_CATEGORIES = frozenset(
    {Category.RECRUITER_APPROACH, Category.JOB_ALERT, Category.UNRELATED}
)


class InvalidGestureError(ValueError):
    """The gesture cannot be made as asked; the message is shown to the user (French)."""


@dataclass(frozen=True)
class TransitionPlan:
    """What a decision gives its application: ``stage`` applied or proposed."""

    outcome: Outcome
    stage: Stage


@dataclass(frozen=True)
class Transition:
    """A stored transition and the gestures that settled it (none: it is in « Ce qui a bougé »)."""

    id: int
    message_id: int
    decision_id: int
    application_id: int
    from_stage: Stage
    to_stage: Stage
    outcome: Outcome
    # The change of the application: written with an applied transition, or when the user applied a proposal.
    change_id: int | None
    created_at: datetime
    settled: frozenset[Gesture] = frozenset()

    @property
    def pending(self) -> bool:
        return not self.settled

    @property
    def undone(self) -> bool:
        return bool(self.settled & {Gesture.CANCELLED, Gesture.CORRECTED})


@dataclass(frozen=True)
class Moved:
    """One line of « Ce qui a bougé »: a transition not settled, with the message and the decision that gave it."""

    transition: Transition
    subject: str
    sender: str
    received_at: datetime
    author: Author
    category: Category | None


@dataclass(frozen=True)
class MessageRef:
    """What the gestures read of a stored message."""

    id: int
    mailbox_address: str
    gmail_id: str
    received_at: datetime
    sender: str
    sender_address: str | None
    subject: str
    # The text part, read decoded (``classification.rules.readable``): « Créer la candidature » reads the title in it.
    body_text: str = ""


@dataclass(frozen=True)
class SenderRule:
    """Q7: a rule of the account, in force until removed."""

    id: int
    sender_address: str
    category: Category
    created_at: datetime


@dataclass(frozen=True)
class Corrected:
    """What a correction did: its decision, the transition it proposes, and what stayed or was learnt."""

    decision_id: int
    # Q3: a transition the message gave stays, the user having changed the application since.
    kept: bool = False
    proposal_id: int | None = None
    rule_address: str | None = None
    domain: str | None = None


@dataclass(frozen=True)
class Label:
    """One label of D14 (Q6): the user's decision about a message and the decision of Rocky it reviewed."""

    message_id: int
    received_at: datetime
    sender_address: str | None
    subject: str
    gesture: str  # the rule of the user's decision: ``user.corrected``, ``user.confirmed``, ``user.created``
    category: Category | None
    application_id: int | None
    decided_at: datetime
    reviewed_category: Category | None
    reviewed_application_id: int | None
    reviewed_level: Level | None
    reviewed_author: Author | None
    reviewed_rule: str | None
    reviewed_version: str | None


@dataclass(frozen=True)
class MessageGroup:
    """Q8: the messages of one application in a list, the most decisive first; a message without one is alone."""

    head: SortedMessage
    others: tuple[SortedMessage, ...] = ()


class Applications(Protocol):
    """What the decisions ask of the module ``candidatures`` (its public functions), in the same transaction."""

    def stage(self, account_id: int, application_id: int) -> Stage | None:
        """The stage of an open application, its row held; None for a cancelled one or one of another account."""
        ...

    def move(
        self,
        account_id: int,
        application_id: int,
        stage: Stage,
        *,
        author: Author,
        message_id: int,
        now: datetime,
        today: date,
    ) -> int | None:
        """Change the stage; the change's id, None when already there."""
        ...

    def in_force(self, account_id: int, application_id: int, change_id: int) -> bool:
        """The change is not cancelled (nor a cancellation)."""
        ...

    def cancel(
        self, account_id: int, application_id: int, change_id: int, now: datetime
    ) -> bool:
        """Cancel the change while it is the application's latest in force; False otherwise."""
        ...

    def learn_domain(
        self, account_id: int, application_id: int, domain: str, now: datetime
    ) -> bool: ...

    def open_outside(
        self, account_id: int, offer_id: int, sent_on: date, now: datetime
    ) -> int:
        """The application made outside Rocky, at « Envoyée » (Q4)."""
        ...


class Offers(Protocol):
    """What « Créer la candidature » asks of the module ``offres``, in the same transaction (Q4, Q12)."""

    def record_message_offer(
        self,
        account_id: int,
        *,
        message_id: int,
        company: str,
        title: str,
        link: str,
        now: datetime,
        today: date,
    ) -> int: ...


class DecisionStore(Protocol):
    """The SQL of the decisions on the messages, inside the caller's transaction; never commits."""

    def lock_message(self, message_id: int) -> None: ...

    def message(self, account_id: int, message_id: int) -> MessageRef | None: ...

    def current_decision(self, message_id: int) -> StoredDecision | None: ...

    def add_decision(
        self,
        account_id: int,
        message_id: int,
        verdict: Verdict,
        now: datetime,
        *,
        reviews_id: int | None = None,
    ) -> int: ...

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
    ) -> int: ...

    def transition(self, account_id: int, transition_id: int) -> Transition | None:
        """The transition, its row held (two gestures on it run one after the other)."""
        ...

    def transitions_of_message(self, message_id: int) -> list[Transition]: ...

    def settle(
        self,
        account_id: int,
        transition_id: int,
        gesture: Gesture,
        *,
        change_id: int | None,
        now: datetime,
    ) -> None: ...

    def add_sender_rule(
        self,
        account_id: int,
        sender_address: str,
        category: Category,
        *,
        decision_id: int | None,
        now: datetime,
    ) -> int: ...

    def sender_rule_list(self, account_id: int) -> list[SenderRule]: ...

    def remove_sender_rule(
        self, account_id: int, rule: SenderRule, now: datetime
    ) -> None: ...

    def append_event(self, event: NewEvent) -> int: ...

    def applications(self) -> Applications: ...
