from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rocky.system.config import ConfigError, Settings
from rocky.system.web import create_app


def test_health_answers_ok() -> None:
    app = create_app(Settings(database_url="postgresql://u@h/db"))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_fails_at_startup_without_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROCKY_DATABASE_URL", raising=False)

    with pytest.raises(ConfigError):
        create_app()
