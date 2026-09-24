"""Triage prototype data (step B4) — **throwaway**, deleted in C7 with ``prototype_offers.json``.

The offers are real offers of the A1 archive, built by ``docs/procedures/b4-prototype/build_offers.py`` with a
provisional score (a mock-up of the C4 format, not the C4 scoring). Decisions live in memory only.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from rocky.offres.decisions import Decision

DATA_FILE = Path(__file__).with_name("prototype_offers.json")

CONFIDENCE_LABELS = {"low": "faible", "medium": "moyenne", "high": "élevée"}
# Remote work as stored by the old sources (heterogeneous: finding C1).
REMOTE_LABELS = {
    "télétravail": "possible",
    "télétravail partiel": "partiel",
    "partial": "partiel",
    "télétravail complet": "complet",
    "full": "complet",
    "punctual": "ponctuel",
    "no": "aucun",
}
VERDICT_SIGNS = {"good": "✔", "partial": "≈", "bad": "✘", "unknown": "?"}


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    verdict: str
    summary: str
    evidence: str


@dataclass(frozen=True)
class Eliminatory:
    label: str
    evidence: str


@dataclass(frozen=True)
class Salary:
    minimum: float | None
    maximum: float | None
    period: str  # "year" or "day"

    @property
    def text(self) -> str:
        unit = "€ par jour" if self.period == "day" else "€ par an"
        values = [
            f"{v:,.0f}".replace(",", " ") for v in (self.minimum, self.maximum) if v
        ]
        return f"{' – '.join(dict.fromkeys(values))} {unit}"


@dataclass(frozen=True)
class Offer:
    id: int
    title: str
    company: str | None
    city: str | None
    remote: str | None
    contract: str | None
    salary: Salary | None
    source: str
    url: str | None
    published_on: date | None
    deadline: date | None
    description: str
    description_is_full: bool
    tracks: tuple[str, ...]
    score: int
    confidence: str
    components: tuple[Component, ...]
    eliminatory: tuple[Eliminatory, ...]
    skills_found: tuple[str, ...]
    skills_missing: tuple[str, ...]

    @property
    def confidence_label(self) -> str:
        return CONFIDENCE_LABELS[self.confidence]

    @property
    def remote_label(self) -> str | None:
        if not self.remote:
            return None
        return REMOTE_LABELS.get(self.remote.lower(), self.remote)


@dataclass(frozen=True)
class Catalog:
    offers: tuple[Offer, ...]  # by decreasing score
    tracks: dict[str, str]  # key -> label
    threshold: int

    def get(self, offer_id: int) -> Offer | None:
        return next((offer for offer in self.offers if offer.id == offer_id), None)

    def below_threshold(self, offer: Offer) -> bool:
        return offer.score < self.threshold

    def queue(self, decided: set[int]) -> list[Offer]:
        """Offers to examine in triage mode: above the threshold, not decided yet, best first."""
        return [
            o
            for o in self.offers
            if not self.below_threshold(o) and o.id not in decided
        ]


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _offer(raw: dict[str, Any]) -> Offer:
    salary = raw["salary"]
    return Offer(
        id=raw["id"],
        title=raw["title"],
        company=raw["company"],
        city=raw["city"],
        remote=raw["remote"],
        contract=raw["contract"],
        salary=None
        if salary is None
        else Salary(salary["min"], salary["max"], salary["period"]),
        source=raw["source"],
        url=raw["url"],
        published_on=_date(raw["published_on"]),
        deadline=_date(raw["deadline"]),
        description=raw["description"],
        description_is_full=raw["description_is_full"],
        tracks=tuple(raw["tracks"]),
        score=raw["score"],
        confidence=raw["confidence"],
        components=tuple(Component(**component) for component in raw["components"]),
        eliminatory=tuple(Eliminatory(**item) for item in raw["eliminatory"]),
        skills_found=tuple(raw["skills_found"]),
        skills_missing=tuple(raw["skills_missing"]),
    )


@cache
def load_catalog(path: Path = DATA_FILE) -> Catalog:
    data = json.loads(path.read_text(encoding="utf-8"))
    offers = sorted(
        (_offer(raw) for raw in data["offers"]), key=lambda o: (-o.score, o.id)
    )
    return Catalog(
        offers=tuple(offers),
        tracks={track["key"]: track["label"] for track in data["tracks"]},
        threshold=data["threshold"],
    )


class DecisionBook:
    """Decisions per account, in memory, with an undo stack. Thread-safe: requests run in parallel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: dict[int, dict[int, Decision]] = {}
        self._history: dict[int, list[tuple[int, Decision | None]]] = {}

    def decisions(self, account_id: int) -> dict[int, Decision]:
        with self._lock:
            return dict(self._current.get(account_id, {}))

    def record(self, account_id: int, offer_id: int, decision: Decision) -> None:
        with self._lock:
            current = self._current.setdefault(account_id, {})
            self._history.setdefault(account_id, []).append(
                (offer_id, current.get(offer_id))
            )
            current[offer_id] = decision

    def undo(self, account_id: int) -> int | None:
        """Cancel the last decision (the previous one comes back); return its offer, or None."""
        with self._lock:
            history = self._history.get(account_id)
            if not history:
                return None
            offer_id, previous = history.pop()
            current = self._current.setdefault(account_id, {})
            if previous is None:
                current.pop(offer_id, None)
            else:
                current[offer_id] = previous
            return offer_id

    def can_undo(self, account_id: int) -> bool:
        with self._lock:
            return bool(self._history.get(account_id))

    def reset(self, account_id: int) -> None:
        with self._lock:
            self._current.pop(account_id, None)
            self._history.pop(account_id, None)
