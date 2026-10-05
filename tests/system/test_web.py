from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.system.config import ConfigError
from rocky.system.scheduler import DailyTask, PeriodicTask, Scheduler
from rocky.system.web import SCHEDULER_OFF, create_app, planner_card
from tests.system.web_support import make_app


def test_create_app_fails_at_startup_without_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROCKY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ROCKY_PUBLIC_URL", raising=False)

    with pytest.raises(ConfigError):
        create_app()


class RecordingScheduler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit(self, name: str, task: object) -> None:
        self.calls.append(f"submit {name}")

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


@pytest.mark.parametrize(
    ("enabled", "calls"),
    [
        (True, ["submit reprise", "submit reprise-messages", "start", "stop"]),
        (False, ["stop"]),
    ],
)
def test_the_planner_lives_with_the_application_when_enabled(
    migrated_engine: Engine, enabled: bool, calls: list[str]
) -> None:
    app = make_app(migrated_engine)
    app.state.settings = replace(app.state.settings, scheduler_enabled=enabled)
    scheduler = RecordingScheduler()
    app.state.scheduler = scheduler

    with TestClient(app):
        pass

    # First tasks: close the watch runs and the mail collections a stopped process left open.
    assert scheduler.calls == calls


# ⚙️ Système: the planner (decision F1, Q8, Q11)


def test_the_planner_panel_gives_each_task_and_its_next_run() -> None:
    def nothing() -> None:
        return None

    scheduler = Scheduler(
        daily=[
            DailyTask("veille", time(12, 0), nothing),
            DailyTask("purge", time(4, 0), nothing),
        ],
        periodic=[
            PeriodicTask("recalcul", timedelta(minutes=1), nothing),
            PeriodicTask("messages", timedelta(hours=1), nothing),
        ],
        clock=lambda: datetime(2026, 10, 5, 8, 0, tzinfo=UTC),
    )

    card = planner_card(scheduler, enabled=True)

    assert card.details == (
        (
            "Veille des offres",
            "chaque jour à 12:00 · prochain passage le 05/10 à 12:00",
        ),
        (
            "Relevé des boîtes Gmail",
            "toutes les heures · prochain passage le 05/10 à 10:00",
        ),
        ("Recalcul des scores", "dès que le profil ou les règles changent"),
        (
            "Purge des sessions expirées",
            "chaque nuit à 04:00 · prochain passage le 06/10 à 04:00",
        ),
    )
    assert not card.problem


def test_a_planner_switched_off_is_a_problem_without_gesture() -> None:
    card = planner_card(Scheduler(), enabled=False)

    assert card.lines == (SCHEDULER_OFF,)
    assert (card.problem, card.action) == (True, None)
    assert card.details[0] == ("Veille des offres", "chaque jour à 12:00")
