"""The watch assembled on the database, the profiles and the real sources: used by the planner, the screen and
``rocky-admin veille``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import JobSource
from rocky.offres.sources.registry import build_sources
from rocky.offres.sql import SqlStorage
from rocky.offres.watch.model import SourceRun, Trigger, WatchBusyError, WatchRun
from rocky.offres.watch.rules import is_late
from rocky.offres.watch.usecases import (
    Clock,
    SourcesFactory,
    WatchResult,
    active_tracks,
    recover_interrupted,
    rescore_account,
    run_watch,
)
from rocky.profil.api import stored_profile
from rocky.profil.model import Profile
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import SourcesSettings

logger = logging.getLogger(__name__)


class DatabaseProfiles:
    """``Profiles`` read through the module ``profil`` and the accounts of ``system``, one short read each."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def watched_accounts(self) -> list[int]:
        with self._engine.connect() as connection:
            return [
                account.id for account in SqlAuthStore(connection).active_accounts()
            ]

    def profile(self, account_id: int) -> Profile | None:
        with self._engine.connect() as connection:
            return stored_profile(connection, account_id)


def public_sources(settings: SourcesSettings) -> SourcesFactory:
    """The real sources, on a public HTTP client closed after each run."""

    @contextmanager
    def sources() -> Iterator[Sequence[JobSource]]:
        http = PublicHttp()
        try:
            yield build_sources(settings, http)
        finally:
            http.close()

    return sources


@dataclass(frozen=True)
class WatchState:
    """What the banner says (Q2): a run in progress, or a late watch, and the last run for its reason."""

    running: WatchRun | None
    last: WatchRun | None
    last_successful: WatchRun | None
    late: bool


class WatchService:
    def __init__(
        self, engine: Engine, *, sources: SourcesFactory, limit: int, clock: Clock
    ) -> None:
        self.storage = SqlStorage(engine)
        self.profiles = DatabaseProfiles(engine)
        self._sources = sources
        self._limit = limit
        self._clock = clock

    def run(
        self, account_id: int, trigger: Trigger, *, track_name: str | None = None
    ) -> WatchResult:
        """Raises ``WatchBusyError`` when this account's watch is already running."""
        with self._sources() as sources:
            return run_watch(
                self.storage,
                self.profiles,
                sources,
                account_id=account_id,
                trigger=trigger,
                limit=self._limit,
                clock=self._clock,
                track_name=track_name,
            )

    def run_scheduled(self) -> None:
        """The daily watch (Q1, Q8): every activated account with an active track, one after the other."""
        for account_id in self.profiles.watched_accounts():
            if not active_tracks(self.profiles.profile(account_id)):
                logger.info("account %s has no active track: no watch", account_id)
                continue
            try:
                result = self.run(account_id, Trigger.SCHEDULED)
            except WatchBusyError:
                logger.warning("watch of account %s already running", account_id)
                continue
            logger.info(
                "watch run %s of account %s: %s",
                result.run_id,
                account_id,
                result.status,
            )

    def rescore_all(self) -> int:
        """Rescore every account whose scores are out of date (Q5); an account whose watch runs waits."""
        total = 0
        for account_id in self.profiles.watched_accounts():
            try:
                total += rescore_account(
                    self.storage,
                    self.profiles,
                    account_id=account_id,
                    clock=self._clock,
                )
            except WatchBusyError:
                continue
        return total

    def recover(self) -> list[int]:
        closed = recover_interrupted(self.storage, clock=self._clock)
        for run_id in closed:
            logger.warning(
                "watch run %s was left running: closed as interrupted", run_id
            )
        return closed

    def source_runs(self, run_id: int) -> list[SourceRun]:
        """What each source gave in the run ``run_id`` (⚙️ Système, decision F1, Q11)."""
        with self.storage.transaction() as store:
            return store.source_runs(run_id)

    def state(self, account_id: int, now: datetime | None = None) -> WatchState:
        with self.storage.transaction() as store:
            last = store.last_run(account_id)
            last_successful = store.last_successful_run(account_id)
        running = last if last is not None and last.finished_at is None else None
        return WatchState(
            running=running,
            last=last,
            last_successful=last_successful,
            late=running is None and is_late(last_successful, now or self._clock()),
        )
