"""Job sources: stored codes, collected offers, the source ports and their errors.

A source turns a search into offers holding the facts of the posting, as published (no interpretation: contract,
remote work and salary stay source texts, read later by the posting analysis). Nothing here is persisted.
Error reasons are shown to the user, hence in French.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable


class SourceCode(StrEnum):
    APEC = "apec"
    ADZUNA = "adzuna"
    WTTJ = "wttj"
    LINKEDIN = "linkedin"
    WELLFOUND = "wellfound"
    FRANCE_TRAVAIL = "france_travail"


SOURCE_LABELS = {
    SourceCode.APEC: "Apec",
    SourceCode.ADZUNA: "Adzuna",
    SourceCode.WTTJ: "Welcome to the Jungle",
    SourceCode.LINKEDIN: "LinkedIn",
    SourceCode.WELLFOUND: "Wellfound",
    SourceCode.FRANCE_TRAVAIL: "France Travail",
}


def source_label(name: str) -> str:
    """Label of a source name: the platform name of a connector, else the host itself."""
    try:
        return SOURCE_LABELS[SourceCode(name)]
    except ValueError:
        return name


class Availability(StrEnum):
    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    PENDING_ACCESS = "pending_access"


@dataclass(frozen=True)
class SearchQuery:
    """One search: a job title of a track, in one of its locations (``None``: no location)."""

    title: str
    location: str | None = None


@dataclass(frozen=True)
class CollectedOffer:
    """The facts of one posting. ``source`` is a source name: a ``SourceCode`` for a connector, else the host of
    the posting (``hellowork.com``, see ``rules.source_for_url``)."""

    source: str
    external_id: str
    url: str
    title: str
    description: str
    description_complete: bool
    incomplete_reason: str | None = None
    company: str | None = None
    location: str | None = None
    country: str | None = None
    application_url: str | None = None
    contract: str | None = None
    remote: str | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    sector: str | None = None
    published_on: date | None = None
    # Closing date as published (``validThrough`` of a posting page); the posting analysis also reads the text.
    deadline: date | None = None


class SourceError(Exception):
    """A source could not answer; ``reason`` is shown as is."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SourceRefusedError(SourceError):
    """The platform refused an automated request (anti-bot protection): stop asking it for this collection."""


class SourceFailedError(SourceError):
    """The platform answered with an error, an unreadable body, or not at all."""


class NotFoundError(SourceFailedError):
    """The platform has no page for this address (HTTP 404)."""


class InvalidLinkError(SourceError):
    """A posting link that is not read: malformed, not http(s), or aimed at a non-public address."""


class QuerySkippedError(SourceError):
    """This query cannot be sent to this source (for example an unknown location); the other queries go on."""


class JobSource(Protocol):
    code: SourceCode
    # False: the source ignores the location, it is searched once per job title.
    filters_location: bool

    def availability(self) -> Availability: ...

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        """At most ``limit`` offers, from one page of results.

        Raises ``SourceRefusedError``, ``SourceFailedError`` or ``QuerySkippedError``.
        """
        ...


@runtime_checkable
class DetailSource(Protocol):
    """A source whose public detail endpoint gives the full description of an offer."""

    def complete(self, offer: CollectedOffer) -> CollectedOffer:
        """The offer with its full description; raises ``SourceRefusedError`` or ``SourceFailedError``."""
        ...


@runtime_checkable
class LinkSource(DetailSource, Protocol):
    """A source whose posting pages show nothing to a plain reader (an empty JavaScript shell).

    A link to one of its postings is read through its public detail endpoint instead (import by URL, C2).
    """

    code: SourceCode

    def from_link(self, url: str) -> CollectedOffer:
        """The offer a posting link designates, still to complete; raises ``InvalidLinkError``."""
        ...
