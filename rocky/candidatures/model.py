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
    # « Fait » (decision D6, Q5): the action in force is done; the change sets the next one, as a next action does.
    ACTION_DONE = "action_done"


# The stages where « Fait » is offered (D6, Q5): before the sending, the action is done by the step's own gesture.
FOLLOW_UP_STAGES = frozenset(
    {Stage.SENT, Stage.IN_DISCUSSION, Stage.INTERVIEW, Stage.OFFER}
)

# The stages whose proposed next action stops at the offer's deadline (D6, Q8): the application is not sent yet.
BEFORE_SENDING = frozenset({Stage.PREPARING, Stage.READY, Stage.PREFILLED})

# The language of an application (D6, Q4): one for its CV, letter, message and PDFs; French without a choice.
LANGUAGES = ("fr", "en")
DEFAULT_LANGUAGE = "fr"
LANGUAGE_LABELS = {"fr": "Français", "en": "Anglais"}


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
class MailTarget:
    """An application a received message may concern (decision E2, Q11), as the module ``messages`` sees it."""

    application_id: int
    company: str
    title: str
    stage: Stage
    sent_on: date | None
    # The employer's e-mail domain typed in the dossier (Q3), and the offer's links it may be deduced from.
    employer_domain: str | None
    links: tuple[str, ...]


# The letter and the accompanying message of an application (decision D4).


class LetterOrigin(StrEnum):
    """Where a paragraph of an application's letter comes from (Q11, D14)."""

    GENERIC = "generic"  # the generic letter, as it is
    ADAPTED = "adapted"  # the version adapted by the model, chosen as it is
    EDITED = "edited"  # written or corrected by the user


class LetterState(StrEnum):
    NONE = "none"  # nothing decided yet
    VALIDATED = "validated"
    SKIPPED = "skipped"  # « Pas de lettre pour cette candidature » (Q4)


@dataclass(frozen=True)
class LetterParagraph:
    role: str  # the part it plays in the generic letter (``profil.model.LetterRole`` value)
    text: str
    origin: LetterOrigin
    proposed: str | None = None  # the adapted version shown beside it (kept: D14)
    signals: tuple[str, ...] = ()  # what the checks said of the text kept (Q8)


@dataclass(frozen=True)
class LetterHeader:
    subject: str
    recipient: str  # one line per line of the address block


@dataclass(frozen=True)
class NewLetter:
    language: str
    paragraphs: tuple[LetterParagraph, ...]
    header: LetterHeader
    generic_sha256: str  # the generic letter it started from (Q17)
    checks_version: str


@dataclass(frozen=True)
class LetterVersion:
    """One validated letter of an application; the latest of a language is in force (Q11, Q17)."""

    id: int
    language: str
    paragraphs: tuple[LetterParagraph, ...]
    header: LetterHeader
    generic_sha256: str
    created_at: datetime


@dataclass(frozen=True)
class NoLetter:
    """« Pas de lettre pour cette candidature » (Q4)."""

    id: int
    created_at: datetime


type LetterEntry = LetterVersion | NoLetter


class MessageOrigin(StrEnum):
    GENERATED = "generated"
    EDITED = "edited"


@dataclass(frozen=True)
class NewMessage:
    language: str
    text: str
    origin: MessageOrigin
    proposed: str | None
    signals: tuple[str, ...]
    checks_version: str


@dataclass(frozen=True)
class MessageVersion:
    id: int
    language: str
    text: str
    origin: MessageOrigin
    created_at: datetime


# The revisions of the documents sent, the sending and the prefilling (decision D5).


class RevisionKind(StrEnum):
    CV = "cv"
    LETTER = "letter"


REVISION_LABELS = {RevisionKind.CV: "CV", RevisionKind.LETTER: "Lettre"}


@dataclass(frozen=True)
class NewRevision:
    """A generated PDF, stored under its hash (Q2). ``inputs_sha256``: what it was made from, to tell it is stale."""

    kind: RevisionKind
    language: str
    path: str
    sha256: str
    inputs_sha256: str
    letter_id: int | None = None  # the letter version a letter revision was made from


@dataclass(frozen=True)
class Revision:
    id: int
    application_id: int
    kind: RevisionKind
    language: str
    path: str
    sha256: str
    inputs_sha256: str
    letter_id: int | None
    created_at: datetime


class Channel(StrEnum):
    """Where the application was sent (Q3). A code published is never renamed."""

    COMPANY_SITE = "company_site"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    WELCOME_TO_THE_JUNGLE = "welcome_to_the_jungle"
    APEC = "apec"
    HELLOWORK = "hellowork"
    FRANCE_TRAVAIL = "france_travail"
    EMAIL = "email"
    OTHER = "other"


