"""The progress of the cockpit (decision G3, Q9–Q12, Q23): the goal of the week, the streaks and the milestones,
computed exactly from the changes in force."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from rocky.candidatures.model import Change, ChangeKind, Stage
from rocky.candidatures.progress import (
    Moments,
    Reached,
    Start,
    Week,
    active_day_streak,
    celebrations,
    goal_week_streak,
    last_reached,
    milestones,
    moments_of,
    next_milestone,
    started,
    week_days,
    week_of,
)
from rocky.offres.decisions import Author

# Wednesday 7 October 2026; noon in Paris is 10:00 UTC.
TODAY = date(2026, 10, 7)


def at(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def change(
    change_id: int,
    kind: ChangeKind,
    moment: datetime,
    stage: Stage | None = None,
    cancels: int | None = None,
) -> Change:
    return Change(change_id, 1, kind, Author.USER, moment, stage=stage, cancels=cancels)


def test_a_sending_is_the_first_sent_stage_in_force() -> None:
    created = at(date(2026, 10, 1))
    first_sent = at(date(2026, 10, 2))
    answered = at(date(2026, 10, 6))
    changes = [
        change(1, ChangeKind.CREATED, created, Stage.PREPARING),
        change(2, ChangeKind.STAGE, first_sent, Stage.SENT),
        change(3, ChangeKind.CANCELLATION, first_sent, cancels=2),
        change(4, ChangeKind.STAGE, at(date(2026, 10, 5)), Stage.SENT),
        change(5, ChangeKind.STAGE, answered, Stage.INTERVIEW),
    ]

    found = moments_of([(1, changes)])

    assert found.opened == (created,)
    assert found.sent == (at(date(2026, 10, 5)),)  # the cancelled sending never counts
    assert found.answered == (answered,)
    assert found.interviews == (answered,)
    assert found.job_offers == ()


def test_a_cancelled_creation_is_no_application() -> None:
    changes = [
        change(1, ChangeKind.CREATED, at(TODAY), Stage.PREPARING),
        change(2, ChangeKind.CANCELLATION, at(TODAY), cancels=1),
    ]

    assert moments_of([(1, changes)]) == Moments()


def test_the_week_counts_the_sendings_of_the_paris_week() -> None:
    sent = [
        datetime(2026, 10, 4, 22, 30, tzinfo=UTC),  # Monday 00:30 in Paris
        at(date(2026, 10, 6)),
        at(date(2026, 10, 7), 8),
        at(date(2026, 9, 30)),  # last week
    ]

    week = week_of(sent, 2, TODAY)

    assert week == Week(sent=3, goal=2, reached_at=at(date(2026, 10, 6)))
    assert week.remaining == 0
    assert week_of(sent, 5, TODAY).remaining == 2
    assert week_of(sent, 5, TODAY).reached_at is None


def test_the_weekend_never_breaks_the_daily_streak() -> None:
    active = {
        date(2026, 10, 1),  # Thursday
        date(2026, 10, 2),  # Friday
        date(2026, 10, 4),  # Sunday: counts
        date(2026, 10, 5),  # Monday
        date(2026, 10, 6),  # Tuesday
    }

    # Today (Wednesday) is not active yet: it does not break the streak.
    assert active_day_streak(active, TODAY) == 5
    assert active_day_streak(active | {TODAY}, TODAY) == 6


def test_a_weekday_without_gesture_breaks_the_daily_streak() -> None:
    active = {date(2026, 9, 30), date(2026, 10, 2), date(2026, 10, 5)}

    # Thursday 1 October had nothing: the streak starts on Friday.
    assert active_day_streak(active, date(2026, 10, 5)) == 2
    assert active_day_streak(set(), TODAY) == 0


def test_weeks_in_a_row_at_the_goal() -> None:
    sent = [
        at(date(2026, 9, 21)),
        at(date(2026, 9, 22)),
        at(date(2026, 9, 29)),
        at(date(2026, 9, 30)),
        at(date(2026, 10, 6)),
    ]

    # This week (1 of 2) is in progress: it does not break the streak.
    assert goal_week_streak(sent, 2, TODAY) == 2
    assert goal_week_streak([*sent, at(TODAY)], 2, TODAY) == 3
    assert goal_week_streak(sent, 3, TODAY) == 0


def test_the_days_of_the_week() -> None:
    days = week_days({date(2026, 10, 5), date(2026, 10, 4)}, TODAY)

    assert [(d.letter, d.active, d.today) for d in days] == [
        ("L", True, False),
        ("M", False, False),
        ("M", False, True),
        ("J", False, False),
        ("V", False, False),
    ]


def test_milestones_are_dated_and_the_next_one_says_what_is_left() -> None:
    sent = tuple(at(date(2026, 9, 1) + timedelta(days=i)) for i in range(6))
    decided = [at(date(2026, 8, 1) + timedelta(days=i)) for i in range(12)]
    start = Start(
        profile=Reached(True, at(date(2026, 7, 1))),
        track=Reached(True),  # older than its event: no date
        cv=Reached(True, at(date(2026, 7, 2))),
        gmail=Reached(False),
        watch=Reached(True, at(date(2026, 7, 3))),
    )

    found = milestones(start, Moments(opened=sent[:1], sent=sent), decided)
    by_key = {m.key: m for m in found}

    assert by_key["piste"].done and by_key["piste"].at is None
    assert by_key["tri-10"].at == decided[9]
    assert by_key["envoi-5"].at == sent[4]
    assert by_key["envoi-10"].remaining == "encore 4 envois"
    assert by_key["tri-50"].remaining == "encore 38 offres"
    nxt = next_milestone(found)
    assert nxt is not None and nxt.key == "gmail"
    last = last_reached(found)
    assert last is not None and last.key == "envoi-5"
    assert started(start)
    assert not started(Start())


def test_a_celebration_is_shown_once_after_the_previous_visit() -> None:
    sent = (at(date(2026, 10, 5)), at(TODAY, 9))
    found = milestones(Start(), Moments(opened=sent, sent=sent), [])
    week = week_of(sent, 2, TODAY)

    after = celebrations(found, week, at(TODAY, 8))
    assert after == ("Objectif de la semaine atteint : 2 sur 2.",)
    before = celebrations(found, week, at(date(2026, 10, 4)))
    assert "Jalon franchi : Première candidature envoyée." in before
    assert "Jalon franchi : Premier dossier ouvert." in before
    # Nothing on the very first visit, nothing once seen.
    assert celebrations(found, week, None) == ()
    assert celebrations(found, week, at(TODAY, 11)) == ()
