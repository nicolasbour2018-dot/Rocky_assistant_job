"""The watch: its triggers, statuses and counts, and the ports it runs on.

Decision ``docs/decisions/C6-veille.md``. Codes are English; French labels are shown only on screen.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Protocol

from rocky.offres.model import OfferStore
from rocky.offres.sources.usecases import Outcome
from rocky.profil.model import Profile

# Q1: one watch a day, at noon, Paris time.
WATCH_HOUR = time(12, 0)
# Q5: the rescoring is woken up by a change of the profile; this look also catches a new version of the rules.
RESCORE_EVERY = timedelta(minutes=1)


class Trigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    CATCH_UP = "catch_up"


TRIGGER_LABELS = {
    Trigger.SCHEDULED: "Veille planifiée",
    Trigger.MANUAL: "Lancée à la main",
    Trigger.CATCH_UP: "Rattrapage",
}


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


RUN_STATUS_LABELS = {
    RunStatus.RUNNING: "En cours",
    RunStatus.COMPLETED: "Terminée",
    RunStatus.PARTIAL: "Partielle",
    RunStatus.FAILED: "Échouée",
    RunStatus.INTERRUPTED: "Interrompue",
}
# A run that brought offers in: the watch is not late after it (Q2).
SUCCESSFUL = frozenset({RunStatus.COMPLETED, RunStatus.PARTIAL})


@dataclass(frozen=True)
class RunCounts:
    """``found``: offers collected; ``new`` and ``completed`` (known offers given new facts) among them;
    ``below_threshold`` and ``incomplete`` among the written ones; ``not_written``: offers a technical error stopped.
    """

    found: int = 0
    new: int = 0
    completed: int = 0
    below_threshold: int = 0
    incomplete: int = 0
    not_written: int = 0


@dataclass(frozen=True)
class SourceRun:
    """What one source gave in a run (a row of ``watch_run_sources``)."""

    source: str
    outcome: Outcome
    reason: str | None
    offers: int
    incomplete: int
    skipped: tuple[tuple[str, str | None, str], ...] = ()
    detail_stopped: str | None = None


@dataclass(frozen=True)
class WatchRun:
    id: int
    account_id: int
    trigger: Trigger
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    reason: str | None
    counts: RunCounts


class RunStore(Protocol):
    """The runs of the watch, on a connection inside the caller's transaction; never commits."""

    def start_run(self, account_id: int, trigger: Trigger, now: datetime) -> int: ...

    def finish_run(
        self,
        run_id: int,
        *,
        status: RunStatus,
        reason: str | None,
        counts: RunCounts,
        sources: Sequence[SourceRun],
        now: datetime,
    ) -> None: ...

    def running_runs(self) -> list[WatchRun]: ...

    def get_run(self, run_id: int) -> WatchRun | None: ...

    def last_run(self, account_id: int) -> WatchRun | None: ...

    def last_successful_run(self, account_id: int) -> WatchRun | None: ...

    def source_runs(self, run_id: int) -> list[SourceRun]: ...


class Store(OfferStore, RunStore, Protocol):
    """All the SQL of the module ``offres`` the watch needs."""


class Storage(Protocol):
    """Transactions and the lock of an account's watch."""

    def transaction(self) -> AbstractContextManager[Store]:
        """One transaction: committed on exit, rolled back on error."""
        ...

    def lock(self, account_id: int) -> AbstractContextManager[bool]:
        """Holds the account's watch lock while open; False when another process holds it."""
        ...


class Profiles(Protocol):
    """The profiles, read through the module ``profil`` (never its SQL)."""

    def watched_accounts(self) -> Iterable[int]:
        """Activated accounts, in a stable order."""
        ...

    def profile(self, account_id: int) -> Profile | None:
        """The account's profile, or None when it has none yet (never created to answer)."""
        ...


class WatchBusyError(Exception):
    """Another watch or rescoring of this account is running."""
