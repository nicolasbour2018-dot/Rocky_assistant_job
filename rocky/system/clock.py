"""The time of Rocky: one clock (UTC instants), one day (the user's, in Paris, D12).

Every "today" of Rocky is the Paris day of the injected clock (``app.state.auth.clock``): never ``.date()`` on a UTC
instant, which lags one day between midnight and 2 a.m. in Paris.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import Request

PARIS = ZoneInfo("Europe/Paris")


def utc_now() -> datetime:
    return datetime.now(UTC)


def paris_day(moment: datetime) -> date:
    """The day of ``moment`` in Paris (the user's day, D12)."""
    return moment.astimezone(PARIS).date()


def paris_time(moment: datetime) -> str:
    """``moment`` as the screens show it, in Paris: « 06/10 à 00:30 »."""
    return moment.astimezone(PARIS).strftime("%d/%m à %H:%M")


def today_of(request: Request) -> date:
    """The user's day on the application's clock (replaced by the tests)."""
    clock: Callable[[], datetime] = request.app.state.auth.clock
    return paris_day(clock())
