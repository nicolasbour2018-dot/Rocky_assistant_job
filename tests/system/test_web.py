from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.system.config import ConfigError
from rocky.system.web import create_app
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
    [(True, ["submit reprise", "start", "stop"]), (False, ["stop"])],
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

    # First task: close the runs a stopped process left open.
    assert scheduler.calls == calls
