"""Stored offers (step C6): an offer, the tracks that found it and its current scores, written as one unit.

Decision ``docs/decisions/C6-veille.md``. Codes are English; French labels are shown only on screen.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from rocky.offres.analysis.model import AccountSkill
from rocky.offres.analysis.usecases import Summary
from rocky.offres.decisions import Author, Decision, DecisionRow
from rocky.offres.scoring.model import Score, ScoringProfile, TrackScore
from rocky.offres.sources.model import CollectedOffer
from rocky.system.events import NewEvent


class Origin(StrEnum):
    """How an offer came in, and how a track was linked to it."""

    WATCH = "watch"
    IMPORT = "import"


ORIGIN_LABELS = {
    Origin.WATCH: "Trouvée par la veille",
    Origin.IMPORT: "Ajoutée par toi",
}


@dataclass(frozen=True)
class ScoringInputs:
    """What the analysis and the score read of an account, and the fingerprint of it all (``inputs_hash``).

    A stored score of another fingerprint is out of date (Q5).
    """

    skills: tuple[AccountSkill, ...]
    profile: ScoringProfile
    inputs_hash: str


@dataclass(frozen=True)
class StoredOffer:
    id: int
    account_id: int
    offer: CollectedOffer
    origin: Origin


@dataclass(frozen=True)
class OfferHeading:
    """What another module shows of an offer (the applications, D1)."""

    id: int
    title: str
    company: str | None
    location: str | None
    url: str = ""  # the posting where it was found
    application_url: str | None = (
        None  # where to apply, when the source gives it (D3, Q25)
    )

    @property
    def apply_at(self) -> str:
        """Where the user applies: the source's application link, else the posting."""
        return self.application_url or self.url


@dataclass(frozen=True)
class Recorded:
    """What ``record_offer`` did: a new offer, or a known one completed (Q7), and its score."""

    offer_id: int
    created: bool
    completed: bool
    score: Score
    # The stored description is complete (a known complete offer stays complete when a source gives an excerpt).
    description_complete: bool


@dataclass(frozen=True)
class StoredSummary:
    """The summary of an offer, with the fingerprint of the description it summarises (C7, Q6)."""

    description_hash: str
    summary: Summary


class OfferStore(Protocol):
    """The offers of the accounts, on a connection inside the caller's transaction; never commits."""

    def find(self, account_id: int, offer: CollectedOffer) -> StoredOffer | None:
        """The stored offer with the same source and identifier, else with the same address."""
        ...

    def insert(
        self,
        account_id: int,
        offer: CollectedOffer,
        *,
        origin: Origin,
        match_key: str | None,
        now: datetime,
    ) -> int: ...

    def update(
        self,
        offer_id: int,
        offer: CollectedOffer,
        *,
        match_key: str | None,
        now: datetime,
        seen: bool = True,
    ) -> None:
        """New facts of a known offer; also marks it seen, unless the user gave them (``seen=False``)."""
        ...

    def mark_seen(self, offer_id: int, now: datetime) -> None: ...

    def link_tracks(
        self,
        offer_id: int,
        track_ids: Iterable[int],
        *,
        found_by: Origin,
        run_id: int | None,
        now: datetime,
    ) -> None:
        """Adds the links that are missing; an existing link keeps how and when it was made."""
        ...

    def replace_scores(
        self, offer_id: int, score: Score, *, inputs_hash: str, now: datetime
    ) -> None:
        """The current scores of the offer become ``score``, one row per track (Q6)."""
        ...

    def current_score(self, offer_id: int) -> Score | None: ...

    def current_inputs_hash(self, offer_id: int) -> str | None: ...

    def stale_offers(self, account_id: int, inputs_hash: str) -> list[StoredOffer]:
        """Offers of the account without a score of this fingerprint."""
        ...

    def complete_keys(
        self, account_id: int, keys: Iterable[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        """Among ``(source, external_id)`` keys, those of stored offers whose description is complete."""
        ...

    def append_event(self, event: NewEvent) -> None: ...


class DecisionStore(Protocol):
    """The decisions of an account (C7), on a connection inside the caller's transaction; never commits."""

    def current_score(self, offer_id: int) -> Score | None: ...

    def current_inputs_hash(self, offer_id: int) -> str | None: ...

    def decision_rows(
        self, account_id: int, offer_id: int | None = None
    ) -> list[DecisionRow]: ...

    def insert_decision(
        self,
        account_id: int,
        offer_id: int,
        decision: Decision,
        *,
        author: Author,
        track: TrackScore,
        score: Score,
        inputs_hash: str | None,
        now: datetime,
    ) -> int: ...

    def insert_cancellation(
        self,
        account_id: int,
        cancelled: DecisionRow,
        *,
        author: Author,
        now: datetime,
    ) -> DecisionRow: ...

    def append_event(self, event: NewEvent) -> None: ...
