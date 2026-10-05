"""Scripted sources for the collection use cases (no HTTP)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from rocky.offres.sources.model import (
    Availability,
    CollectedOffer,
    SearchQuery,
    SourceCode,
)

type Behaviour = Callable[[SearchQuery], list[CollectedOffer]]


def offer(
    source: SourceCode, external_id: str, *, complete: bool = True
) -> CollectedOffer:
    return CollectedOffer(
        source=source,
        external_id=external_id,
        url=f"https://{source}.example/{external_id}",
        title=f"Offre {external_id}",
        description="Description complète." if complete else "Extrait...",
        description_complete=complete,
        incomplete_reason=None if complete else "Extrait seulement.",
    )


@dataclass
class FakeSource:
    code: SourceCode
    behaviour: Behaviour
    filters_location: bool = True
    available: Availability = Availability.READY
    queries: list[SearchQuery] = field(default_factory=list)

    def availability(self) -> Availability:
        return self.available

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        self.queries.append(query)
        return self.behaviour(query)[:limit]


@dataclass
class FakeDetailSource(FakeSource):
    detail: Callable[[CollectedOffer], CollectedOffer] = lambda found: replace(
        found, description="Détail.", description_complete=True, incomplete_reason=None
    )
    completed: list[str] = field(default_factory=list)

    def complete(self, offer: CollectedOffer) -> CollectedOffer:
        self.completed.append(offer.external_id)
        return self.detail(offer)