CHANNEL_LABELS = {
    Channel.COMPANY_SITE: "Site de l'entreprise",
    Channel.LINKEDIN: "LinkedIn",
    Channel.INDEED: "Indeed",
    Channel.WELCOME_TO_THE_JUNGLE: "Welcome to the Jungle",
    Channel.APEC: "Apec",
    Channel.HELLOWORK: "Hellowork",
    Channel.FRANCE_TRAVAIL: "France Travail",
    Channel.EMAIL: "E-mail",
    Channel.OTHER: "Autre",
}


@dataclass(frozen=True)
class NewSending:
    """« J'ai envoyé ma candidature » (Q3, Q5): when, where, and with what exactly (None: no document of Rocky)."""

    sent_on: date
    channel: Channel
    channel_detail: str | None = None
    cv_revision_id: int | None = None
    letter_revision_id: int | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class Sending:
    """A confirmed sending; in force while the stage change « Envoyée » it documents is (``change_id``)."""

    id: int
    application_id: int
    change_id: int
    sent_on: date
    channel: Channel
    channel_detail: str | None
    cv_revision_id: int | None
    letter_revision_id: int | None
    message_id: int | None
    created_at: datetime


# DORMANT (decision D5, acceptance of 04/10): NewPrefill and Prefill serve the prefilling by the Rocky workstation,
# kept but not run (``web.PREFILL_ENABLED``). The stage « Préremplie » stays: the user may still choose it.
@dataclass(frozen=True)
class NewPrefill:
    """A form prefilled by the workstation (Q1, Q4, Q6): what it was given and what it reported."""

    target_url: str
    cv_revision_id: int
    letter_revision_id: int | None
    message_id: int | None
    filled: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class Prefill:
    id: int
    application_id: int
    target_url: str
    cv_revision_id: int
    letter_revision_id: int | None
    message_id: int | None
    filled: tuple[str, ...]
    missing: tuple[str, ...]
    created_at: datetime


# The notes of an application (decision D6, Q6): appended, never rewritten; a removal is a row of its own.


NOTE_MAX_LENGTH = 4000


@dataclass(frozen=True)
class NoteRow:
    """One stored row: a note (``text``), or the removal of one (``removes``)."""

    id: int
    application_id: int
    text: str | None
    removes: int | None
    created_at: datetime


@dataclass(frozen=True)
class Note:
    id: int
    text: str
    created_at: datetime


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

    def letters(self, application_id: int) -> list[LetterEntry]:
        """The letters validated and the « no letter » of the application, in the order they were written."""
        ...

    def insert_letter(
        self,
        account_id: int,
        application_id: int,
        letter: NewLetter | None,
        now: datetime,
    ) -> int:
        """Append a validated letter, or « no letter » with None; returns its id."""
        ...

    def messages(self, application_id: int) -> list[MessageVersion]: ...

    def insert_message(
        self,
        account_id: int,
        application_id: int,
        message: NewMessage,
        now: datetime,
    ) -> int: ...

    def revisions(self, application_id: int) -> list[Revision]:
        """The revisions of the application, in the order they were generated."""
        ...

    def insert_revision(
        self,
        account_id: int,
        application_id: int,
        revision: NewRevision,
        now: datetime,
    ) -> int: ...

    def sendings(self, application_id: int) -> list[Sending]: ...

    def insert_sending(
        self,
        account_id: int,
        application_id: int,
        change_id: int,
        sending: NewSending,
        now: datetime,
    ) -> int: ...

    def prefills(self, application_id: int) -> list[Prefill]: ...

    def insert_prefill(
        self,
        account_id: int,
        application_id: int,
        prefill: NewPrefill,
        now: datetime,
    ) -> int: ...

    def notes(self, application_id: int) -> list[NoteRow]:
        """The notes and their removals, in the order they were written."""
        ...

    def insert_note(
        self,
        account_id: int,
        application_id: int,
        *,
        text: str | None,
        removes: int | None,
        now: datetime,
    ) -> int: ...

    def language(self, application_id: int) -> str | None:
        """The language chosen last; None when none was chosen."""
        ...

    def insert_language(
        self, account_id: int, application_id: int, language: str, now: datetime
    ) -> None: ...

    def employer_domain(self, application_id: int) -> str | None:
        """The employer's e-mail domain typed last; None when none is (or it was removed)."""
        ...

    def insert_employer_domain(
        self, account_id: int, application_id: int, domain: str | None, now: datetime
    ) -> None: ...

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
