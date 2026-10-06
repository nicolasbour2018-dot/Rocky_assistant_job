"""Weeks and months of Paris for the cockpit (decision G3, Q13, Q20, Q22): the buckets of a chart, and the delta of a
flow against the previous week at the same point.

Pure: the days are Paris days (``clock.paris_day``), given by the caller.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

# Q22: the depth of a chart.
CHART_PERIODS = 12
MONTH_LABELS = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)


class Period(StrEnum):
    """As written in the cockpit's URLs."""

    WEEK = "semaine"
    MONTH = "mois"


def week_start(day: date) -> date:
    """The Monday of ``day``'s week (a Paris week runs from Monday to Sunday, Q9)."""
    return day - timedelta(days=day.weekday())


def period_start(day: date, period: Period) -> date:
    return week_start(day) if period is Period.WEEK else day.replace(day=1)


def _previous(start: date, period: Period) -> date:
    if period is Period.WEEK:
        return start - timedelta(days=7)
    return (start - timedelta(days=1)).replace(day=1)


def buckets(
    today: date, period: Period, count: int = CHART_PERIODS
) -> tuple[date, ...]:
    """The first days of the last ``count`` periods, the oldest first; the last one is the current period."""
    starts = [period_start(today, period)]
    while len(starts) < count:
        starts.append(_previous(starts[-1], period))
    return tuple(reversed(starts))


def bucket_label(start: date, period: Period) -> str:
    """« 06/10 » for the week of Monday 6 October, « oct. » for a month (« janv. 2027 » when the year changes)."""
    if period is Period.WEEK:
        return f"{start:%d/%m}"
    label = MONTH_LABELS[start.month - 1]
    return f"{label} {start.year}" if start.month == 1 else label


def counts_by_bucket(
    days: Iterable[date], starts: tuple[date, ...], period: Period
) -> tuple[int, ...]:
    """How many of ``days`` fall in each period starting at ``starts``; days outside are ignored."""
    found = Counter(period_start(day, period) for day in days)
    return tuple(found[start] for start in starts)


@dataclass(frozen=True)
class Delta:
    """A flow this week (Monday to today) and last week at the same point (Monday to the same weekday, Q20)."""

    now: int
    before: int

    @property
    def change(self) -> int:
        return self.now - self.before


def week_delta(days: Iterable[date], today: date) -> Delta:
    start = week_start(today)
    last_start = start - timedelta(days=7)
    last_same = today - timedelta(days=7)
    now = before = 0
    for day in days:
        if start <= day <= today:
            now += 1
        elif last_start <= day <= last_same:
            before += 1
    return Delta(now, before)
