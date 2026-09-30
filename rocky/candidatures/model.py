"""Applications (step D1): stages, the next action, and the changes they are made of.

Decision ``docs/decisions/D1-dossier-statuts.md``. An application is a list of changes, appended and never changed
(creation, stage, next action, cancellation); its stage and next action are computed from the changes not cancelled
(``rules.dossier``), never stored. Codes are English; French labels are shown only on screen, and error messages are
shown to the user (French).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol

from rocky.offres.decisions import Author, Decision, DecisionValue
from rocky.system.events import NewEvent


class Stage(StrEnum):
    """Q1: the stages forward, in their order, then the three outcomes."""

    PREPARING = "preparing"
    READY = "ready"
    PREFILLED = "prefilled"
    SENT = "sent"
    IN_DISCUSSION = "in_discussion"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    NO_RESPONSE = "no_response"


FORWARD = (
    Stage.PREPARING,
    Stage.READY,
    Stage.PREFILLED,
    Stage.SENT,
    Stage.IN_DISCUSSION,
    Stage.INTERVIEW,
    Stage.OFFER,
)
ISSUES = frozenset({Stage.REJECTED, Stage.WITHDRAWN, Stage.NO_RESPONSE})

STAGE_LABELS = {
    Stage.PREPARING: "En préparation",
    Stage.READY: "Prête à envoyer",
    Stage.PREFILLED: "Préremplie",
    Stage.SENT: "Envoyée",
    Stage.IN_DISCUSSION: "En discussion",
    Stage.INTERVIEW: "Entretien",
    Stage.OFFER: "Offre",
    Stage.REJECTED: "Refusée",
    Stage.WITHDRAWN: "Retirée",
    Stage.NO_RESPONSE: "Sans réponse",
}


@dataclass(frozen=True)
class Proposal:
    """The next action proposed on reaching a stage (Q3): ``days`` after today, or a date to enter when None."""

    label: str
    days: int | None


PROPOSALS: dict[Stage, Proposal] = {
    Stage.PREPARING: Proposal("Finir le dossier", 2),
    Stage.READY: Proposal("Envoyer la candidature", 2),
    Stage.PREFILLED: Proposal("Confirmer l'envoi", 1),
    Stage.SENT: Proposal("Relancer", 7),
    Stage.IN_DISCUSSION: Proposal("Relancer", 7),
    Stage.INTERVIEW: Proposal("Préparer l'entretien", None),
    Stage.OFFER: Proposal("Répondre à l'offre", 3),
}
DEFER_DAYS = (1, 3, 7)


class ChangeKind(StrEnum):
    CREATED = "created"
    STAGE = "stage"
    NEXT_ACTION = "next_action"
    CANCELLATION = "cancellation"


class InvalidChangeError(ValueError):
    """The change cannot be made as given; the message is shown to the user."""


@dataclass(frozen=True)
class NextAction:
    label: str
    due: date


@dataclass(frozen=True)
class NewChange:
    """A change to append. A creation or a stage change also sets the next action (None: no action)."""

    kind: ChangeKind
    stage: Stage | None = None
    next_action: NextAction | None = None
    # The « Intéressé » written with the creation (Q8), cancelled with it (Q9).
    decision_id: int | None = None
    cancels: int | None = None


@dataclass(frozen=True)
class Change:
    """One stored change of an application."""

    id: int
    application_id: int
    kind: ChangeKind
    author: Author
    changed_at: datetime
    stage: Stage | None = None
    next_action: NextAction | None = None
    decision_id: int | None = None
    cancels: int | None = None


@dataclass(frozen=True)
class Application:
    """The identity of an application: one per offer of an account (Q7), reused when it is opened again."""

    id: int
    account_id: int
    offer_id: int


@dataclass(frozen=True)
class Dossier:
    """What the changes of an application amount to (computed, never stored)."""

    # Its creation is in force: False before « Préparer », and once the creation is cancelled.
    open: bool
    stage: Stage | None
    next_action: NextAction | None
    creation: Change | None


class ApplicationStore(Protocol):
    """The applications of the accounts, on a connection inside the caller's transaction; never commits."""

    def application_for_offer(
        self, account_id: int, offer_id: int, now: datetime
    ) -> Application:
        """The application of the offer, created when missing, and locked until the end of the transaction."""
        ...

    def locked_application(
        self, account_id: int, application_id: int
    ) -> Application | None:
        """The application when it belongs to the account, locked until the end of the transaction."""
        ...

    def changes(self, application_id: int) -> list[Change]:
        """The changes of the application, in the order they were made."""
        ...

    def insert_change(
        self,
        account_id: int,
        application_id: int,
        change: NewChange,
        *,
        author: Author,
        now: datetime,
    ) -> Change: ...

    def cv_selection(self, application_id: int) -> Mapping[str, Any] | None:
        """The CV selection in force (decision D3, Q4); None: the rules' proposal."""
        ...

    def insert_cv_selection(
        self,
        account_id: int,
        application_id: int,
        layout: Mapping[str, Any] | None,
        now: datetime,
    ) -> None:
        """Append an adjustment; None goes back to the rules' proposal."""
        ...

    def append_event(self, event: NewEvent) -> None: ...


class OfferDecisions(Protocol):
    """What the applications ask of the module ``offres`` (its public functions), in the same transaction."""

    def decision_in_force(
        self, account_id: int, offer_id: int
    ) -> DecisionValue | None: ...

    def record_interested(
        self, account_id: int, offer_id: int, decision: Decision, now: datetime
    ) -> int:
        """Record the decision, return its id."""
        ...

    def cancel(self, account_id: int, decision_id: int, now: datetime) -> bool:
        """Cancel the decision; False when it was already cancelled."""
        ...
