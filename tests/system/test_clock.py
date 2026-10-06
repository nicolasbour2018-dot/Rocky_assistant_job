"""The time of Rocky: one clock, one day — the user's, in Paris (step H2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from fastapi import FastAPI, Request

from rocky.system.clock import paris_day, paris_midnight, paris_time, today_of

# 00:30 in Paris (summer time, UTC+2) is 22:30 UTC the day before.
HALF_PAST_MIDNIGHT_SUMMER = datetime(2026, 10, 5, 22, 30, tzinfo=UTC)
# 00:30 in Paris (winter time, UTC+1) is 23:30 UTC the day before.
HALF_PAST_MIDNIGHT_WINTER = datetime(2026, 12, 4, 23, 30, tzinfo=UTC)


def test_the_day_is_the_users_in_paris() -> None:
    assert paris_day(HALF_PAST_MIDNIGHT_SUMMER) == date(2026, 10, 6)
    assert paris_day(HALF_PAST_MIDNIGHT_WINTER) == date(2026, 12, 5)


def test_a_time_is_shown_in_paris() -> None:
    assert paris_time(HALF_PAST_MIDNIGHT_SUMMER) == "06/10 à 00:30"
    assert paris_time(HALF_PAST_MIDNIGHT_WINTER) == "05/12 à 00:30"


def test_today_is_the_paris_day_of_the_application_clock() -> None:
    app = FastAPI()
    app.state.auth = SimpleNamespace(clock=lambda: HALF_PAST_MIDNIGHT_SUMMER)

    assert today_of(Request({"type": "http", "app": app})) == date(2026, 10, 6)


def test_a_paris_day_starts_at_midnight_in_paris_summer_and_winter() -> None:
    assert paris_midnight(date(2026, 10, 7)) == datetime(2026, 10, 6, 22, 0, tzinfo=UTC)
    assert paris_midnight(date(2026, 12, 7)) == datetime(2026, 12, 6, 23, 0, tzinfo=UTC)
    # The day of the change of hour starts before it.
    assert paris_midnight(date(2026, 10, 25)) == datetime(
        2026, 10, 24, 22, 0, tzinfo=UTC
    )
