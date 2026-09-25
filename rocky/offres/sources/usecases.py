"""Collection use cases: ask every source, isolate each failure, and say why a source gave nothing.

Nothing is written: the watch (C6) stores offers, their tracks and their scores as one unit.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    DetailSource,
    JobSource,
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.offres.sources.rules import unique_queries

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    OK = "ok"
    REFUSED = "refused"
    FAILED = "failed"
    PENDING_ACCESS = "pending_access"
    NOT_CONFIGURED = "not_configured"


OUTCOME_LABELS = {
    Outcome.OK: "Collectée",
    Outcome.REFUSED: "Refusée par la plateforme",
    Outcome.FAILED: "En panne",
    Outcome.PENDING_ACCESS: "En attente d'accès",
    Outcome.NOT_CONFIGURED: "Non configurée",
}
UNAVAILABLE = {
    Availability.PENDING_ACCESS: Outcome.PENDING_ACCESS,
    Availability.NOT_CONFIGURED: Outcome.NOT_CONFIGURED,
}


@dataclass(frozen=True)
class SkippedQuery:
    query: SearchQuery
    reason: str


@dataclass(frozen=True)
class SourceOutcome:
    """What one source gave: its offers (kept even when it stopped halfway), and why it stopped or skipped."""

    source: SourceCode
    status: Outcome
    filters_location: bool
    offers: tuple[CollectedOffer, ...] = ()
    skipped: tuple[SkippedQuery, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class CollectionReport:
    outcomes: tuple[SourceOutcome, ...]

    @property
    def offers(self) -> list[CollectedOffer]:
        return [offer for outcome in self.outcomes for offer in outcome.offers]


@dataclass(frozen=True)
class DetailReport:
    offers: tuple[CollectedOffer, ...]
    # Sources that refused their detail: asked once, then left alone for the rest of the collection.
    refused: dict[SourceCode, str] = field(default_factory=dict)


def collect(
    sources: Sequence[JobSource], queries: Sequence[SearchQuery], limit: int
) -> CollectionReport:
    """One outcome per source, in the order of ``sources``; a source never stops the others."""
    return CollectionReport(
        tuple(_collect_one(source, queries, limit) for source in sources)
    )


def _collect_one(
    source: JobSource, queries: Sequence[SearchQuery], limit: int
) -> SourceOutcome:
    availability = source.availability()
    if availability in UNAVAILABLE:
        return SourceOutcome(
            source.code, UNAVAILABLE[availability], source.filters_location
        )
    offers: dict[str, CollectedOffer] = {}
    skipped: list[SkippedQuery] = []

    def outcome(status: Outcome, reason: str | None = None) -> SourceOutcome:
        return SourceOutcome(
            source.code,
            status,
            source.filters_location,
            tuple(offers.values()),
            tuple(skipped),
            reason,
        )

    try:
        for query in unique_queries(queries, filters_location=source.filters_location):
            try:
                found = source.search(query, limit)
            except QuerySkippedError as error:
                skipped.append(SkippedQuery(query, error.reason))
                continue
            for offer in found:
                # Several titles of the tracks find the same posting: it is collected once.
                offers.setdefault(offer.external_id, offer)
    except SourceRefusedError as error:
        return outcome(Outcome.REFUSED, error.reason)
    except SourceFailedError as error:
        return outcome(Outcome.FAILED, error.reason)
    except Exception:
        # A connector bug (a changed page, an unexpected type) must not stop the other sources:
        # it is logged with its trace and shown as a failure of this source.
        logger.exception("source %s failed unexpectedly", source.code)
        return outcome(
            Outcome.FAILED,
            f"Erreur technique dans le connecteur {SOURCE_LABELS[source.code]} "
            "(trace dans le journal de l'application).",
        )
    return outcome(Outcome.OK)


def complete_descriptions(
    sources: Sequence[JobSource], offers: Sequence[CollectedOffer]
) -> DetailReport:
    """Ask the public detail of each incomplete offer whose source has one; a refusal stops that source."""
    detail_sources = {
        source.code: source for source in sources if isinstance(source, DetailSource)
    }
    refused: dict[SourceCode, str] = {}
    completed: list[CollectedOffer] = []
    for offer in offers:
        source = detail_sources.get(offer.source)
        if offer.description_complete or source is None:
            completed.append(offer)
        elif offer.source in refused:
            completed.append(replace(offer, incomplete_reason=refused[offer.source]))
        else:
            completed.append(_completed(source, offer, refused))
    return DetailReport(tuple(completed), refused)


def _completed(
    source: DetailSource, offer: CollectedOffer, refused: dict[SourceCode, str]
) -> CollectedOffer:
    try:
        return source.complete(offer)
    except SourceRefusedError as error:
        reason = f"{error.reason} La description complète se lit sur l'annonce."
        refused[offer.source] = reason
        return replace(offer, incomplete_reason=reason)
    except SourceFailedError as error:
        return replace(offer, incomplete_reason=f"Détail illisible : {error.reason}")
    except Exception:
        logger.exception(
            "detail of %s offer %s failed unexpectedly", offer.source, offer.external_id
        )
        return replace(
            offer,
            incomplete_reason="Erreur technique pendant la lecture du détail "
            "(trace dans le journal de l'application).",
        )
