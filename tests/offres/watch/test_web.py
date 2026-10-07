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
from rocky.offres.sources.usecases import Outcome
from rocky.offres.sql import SqlStorage
from rocky.offres.watch.model import RunCounts, RunStatus, SourceRun, Trigger
from rocky.offres.watch.service import WatchService
from rocky.offres.watch.web import source_line
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
    sources: Sequence[SourceRun] = (),
    counts: RunCounts | None = None,
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
                counts=counts or RunCounts(),
                sources=sources,
                now=started,
            )


def test_a_watch_never_run_is_a_step_of_the_start_list_not_a_problem(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """Decision G3, Q12: the start list proposes the first watch; the line of state says none succeeded."""
    client, _ = account(app, migrated_engine)

    page = client.get("/").text

    assert "Veille en retard" not in page
    assert "Aucune veille n&#39;a encore réussi." in page
    assert "Pour démarrer" in page and "Première veille" in page
    assert page.count("btn-primary") == 1


def test_no_problem_without_an_active_track(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine, track=False)

    page = client.get("/").text

    assert "notice-problem" not in page
    assert "Aucune piste active : la veille n&#39;a rien à chercher." in page


def test_no_problem_after_a_recent_successful_watch(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """Decision G3, Q13: the line of state says the last watch, with « Lancer la veille » as a plain button."""
    client, account_id = account(app, migrated_engine)
    seed_run(
        app,
        migrated_engine,
        account_id,
        RunStatus.PARTIAL,
        hours_ago=3,
        counts=RunCounts(found=12, new=4),
    )

    page = client.get("/").text

    assert "notice-problem" not in page
    assert "Dernière veille le 24/09 à 11:00 : 12 offres, dont 4 nouvelles." in page
    assert 'class="btn btn-small">Lancer la veille</button>' in page


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

    assert "notice-problem" in page
    assert "⚠️ Veille échouée" in page
    assert "Apec : En panne (HTTP 503)" in page


def test_a_running_watch_is_followed_by_polling_its_line(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.RUNNING, hours_ago=0)

    page = client.get("/").text

    assert "Veille en cours depuis le 24/09 à 14:00." in page
    assert 'hx-get="/cockpit/etat" hx-trigger="every 15s"' in page
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


def test_launching_asks_the_planner_once_and_the_cockpit_follows_the_watch(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    scheduler: Scheduler = app.state.scheduler

    launched = client.post("/veille/lancer")
    client.post("/veille/lancer")

    assert (launched.status_code, launched.headers["location"]) == (303, "/")
    assert scheduler.pending() == [f"veille-compte-{account_id}"]
    assert (
        "Veille lancée : les offres arrivent dans quelques minutes."
        in client.get("/").text
    )
    assert f"veille-compte-{account_id}" in scheduler.tick()
    with SqlStorage(migrated_engine).transaction() as store:
        run = store.last_run(account_id)
    assert run is not None
    assert (run.trigger, run.status) == (Trigger.CATCH_UP, RunStatus.COMPLETED)
    page = client.get("/").text
    assert "Veille lancée" not in page
    assert "Dernière veille le 24/09 à 14:00" in page


# ⚙️ Système (decision F1, Q11): the last run, source by source; the first problem takes the main action.

APEC_RUN = SourceRun(
    "apec",
    Outcome.OK,
    None,
    offers=12,
    incomplete=3,
    skipped=(("Data analyst", "Eure et Loire", "lieu inconnu d'Apec"),) * 2,
)
LINKEDIN_RUN = SourceRun(
    "linkedin", Outcome.REFUSED, "Refusé (HTTP 429)", offers=0, incomplete=0
)


def test_system_without_an_active_track_proposes_one(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine, track=False)

    page = client.get("/systeme").text

    assert "Aucune piste active" in page
    assert page.count("btn-primary") == 1
    assert 'class="btn btn-primary card-action" href="/profil/pistes"' in page


def test_system_tells_the_last_run_source_by_source(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(
        app,
        migrated_engine,
        account_id,
        RunStatus.PARTIAL,
        hours_ago=2,
        sources=(APEC_RUN, LINKEDIN_RUN),
        counts=RunCounts(found=12, new=5),
    )

    page = client.get("/systeme").text

    assert "Dernière veille : 24/09 à 12:00 · Veille planifiée · Partielle" in page
    assert "12 offres trouvées, dont 5 nouvelles." in page
    assert "<dt>Apec</dt>" in page and "<dt>LinkedIn</dt>" in page
    assert page.count("btn-primary") == 1
    assert 'class="btn btn-primary">Lancer la veille maintenant</button>' in page
    assert '<section class="card screen-card">\n    <h2>🔎 Veille</h2>' in page


def test_system_proposes_to_relaunch_a_failed_watch_and_stays_there(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    seed_run(app, migrated_engine, account_id, RunStatus.COMPLETED, hours_ago=5)
    seed_run(app, migrated_engine, account_id, RunStatus.FAILED, hours_ago=1)

    page = client.get("/systeme").text
    launched = client.post("/veille/lancer?retour=systeme")

    assert (
        '<section class="card screen-card screen-card-problem">\n    <h2>🔎 Veille</h2>'
        in page
    )
    assert 'class="btn btn-primary">Relancer la veille</button>' in page
    assert page.count("btn-primary") == 1
    assert launched.headers["location"] == "/systeme"
    assert client.post("/veille/lancer?retour=ailleurs").headers["location"] == "/"


def test_a_source_line_says_what_rocky_admin_sources_says() -> None:
    assert source_line(APEC_RUN) == (
        "Collectée · 12 offres dont 3 incomplètes · requêtes sautées (2) : lieu inconnu d'Apec"
    )
    assert source_line(LINKEDIN_RUN) == "Refusée par la plateforme · Refusé (HTTP 429)"
    assert source_line(
        SourceRun("france_travail", Outcome.PENDING_ACCESS, None, 0, 0)
    ) == ("En attente d'accès · activée quand l'accès à l'API sera accordé (D8)")
    assert source_line(
        SourceRun("wttj", Outcome.OK, None, 4, 0, detail_stopped="Refusé (HTTP 403)")
    ) == ("Collectée · 4 offres · détail arrêté : Refusé (HTTP 403)")


def test_a_profile_change_wakes_the_rescoring_up(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    changed: list[int] = []
    app.state.profile_changed = changed.append

    client.post("/profil/pistes", data={**TRACK, "name": "BI", "titles": "BI analyst"})
    client.get("/profil")

    assert changed == [account_id]


def test_a_change_of_nothing_does_not_wake_the_rescoring_up(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """Step H5: an unknown track writes nothing, so nothing is rescored."""
    client, _ = account(app, migrated_engine)
    changed: list[int] = []
    app.state.profile_changed = changed.append

    response = client.post("/profil/pistes/999999", data={**TRACK, "name": "BI"})

    assert response.status_code == 404
    assert changed == []
