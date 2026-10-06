"""What the offers screen shows (step C7): the triage queue, the filtered list and the card of one offer.

Pure rules on what ``SqlStore`` read: no SQL, no request. Decision ``docs/decisions/C7-ecran-offres.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from rocky.offres.analysis.model import PostingAnalysis, SkillMatch
from rocky.offres.analysis.usecases import Summary, SummaryResult
from rocky.offres.decisions import DecisionRow, DecisionValue
from rocky.offres.imports.rules import readable_in_browser
from rocky.offres.model import StoredOffer
from rocky.offres.scoring.model import (
    THRESHOLD,
    ConfidenceLevel,
    Score,
    ScoringProfile,
    TrackScore,
)

# Decision filter of the list, as written in the URL; None: every decision.
TO_EXAMINE = "a_examiner"
EVERY_DECISION = "toutes"
DECISION_FILTERS: dict[str, DecisionValue | None] = {
    TO_EXAMINE: None,
    "interesse": DecisionValue.INTERESTED,
    "ecarte": DecisionValue.REJECTED,
    "plus_tard": DecisionValue.LATER,
    EVERY_DECISION: None,
}
DECISION_FILTER_LABELS = {
    TO_EXAMINE: "À examiner",
    "interesse": "Intéressé",
    "ecarte": "Écarté",
    "plus_tard": "Plus tard",
    EVERY_DECISION: "Toutes",
}
# Rows of the list per page (« Afficher plus »).
PAGE_SIZE = 100
HIGH_SCORE = 75


def band(display: int) -> str:
    """Colour of a score: high, mid (at or above the threshold) or low."""
    if display >= HIGH_SCORE:
        return "high"
    return "mid" if display >= THRESHOLD else "low"


@dataclass(frozen=True)
class TrackMark:
    """The current score of an offer for one track, as the list needs it."""

    track_id: int | None
    position: int
    value: float
    display: int
    confidence: ConfidenceLevel


@dataclass(frozen=True)
class ListedOffer:
    id: int
    title: str
    company: str | None
    location: str | None
    source: str
    published_on: date | None
    description_complete: bool
    match_key: str | None
    # Tracks linked to the offer (the ones whose queries found it, or the best one for an import).
    track_ids: frozenset[int]
    # One per scored track, in the order of the profile.
    marks: tuple[TrackMark, ...]
    # The deadline the analysis read when the offer was scored (decision G2, Q7).
    deadline: date | None = None

    @property
    def best(self) -> TrackMark:
        # The first of the best, like ``Score.best``.
        return max(self.marks, key=lambda mark: mark.value)

    @property
    def below_threshold(self) -> bool:
        return self.best.display < THRESHOLD

    def mark_for(self, track_id: int | None) -> TrackMark:
        """The score shown: the one of ``track_id`` when the list is filtered on it (C7, Q7), else the best."""
        if track_id is not None:
            for mark in self.marks:
                if mark.track_id == track_id:
                    return mark
        return self.best


def past_deadlines(offers: Iterable[ListedOffer], today: date) -> frozenset[int]:
    """The offers whose deadline is past: signalled, never decided (decision G2, Q7, Q14)."""
    return frozenset(
        offer.id
        for offer in offers
        if offer.deadline is not None and offer.deadline < today
    )


@dataclass(frozen=True)
class ListFilters:
    track_id: int | None = None
    decision: str = TO_EXAMINE
    # Q13: independent filters. « Sous le seuil » adds the offers under the threshold; « Incomplètes » keeps the
    # incomplete offers only, above and under the threshold.
    below_threshold: bool = False
    incomplete: bool = False


def make_filters(
    track: str | None,
    decision: str | None,
    below_threshold: str | None,
    incomplete: str | None,
) -> ListFilters:
    """The filters of the list from the words of the URL; an unknown value falls back to the default."""
    return ListFilters(
        track_id=int(track) if track and track.isascii() and track.isdigit() else None,
        decision=decision if decision in DECISION_FILTERS else TO_EXAMINE,
        below_threshold=bool(below_threshold),
        incomplete=bool(incomplete),
    )


def _decided(
    offer: ListedOffer, decisions: dict[int, DecisionRow], wanted: str
) -> bool:
    decision = decisions.get(offer.id)
    if wanted == TO_EXAMINE:
        return decision is None
    value = DECISION_FILTERS[wanted]
    if value is None:
        return True
    return decision is not None and (
        decision.decision is not None and decision.decision.value is value
    )


def listed(
    offers: Iterable[ListedOffer],
    decisions: dict[int, DecisionRow],
    filters: ListFilters,
) -> list[ListedOffer]:
    """The offers of the list, by decreasing score shown (the track's score when filtered on a track)."""
    kept = [
        offer
        for offer in offers
        if (filters.track_id is None or filters.track_id in offer.track_ids)
        and (
            not offer.description_complete
            if filters.incomplete
            else filters.below_threshold or not offer.below_threshold
        )
        and _decided(offer, decisions, filters.decision)
    ]
    return sorted(kept, key=lambda o: (-o.mark_for(filters.track_id).value, o.id))


def queue(
    offers: Iterable[ListedOffer], decisions: dict[int, DecisionRow]
) -> list[ListedOffer]:
    """The triage queue (Q3): offers without a decision, above the threshold, best first."""
    return sorted(
        (o for o in offers if o.id not in decisions and not o.below_threshold),
        key=lambda o: (-o.best.value, o.id),
    )


@dataclass(frozen=True)
class Counts:
    to_review: int
    below: int


def counts(offers: Sequence[ListedOffer], decisions: dict[int, DecisionRow]) -> Counts:
    return Counts(
        to_review=len(queue(offers, decisions)),
        below=sum(1 for o in offers if o.below_threshold and o.id not in decisions),
    )


def next_after(
    offers: Sequence[ListedOffer],
    decisions: dict[int, DecisionRow],
    offer_id: int | None,
) -> ListedOffer | None:
    """The offer to show after ``offer_id`` in triage: the next one of the queue in score order, else the first."""
    waiting = queue(offers, decisions)
    if not waiting:
        return None
    if offer_id is not None:
        order = sorted(
            (o for o in offers if not o.below_threshold),
            key=lambda o: (-o.best.value, o.id),
        )
        ids = [o.id for o in order]
        if offer_id in ids:
            later = {o.id for o in order[ids.index(offer_id) + 1 :]}
            upcoming = next((o for o in waiting if o.id in later), None)
            if upcoming is not None:
                return upcoming
    return waiting[0]


def neighbours(
    offers: Sequence[ListedOffer],
    decisions: dict[int, DecisionRow],
    offer_id: int,
) -> tuple[ListedOffer | None, ListedOffer | None]:
    """Previous and next offers of the queue (keys k and j); an offer out of the queue only has a next one."""
    waiting = queue(offers, decisions)
    ids = [o.id for o in waiting]
    if offer_id not in ids:
        return None, next_after(offers, decisions, offer_id)
    index = ids.index(offer_id)
    previous = waiting[index - 1] if index > 0 else None
    following = waiting[index + 1] if index + 1 < len(waiting) else None
    return previous, following


@dataclass(frozen=True)
class SkillLine:
    """A skill of the account named by the posting, and whether the profile proves it (an experience or a project)."""

    match: SkillMatch
    proven: bool


@dataclass(frozen=True)
class OfferCard:
    """Everything the triage card and the side sheet show of one offer (C7, Q12)."""

    stored: StoredOffer
    score: Score
    # The score shown: the best one, or the track the list is filtered on (Q7, Q11).
    shown: TrackScore
    analysis: PostingAnalysis
    skills: tuple[SkillLine, ...]
    # Track names of the tracks linked to the offer.
    tracks: tuple[str, ...]
    # Other offers of the same posting on other sites: id and source (C6 Q4, C7 Q4).
    same_posting: tuple[tuple[int, str], ...]
    decision: DecisionRow | None
    summary: Summary | None
    deadline_passed: bool = False

    @property
    def id(self) -> int:
        return self.stored.id

    @property
    def gaps(self) -> tuple[str, ...]:
        return self.shown.gaps

    @property
    def summary_result(self) -> SummaryResult | None:
        return None if self.summary is None else SummaryResult(summary=self.summary)

    @property
    def readable_in_browser(self) -> bool:
        """« Ouvrir dans le navigateur » is offered (decision E5, Q8)."""
        return readable_in_browser(self.stored.offer)


def shown_track(score: Score, track_id: int | None) -> TrackScore:
    """The score of ``track_id`` when the offer has one, else the best score."""
    if track_id is not None:
        for track in score.tracks:
            if track.track_id == track_id:
                return track
    return score.best


def offer_card(
    stored: StoredOffer,
    *,
    score: Score,
    analysis: PostingAnalysis,
    profile: ScoringProfile,
    track_names: dict[int, str],
    linked: Iterable[int],
    same_posting: Sequence[tuple[int, str]],
    decision: DecisionRow | None,
    summary: Summary | None,
    today: date,
    track_id: int | None = None,
) -> OfferCard:
    proven = {skill.label for skill in profile.skills if skill.proven}
    return OfferCard(
        stored=stored,
        score=score,
        shown=shown_track(score, track_id),
        analysis=analysis,
        skills=tuple(
            SkillLine(match, match.skill in proven) for match in analysis.skills
        ),
        tracks=tuple(
            track_names[track] for track in sorted(linked) if track in track_names
        ),
        same_posting=tuple(same_posting),
        decision=decision,
        summary=summary,
        deadline_passed=analysis.deadline is not None and analysis.deadline < today,
    )
