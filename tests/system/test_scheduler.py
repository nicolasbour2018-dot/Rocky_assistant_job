"""The single planner (D12): daily tasks at a Paris hour, never caught up at start; periodic tasks woken up; one-off
tasks; a failing task is logged and the others go on."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, time, timedelta

import pytest

from rocky.system.scheduler import DailyTask, PeriodicTask, Scheduler

NOON = time(12, 0)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def paris(day: int, hour: int, minute: int = 0, month: int = 9) -> datetime:
    """A moment of 2026 given in Paris summer time (UTC+2) until the end of October."""
    return datetime(2026, month, day, hour - 2, minute, tzinfo=UTC)


def test_the_daily_task_runs_when_noon_comes_in_paris() -> None:
    clock = Clock(paris(29, 11, 59))
    ran: list[str] = []
    scheduler = Scheduler(
        daily=[DailyTask("veille", NOON, lambda: ran.append("veille"))], clock=clock
    )

    assert scheduler.tick() == []
    clock.now = paris(29, 12, 0)
    assert scheduler.tick() == ["veille"]
    clock.now = paris(29, 12, 30)
    assert scheduler.tick() == []
    assert scheduler.next_run("veille") == paris(30, 12, 0)
    assert ran == ["veille"]


def test_a_daily_hour_already_past_at_start_is_not_caught_up() -> None:
    clock = Clock(paris(29, 14, 0))
    scheduler = Scheduler(daily=[DailyTask("veille", NOON, lambda: None)], clock=clock)

    assert scheduler.tick() == []
    assert scheduler.next_run("veille") == paris(30, 12, 0)


def test_noon_follows_the_change_to_winter_time() -> None:
    # Summer time ends on 25 October 2026: noon in Paris is 10:00 UTC before, 11:00 UTC after.
    scheduler = Scheduler(clock=Clock(paris(24, 13, 0, month=10)))

    after = scheduler.next_daily(NOON, paris(24, 13, 0, month=10))

    assert after == datetime(2026, 10, 25, 11, 0, tzinfo=UTC)


def test_a_periodic_task_runs_first_then_every_period_or_when_woken_up() -> None:
    clock = Clock(paris(29, 9, 0))
    scheduler = Scheduler(
        periodic=[PeriodicTask("recalcul", timedelta(minutes=1), lambda: None)],
        clock=clock,
    )

    assert scheduler.tick() == ["recalcul"]
    clock.now += timedelta(seconds=30)
    assert scheduler.tick() == []
    scheduler.wake("recalcul")
    assert scheduler.tick() == ["recalcul"]
    clock.now += timedelta(seconds=59)
    assert scheduler.tick() == []
    clock.now += timedelta(seconds=1)
    assert scheduler.tick() == ["recalcul"]


def test_one_off_tasks_run_once_before_the_others() -> None:
    clock = Clock(paris(29, 9, 0))
    scheduler = Scheduler(
        periodic=[PeriodicTask("recalcul", timedelta(minutes=1), lambda: None)],
        clock=clock,
    )
    scheduler.submit("veille-compte-1", lambda: None)

    assert scheduler.pending() == ["veille-compte-1"]
    assert scheduler.tick() == ["veille-compte-1", "recalcul"]
    assert scheduler.pending() == []


def test_a_failing_task_is_logged_with_its_trace_and_the_others_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ran: list[str] = []

    def broken() -> None:
        raise RuntimeError("boom")

    scheduler = Scheduler(clock=Clock(paris(29, 9, 0)))
    scheduler.submit("cassée", broken)
    scheduler.submit("suivante", lambda: ran.append("suivante"))

    with caplog.at_level(logging.ERROR):
        assert scheduler.tick() == ["cassée", "suivante"]

    assert ran == ["suivante"]
    (record,) = caplog.records
    assert record.getMessage() == "scheduled task cassée failed"
    assert record.exc_info is not None


def test_the_thread_runs_submitted_tasks_and_stops() -> None:
    done = threading.Event()
    scheduler = Scheduler()
    scheduler.start()
    try:
        scheduler.submit("essai", done.set)
        assert done.wait(5)
    finally:
        scheduler.stop()
