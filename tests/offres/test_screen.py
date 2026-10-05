"""What the offers screen shows (C7): queue, list filters, neighbours, and the card's proven skills."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from rocky.offres.analysis.model import Importance, PostingAnalysis, SkillMatch
from rocky.offres.decisions import Decision, DecisionKind, DecisionRow, DecisionValue
from rocky.offres.model import Origin, StoredOffer
from rocky.offres.scoring.model import (
    Confidence,
    ConfidenceLevel,
    ProfileSkill,
    Score,
    ScoringProfile,
    TrackScore,
)
from rocky.offres.screen import (
    ListedOffer,
    ListFilters,
    TrackMark,
    band,
    counts,
    listed,
    make_filters,
    neighbours,
    next_after,
    offer_card,
    queue,
)
from tests.offres.fakes import posting

AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def offer(
    offer_id: int,
    *scores: int,
    tracks: tuple[int, ...] = (1,),
    complete: bool = True,
) -> ListedOffer:
    return ListedOffer(
        id=offer_id,
        title=f"Offre {offer_id}",
        company=None,
        location=None,
        source="apec",
        published_on=None,
        description_complete=complete,
        match_key=None,
        track_ids=frozenset(tracks),
        marks=tuple(
            TrackMark(track, position, float(value), value, ConfidenceLevel.HIGH)
            for position, (track, value) in enumerate(zip((1, 2), scores, strict=False))
        ),
    )


def later(offer_id: int, row_id: int = 1) -> DecisionRow:
    return DecisionRow(
        row_id,
        offer_id,
        DecisionKind.DECISION,
        AT,
        Decision(DecisionValue.LATER, ("reread",)),
    )


OFFERS = [
    offer(1, 60, 80, tracks=(2,)),
    offer(2, 90, 10),
    offer(3, 55, 20, complete=False),
    offer(4, 30, 20),
    offer(5, 20, 10, complete=False),
]


def ids(offers: list[ListedOffer]) -> list[int]:
    return [o.id for o in offers]


def test_the_queue_is_undecided_offers_above_the_threshold_best_first() -> None:
    assert ids(queue(OFFERS, {})) == [2, 1, 3]
    assert ids(queue(OFFERS, {2: later(2)})) == [1, 3]
    assert counts(OFFERS, {2: later(2)}).to_review == 2
    assert counts(OFFERS, {4: later(4)}).below == 1


def test_later_offers_leave_the_queue_for_the_list() -> None:
    decisions = {1: later(1)}

    assert 1 not in ids(queue(OFFERS, decisions))
    assert ids(listed(OFFERS, decisions, ListFilters(decision="plus_tard"))) == [1]


def test_filters_are_independent() -> None:
    assert ids(listed(OFFERS, {}, ListFilters())) == [2, 1, 3]
    assert ids(listed(OFFERS, {}, ListFilters(below_threshold=True))) == [2, 1, 3, 4, 5]
    # Q13: incomplete offers above and under the threshold.
    assert ids(listed(OFFERS, {}, ListFilters(incomplete=True))) == [3, 5]


def test_a_track_filter_sorts_by_that_tracks_score() -> None:
    both = [offer(1, 60, 80, tracks=(1, 2)), offer(2, 90, 10, tracks=(1, 2))]

    assert ids(listed(both, {}, ListFilters())) == [2, 1]
    assert ids(listed(both, {}, ListFilters(track_id=2))) == [1, 2]
    assert both[0].mark_for(2).display == 80
    assert both[0].mark_for(None).display == 80  # the best
    assert both[1].mark_for(2).display == 10


def test_filters_from_the_url_fall_back_to_the_defaults() -> None:
    assert make_filters("abc", "maybe", None, "") == ListFilters()
    assert make_filters("7", "ecarte", "1", "1") == ListFilters(7, "ecarte", True, True)


def test_the_next_offer_follows_the_score_order() -> None:
    assert next_after(OFFERS, {}, None) == OFFERS[1]
    assert next_after(OFFERS, {}, 2) == OFFERS[0]
    # The last one wraps to the first waiting offer.
    assert next_after(OFFERS, {2: later(2)}, 3) == OFFERS[0]
    assert next_after(OFFERS, {n: later(n, n) for n in (1, 2, 3)}, 3) is None


def test_an_offer_out_of_the_queue_only_has_a_next_one() -> None:
    assert neighbours(OFFERS, {}, 1) == (OFFERS[1], OFFERS[2])
    assert neighbours(OFFERS, {}, 4) == (None, OFFERS[1])


def test_score_bands() -> None:
    assert [band(v) for v in (80, 75, 60, 50, 49)] == [
        "high",
        "high",
        "mid",
        "mid",
        "low",
    ]


def track(track_id: int, value: float) -> TrackScore:
    return TrackScore(
        track_id=track_id,
        track_name=f"Piste {track_id}",
        value=value,
        uncapped=value,
        components=(),
        confidence=Confidence(ConfidenceLevel.HIGH),
    )


def test_the_card_tells_proven_skills_and_shows_the_asked_track() -> None:
    stored = StoredOffer(1, 1, posting("x"), Origin.WATCH)
    score = Score("s", "a", (track(1, 40.0), track(2, 70.0)))
    analysis = PostingAnalysis(
        rules_version="a",
        description="",
        skills=(
            SkillMatch("Python", "python", Importance.ELIMINATORY, "Python exigé"),
            SkillMatch("SQL", "sql", Importance.DETECTED, "SQL"),
        ),
    )
    profile = ScoringProfile(
        skills=(ProfileSkill("Python", proven=True), ProfileSkill("SQL"))
    )

    card = offer_card(
        stored,
        score=score,
        analysis=analysis,
        profile=profile,
        track_names={1: "Data", 2: "IA", 3: "Archivée"},
        linked=[2, 1],
        same_posting=[(9, "wttj")],
        decision=None,
        summary=None,
    )
    asked = offer_card(
        stored,
        score=score,
        analysis=analysis,
        profile=profile,
        track_names={},
        linked=[],
        same_posting=[],
        decision=None,
        summary=None,
        track_id=1,
    )

    assert [(line.match.skill, line.proven) for line in card.skills] == [
        ("Python", True),
        ("SQL", False),
    ]
    assert card.tracks == ("Data", "IA")
    assert card.shown.track_id == 2  # the best
    assert asked.shown.track_id == 1
    assert replace(card, summary=None).summary_result is None
