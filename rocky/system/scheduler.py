"""The single planner of Rocky (D12): daily tasks at a local hour, periodic tasks that can be woken up, and one-off
tasks asked by the screen.

It runs in one thread started by the application. A task failure is logged with its trace and the thread goes on; the
durable state of a task lives in the database (a watch records its runs), so nothing is lost when it stops. A daily
task missed while the application was off is not caught up here: the screen proposes it (D12).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from rocky.system.clock import PARIS, utc_now

logger = logging.getLogger(__name__)

# Longest sleep between two looks at the tasks.
IDLE = timedelta(seconds=30)

type Task = Callable[[], object]
type Clock = Callable[[], datetime]


@dataclass(frozen=True)
class DailyTask:
    name: str
    at: time
    run: Task


@dataclass(frozen=True)
class PeriodicTask:
    """Run at the first look, then every ``every``, and at once when woken up."""

    name: str
    every: timedelta
    run: Task


class Scheduler:
    def __init__(
        self,
        *,
        daily: Sequence[DailyTask] = (),
        periodic: Sequence[PeriodicTask] = (),
        clock: Clock = utc_now,
        zone: ZoneInfo = PARIS,
    ) -> None:
        self._daily = tuple(daily)
        self._periodic = {task.name: task for task in periodic}
        self._clock = clock
        self._zone = zone
        self._lock = threading.Lock()
        self._queue: deque[tuple[str, Task]] = deque()
        start = clock()
        self._next: dict[str, datetime] = {
            **{task.name: self.next_daily(task.at, start) for task in self._daily},
            **dict.fromkeys(self._periodic, start),
        }
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def next_daily(self, at: time, after: datetime) -> datetime:
        """The first ``at`` (local hour) strictly after ``after``: a task is never run for an hour already past."""
        local = after.astimezone(self._zone)
        day = local.date()
        candidate = datetime.combine(day, at, tzinfo=self._zone)
        if candidate <= local:
            candidate = datetime.combine(day + timedelta(days=1), at, tzinfo=self._zone)
        return candidate.astimezone(UTC)

    def next_run(self, name: str) -> datetime:
        with self._lock:
            return self._next[name]

    def submit(self, name: str, task: Task) -> None:
        """Run ``task`` once, as soon as the thread is free."""
        with self._lock:
            self._queue.append((name, task))
        self._wake.set()

    def pending(self) -> list[str]:
        with self._lock:
            return [name for name, _ in self._queue]

    def wake(self, name: str) -> None:
        """Run the periodic task ``name`` as soon as the thread is free."""
        with self._lock:
            self._next[name] = min(self._next[name], self._clock())
        self._wake.set()

    def due(self, now: datetime) -> list[tuple[str, Task]]:
        """The tasks to run at ``now``, one-off tasks first; their next runs are set."""
        with self._lock:
            tasks = list(self._queue)
            self._queue.clear()
            for daily in self._daily:
                if now >= self._next[daily.name]:
                    tasks.append((daily.name, daily.run))
                    self._next[daily.name] = self.next_daily(daily.at, now)
            for name, periodic in self._periodic.items():
                if now >= self._next[name]:
                    tasks.append((name, periodic.run))
                    self._next[name] = now + periodic.every
        return tasks

    def tick(self) -> list[str]:
        """Run what is due, one task after the other; the names of the tasks run."""
        ran: list[str] = []
        for name, task in self.due(self._clock()):
            try:
                task()
            except Exception:
                logger.exception("scheduled task %s failed", name)
            ran.append(name)
        return ran

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="rocky-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the thread to stop and wait for it a little: a watch in progress is closed as interrupted at the
        next start if the process ends first."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Cleared before running: a wake-up asked during a task is not lost.
            self._wake.clear()
            self.tick()
            self._wake.wait(self._delay().total_seconds())

    def _delay(self) -> timedelta:
        with self._lock:
            if self._queue:
                return timedelta(0)
            soonest = min(self._next.values(), default=self._clock() + IDLE)
        return max(timedelta(0), min(IDLE, soonest - self._clock()))
