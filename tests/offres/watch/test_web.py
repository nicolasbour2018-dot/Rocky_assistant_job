"""The watch on screen (C6, Q2; decision F1, Q6): the first block of 🏠 Aujourd'hui when the watch is late, running or
failed, with « Lancer maintenant », and the counter of 🏠."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.offres.sources.model import JobSource, SourceCode
from rocky.offres.sql import SqlStorage
from rocky.offres.watch.model import RunCounts, RunStatus, Trigger
from rocky.offres.watch.service import WatchService
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.scheduler import Scheduler
from tests.offres.fakes import posting
from tests.offres.sources.fakes import FakeSource
from tests.system.web_support import logged_in, make_app

TRACK = {"name": "Data", "titles": "Data analyst", "locations": "Paris"}


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)

    @contextmanager
    def fake_sources() -> Iterator[Sequence[JobSource]]:
        yield [FakeSource(SourceCode.APEC, lambda query: [posting("a1")])]

    app.state.watch = WatchService(
        migrated_engine, sources=fake_sources, limit=20, clock=app.state.auth.clock
    )
    # Only what the screen asks: no daily watch nor rescoring of the other tests' accounts.
    app.state.scheduler = Scheduler(clock=app.state.auth.clock)
    return app


def account(
    app: FastAPI, engine: Engine, *, track: bool = True
) -> tuple[TestClient, int]:
    client, email = logged_in(app, engine)
    if track:
        client.post("/profil/pistes", data=TRACK)
    with engine.connect() as connection:
        found = SqlAuthStore(connection).find_account(email)
    assert found is not None
    return client, found.id


def seed_run(
    app: FastAPI,
    engine: Engine,
    account_id: int,
    status: RunStatus,
    *,
    hours_ago: float,
) -> None:
    started = app.state.auth.clock() - timedelta(hours=hours_ago)
    storage = SqlStorage(engine)
    with storage.transaction() as store:
        run_id = store.start_run(account_id, Trigger.SCHEDULED, started)
        if status is not RunStatus.RUNNING:
            store.finish_run(
                run_id,
                status=status,
                reason="Apec : En panne (HTTP 503)"
                if status is RunStatus.FAILED
                else None,
                counts=RunCounts(),
                sources=(),
                now=started,
            )


def test_a_watch_never_run_is_proposed_in_today_and_nowhere_else(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine)

    page = client.get("/").text

    assert "⏰ Veille en retard" in page
    assert "Aucune veille n&#39;a encore réussi." in page
    assert 'class="btn btn-primary">Lancer maintenant</button>' in page
    assert "Veille en retard" not in client.get("/profil").text


def test_no_block_without_an_active_track(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine, track=False)

    assert "Veille" not in client.get("/").text


def test_no_block_after_a_recent_successful_watch(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.PARTIAL, hours_ago=3)

    assert "Veille" not in client.get("/").text


def test_a_late_watch_says_when_it_last_succeeded(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.COMPLETED, hours_ago=30)

    page = client.get("/").text

    # The fake clock says 24/09 12:00 UTC: 30 hours before is 23/09 06:00 UTC, 08:00 in Paris.
    assert "La dernière veille réussie date du 23/09 à 08:00." in page


def test_a_failed_watch_shows_its_reason(app: FastAPI, migrated_engine: Engine) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.COMPLETED, hours_ago=5)
    seed_run(app, migrated_engine, account_id, RunStatus.FAILED, hours_ago=1)

    page = client.get("/").text

    assert "screen-card-problem" in page
    assert "⚠️ Veille échouée" in page
    assert "Apec : En panne (HTTP 503)" in page


def test_a_running_watch_is_followed_by_polling_today(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.RUNNING, hours_ago=0)

    page = client.get("/").text

    assert "Veille en cours depuis le 24/09 à 14:00." in page
    assert 'hx-get="/" hx-trigger="every 15s"' in page
    assert "Lancer maintenant" not in page


@pytest.mark.parametrize(
    ("status", "hours_ago", "count"),
    [
        (RunStatus.COMPLETED, 30, 1),
        (RunStatus.FAILED, 1, 1),
        (RunStatus.RUNNING, 0, 0),
        (RunStatus.COMPLETED, 3, 0),
    ],
    ids=["late", "failed", "running", "on-time"],
)
def test_the_counter_of_today_says_the_watch_asks_for_a_gesture(
    app: FastAPI,
    migrated_engine: Engine,
    status: RunStatus,
    hours_ago: float,
    count: int,
) -> None:
    client, account_id = account(app, migrated_engine)
    if status is not RunStatus.COMPLETED:
        # A failure or a run in progress after a recent success: the watch is not late.
        seed_run(app, migrated_engine, account_id, RunStatus.COMPLETED, hours_ago=5)
    seed_run(app, migrated_engine, account_id, status, hours_ago=hours_ago)

    page = client.get("/profil").text

    shown = f'id="nav-count-today" class="nav-count" title="{count} à traiter"'
    assert shown in page
    assert (f"{shown} hidden" in page) is (count == 0)


def test_launching_asks_the_planner_once_and_today_follows_the_watch(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    scheduler: Scheduler = app.state.scheduler

    launched = client.post("/veille/lancer")
    client.post("/veille/lancer")

    assert (launched.status_code, launched.headers["location"]) == (303, "/")
    assert scheduler.pending() == [f"veille-compte-{account_id}"]
    assert "🔄 Veille lancée" in client.get("/").text
    assert f"veille-compte-{account_id}" in scheduler.tick()
    with SqlStorage(migrated_engine).transaction() as store:
        run = store.last_run(account_id)
    assert run is not None
    assert (run.trigger, run.status) == (Trigger.CATCH_UP, RunStatus.COMPLETED)
    assert "Veille" not in client.get("/").text


def test_a_profile_change_wakes_the_rescoring_up(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    changed: list[int] = []
    app.state.profile_changed = changed.append

    client.post("/profil/pistes", data={**TRACK, "name": "BI", "titles": "BI analyst"})
    client.get("/profil")

    assert changed == [account_id]
