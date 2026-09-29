"""The watch on screen (C6, Q2): the banner when the watch is late, running or failed, and « Lancer maintenant »."""

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
from tests.system.web_support import HTMX, logged_in, make_app

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


def test_a_watch_never_run_is_proposed_on_every_page(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine)

    page = client.get("/profil").text

    assert 'id="veille-bandeau"' in page
    assert "Aucune veille n" in page
    assert "Lancer maintenant" in page


def test_no_banner_without_an_active_track(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine, track=False)

    assert 'id="veille-bandeau"' not in client.get("/profil").text


def test_no_banner_after_a_recent_successful_watch(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.PARTIAL, hours_ago=3)

    assert 'id="veille-bandeau"' not in client.get("/profil").text


def test_a_late_watch_says_when_it_last_succeeded(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.COMPLETED, hours_ago=30)

    page = client.get("/profil").text

    # The fake clock says 24/09 12:00 UTC: 30 hours before is 23/09 06:00 UTC, 08:00 in Paris.
    assert "la dernière veille réussie date du\n      23/09 à 08:00" in page


def test_a_failed_watch_shows_its_reason(app: FastAPI, migrated_engine: Engine) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.COMPLETED, hours_ago=5)
    seed_run(app, migrated_engine, account_id, RunStatus.FAILED, hours_ago=1)

    page = client.get("/profil").text

    assert "alert-error" in page
    assert "a échoué" in page
    assert "Apec : En panne (HTTP 503)" in page


def test_a_running_watch_is_followed_by_polling(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.RUNNING, hours_ago=0)

    fragment = client.get("/veille/bandeau", headers=HTMX).text

    assert "Veille en cours depuis le 24/09 à 14:00" in fragment
    assert 'hx-trigger="every 15s"' in fragment


def test_launching_asks_the_planner_once_and_the_watch_then_runs(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    scheduler: Scheduler = app.state.scheduler

    launched = client.post("/veille/lancer", headers=HTMX)
    client.post("/veille/lancer", headers=HTMX)

    assert "Veille lancée" in launched.text
    assert scheduler.pending() == [f"veille-compte-{account_id}"]
    assert f"veille-compte-{account_id}" in scheduler.tick()
    with SqlStorage(migrated_engine).transaction() as store:
        run = store.last_run(account_id)
    assert run is not None
    assert (run.trigger, run.status) == (Trigger.CATCH_UP, RunStatus.COMPLETED)
    assert client.get("/veille/bandeau", headers=HTMX).text == (
        '<div id="veille-bandeau" hidden></div>'
    )


def test_launching_without_htmx_goes_back_to_today(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine)

    response = client.post("/veille/lancer")

    assert (response.status_code, response.headers["location"]) == (303, "/")


def test_a_profile_change_wakes_the_rescoring_up(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    changed: list[int] = []
    app.state.profile_changed = changed.append

    client.post("/profil/pistes", data={**TRACK, "name": "BI", "titles": "BI analyst"})
    client.get("/profil")

    assert changed == [account_id]
