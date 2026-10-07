"""The time of Rocky: one clock (UTC instants), one day (the user's, in Paris, D12).

Every "today" of Rocky is the Paris day of the injected clock (``app.state.auth.clock``): never ``.date()`` on a UTC
instant, which lags one day between midnight and 2 a.m. in Paris.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import Request
from jinja2 import pass_context
from jinja2.runtime import Context

PARIS = ZoneInfo("Europe/Paris")


def utc_now() -> datetime:
    return datetime.now(UTC)


def paris_day(moment: datetime) -> date:
    """The day of ``moment`` in Paris (the user's day, D12)."""
    return moment.astimezone(PARIS).date()


def paris_midnight(day: date) -> datetime:
    """The instant ``day`` starts in Paris (the start of a "per day" limit, step G4), daylight saving included."""
    return datetime.combine(day, time(0, 0), tzinfo=PARIS)


def paris_hour(moment: datetime) -> str:
    """« 12:04 »: the hour of an instant in Paris (the cockpit's feed, step G3)."""
    return moment.astimezone(PARIS).strftime("%H:%M")


def paris_time(moment: datetime, today: date | None = None) -> str:
    """``moment`` as the screens show it, in Paris: « 06/10 à 00:30 », with its year when it is not the year of
    ``today`` (decision G6, lexicon): « 30/12/2025 à 18:00 »."""
    local = moment.astimezone(PARIS)
    if today is not None and local.year != today.year:
        return local.strftime("%d/%m/%Y à %H:%M")
    return local.strftime("%d/%m à %H:%M")


@pass_context
def paris_time_filter(context: Context, moment: datetime) -> str:
    """The filter ``paris_time`` of the templates: the year is said when it is not the user's (the request's clock)."""
    request = context.get("request")
    return paris_time(
        moment, today_of(request) if isinstance(request, Request) else None
    )


def today_of(request: Request) -> date:
    """The user's day on the application's clock (replaced by the tests)."""
    clock: Callable[[], datetime] = request.app.state.auth.clock
    return paris_day(clock())
