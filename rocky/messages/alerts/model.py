"""The job alerts as a source of offers: the cards of an alert, what reading it gave, and the ports it runs on.

Decision ``docs/decisions/E3-alertes.md``. A card always gives an offer, without the network (Q2); its posting is then
read through its link when it can be, and an unread posting keeps its reason (Q5). Codes are English; French labels
are shown only on screen.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from rocky.offres.imports.model import ImportResult
from rocky.offres.sources.model import CollectedOffer
from rocky.system.events import NewEvent

# Changes whenever a reader, the offer of a card or a limit changes: kept with every reading (D14).
ALERTS_VERSION = "alerts-2026-10-05.3"
# Q8: at most this many alerts give their offers per day and per account (the most recent first), and an alert older
# than this gives nothing (useless calls, postings probably closed). « Pour le moment »: to be reviewed with use.
ALERTS_PER_DAY = 10
ALERT_MAX_AGE = timedelta(days=3)


class Platform(StrEnum):
    """The platforms whose alerts Rocky reads, each with a reader written on a real alert (Q6)."""

    HELLOWORK = "hellowork"
    CADREMPLOI = "cadremploi"
    EFINANCIALCAREERS = "efinancialcareers"
    LINKEDIN = "linkedin"


PLATFORM_LABELS = {
    Platform.HELLOWORK: "Hellowork",
    Platform.CADREMPLOI: "Cadremploi",
    Platform.EFINANCIALCAREERS: "eFinancialCareers",
    Platform.LINKEDIN: "LinkedIn",
}


class ReadingStatus(StrEnum):
    """What reading an alert gave."""

    READ = "read"
    # No reader for this sender: the alert is shown as not read, never ignored (Q6).
    UNKNOWN_FORMAT = "unknown_format"
    # A reader, but no card in the message: its format changed, or it holds no offer.
    NO_CARD = "no_card"
    # An unexpected error while reading it (its trace is in the log).
    FAILED = "failed"
    # Q8: older than ``ALERT_MAX_AGE``, it gives nothing.
    TOO_OLD = "too_old"


READING_LABELS = {
    ReadingStatus.READ: "Alerte lue",
    ReadingStatus.UNKNOWN_FORMAT: "Format d'alerte non lu",
    ReadingStatus.NO_CARD: "Aucune offre trouvée dans l'alerte",
    ReadingStatus.FAILED: "Lecture de l'alerte en échec",
    ReadingStatus.TOO_OLD: "Alerte trop ancienne",
}


class LinkOutcome(StrEnum):
    """What became of the link of a card: its posting read, refused, failed, or not tried (with why)."""

    READ = "read"
    REFUSED = "refused"
    FAILED = "failed"
    INVALID = "invalid"
    NOT_TRIED = "not_tried"


LINK_OUTCOME_LABELS = {
    LinkOutcome.READ: "Fiche lue",
    LinkOutcome.REFUSED: "Fiche refusée",
    LinkOutcome.FAILED: "Fiche non lue",
    LinkOutcome.INVALID: "Lien inutilisable",
    LinkOutcome.NOT_TRIED: "Fiche non lue",
}


class NotTried(StrEnum):
    """Why the link of a card was not read."""

    KNOWN_COMPLETE = "known_complete"
    # Readings of the versions before ``.3`` only (fiches of alerts older than 7 days); since Q8, such an alert gives
    # nothing.
    TOO_OLD = "too_old"
    HOST_STOPPED = "host_stopped"
    NO_LINK = "no_link"
    WITHOUT_LINKS = "without_links"


NOT_TRIED_REASONS = {
    NotTried.KNOWN_COMPLETE: "Offre déjà connue avec sa description complète.",
    NotTried.TOO_OLD: "Alerte de plus de 7 jours : la fiche n'est pas lue.",
    NotTried.HOST_STOPPED: "Le site a refusé une lecture précédente pendant ce passage : Rocky ne lui redemande rien.",
    NotTried.NO_LINK: "L'alerte ne donne pas de lien vers la fiche.",
    NotTried.WITHOUT_LINKS: "Passage sans lecture des fiches.",
}


@dataclass(frozen=True)
class AlertMessage:
    """A stored message whose decision in force is « Alerte emploi », as the reading sees it."""

    id: int
    received_at: datetime
    mailbox_address: str
    gmail_id: str
    sender_address: str | None
    subject: str
    body_text: str
    body_html: str


@dataclass(frozen=True)
class AlertCard:
    """One offer as an alert shows it: facts as written, the link of its button, the platform's number when the link
    shows it. ``position``: its rank in the alert, from 1."""

    position: int
    title: str
    company: str | None = None
    location: str | None = None
    contract: str | None = None
    remote: str | None = None
    salary_text: str | None = None
    link: str | None = None
    platform_id: str | None = None


@dataclass(frozen=True)
class CardResult:
    """A card, the offer written from it, and what became of its link."""

    card: AlertCard
    offer: CollectedOffer
    outcome: LinkOutcome
    not_tried: NotTried | None = None
    # French; None only for a posting read.
    reason: str | None = None


@dataclass(frozen=True)
class AlertOffer:
    """A row of « Pourquoi ? » under an alert (Q5): the offer it gave and what became of its link."""

    position: int
    offer_id: int
    title: str
    company: str | None
    created: bool
    outcome: LinkOutcome
    reason: str | None


@dataclass(frozen=True)
class AlertSummary:
    """What an alert gave, as its row in 📬 Messages says it (Q5)."""

    status: ReadingStatus
    platform: Platform | None
    offers: tuple[AlertOffer, ...] = ()
    reason: str | None = None

    @property
    def created(self) -> int:
        return sum(1 for offer in self.offers if offer.created)

    @property
    def read(self) -> int:
        return sum(1 for offer in self.offers if offer.outcome is LinkOutcome.READ)

    @property
    def unread(self) -> int:
        return len(self.offers) - self.read


@dataclass
class AlertsReport:
    """What a pass did."""

    alerts: int = 0
    too_old: int = 0
    offers: int = 0
    created: int = 0
    pages_read: int = 0
    pages_unread: int = 0
    unknown_formats: int = 0
    failed: int = 0
    # Alerts left for a next pass (the day's limit reached, the offers locked by a watch, no profile yet), and why.
    postponed: int = 0
    reason: str | None = None
    by_platform: dict[str, int] = field(default_factory=dict)


class AlertsBusyError(Exception):
    """The alerts of this account are being read elsewhere."""


class AlertOffers(Protocol):
    """The offers of the account, on the connection of the transaction in progress (module ``offres``)."""

    def complete_keys(
        self, account_id: int, keys: Iterable[tuple[str, str]]
    ) -> set[tuple[str, str]]: ...

    def try_lock(self, account_id: int) -> bool:
        """The lock of the account's offers for this transaction; False while a watch holds it."""
        ...

    def record(
        self, account_id: int, offer: CollectedOffer, *, now: datetime, today: date
    ) -> tuple[int, bool]:
        """The offer written (with its best track and its scores); its id and whether it is new."""
        ...


class AlertStore(Protocol):
    """The reading of the alerts on a connection inside the caller's transaction; never commits."""

    def alerts_to_read(self, account_id: int) -> list[AlertMessage]:
        """The alerts never read, the most recent first."""
        ...

    def alerts_read_since(self, account_id: int, since: datetime) -> int:
        """The alerts that gave their offers since ``since`` (Q8: the day's limit)."""
        ...

    def alert_offers(self, account_id: int) -> AlertOffers | None:
        """The offers of the account, scored with its profile; None when the account has no profile."""
        ...

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
        """The reading of the message, or None when it already has one (an other pass read it meanwhile)."""
        ...

    def add_alert_offer(
        self,
        account_id: int,
        reading_id: int,
        result: CardResult,
        *,
        offer_id: int,
        created: bool,
    ) -> None: ...

    def append_event(self, event: NewEvent) -> int: ...


class AlertStorage(Protocol):
    def transaction(self) -> AbstractContextManager[AlertStore]: ...

    def alerts_lock(self, account_id: int) -> AbstractContextManager[bool]: ...


class PageReading(Protocol):
    """The reading of a posting link (``offres.imports.usecases.import_link`` on a public HTTP client)."""

    def __call__(self, link: str, *, today: date) -> ImportResult: ...
