"""Weeks and months of Paris for the cockpit's charts and deltas (decision G3, Q20, Q22)."""

from __future__ import annotations

from datetime import date

from rocky.system.periods import (
    Delta,
    Period,
    bucket_label,
    buckets,
    counts_by_bucket,
    week_delta,
    week_start,
)

# Wednesday 7 October 2026.
WEDNESDAY = date(2026, 10, 7)


def test_a_week_runs_from_monday() -> None:
    assert week_start(WEDNESDAY) == date(2026, 10, 5)
    assert week_start(date(2026, 10, 11)) == date(2026, 10, 5)  # Sunday
    assert week_start(date(2026, 10, 5)) == date(2026, 10, 5)


def test_twelve_weeks_the_current_one_last() -> None:
    starts = buckets(WEDNESDAY, Period.WEEK)

    assert len(starts) == 12
    assert starts[-1] == date(2026, 10, 5)
    assert starts[0] == date(2026, 7, 20)
    assert [bucket_label(s, Period.WEEK) for s in starts[-2:]] == ["28/09", "05/10"]


def test_twelve_months_across_a_year() -> None:
    starts = buckets(date(2027, 2, 14), Period.MONTH)

    assert starts[0] == date(2026, 3, 1)
    assert starts[-1] == date(2027, 2, 1)
    labels = [bucket_label(s, Period.MONTH) for s in starts]
    assert labels[-3:] == ["déc.", "janv. 2027", "févr."]


def test_days_are_counted_in_their_period() -> None:
    starts = buckets(WEDNESDAY, Period.WEEK, 2)
    days = [date(2026, 9, 28), date(2026, 10, 4), date(2026, 10, 5), date(2026, 1, 1)]

    assert counts_by_bucket(days, starts, Period.WEEK) == (2, 1)


def test_the_delta_compares_the_same_point_of_last_week() -> None:
    days = [
        date(2026, 10, 5),  # this Monday
        date(2026, 10, 7),  # today
        date(2026, 9, 28),  # last Monday
        date(2026, 9, 30),  # last Wednesday: same point
        date(2026, 10, 1),  # last Thursday: after the same point
        date(2026, 10, 8),  # tomorrow: not yet
    ]

    delta = week_delta(days, WEDNESDAY)

    assert delta == Delta(now=2, before=2)
    assert delta.change == 0
