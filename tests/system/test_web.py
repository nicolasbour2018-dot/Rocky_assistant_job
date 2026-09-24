from __future__ import annotations

import pytest

from rocky.system.config import ConfigError
from rocky.system.web import create_app


def test_create_app_fails_at_startup_without_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROCKY_DATABASE_URL", raising=False)
    monkeypatch.delenv("ROCKY_PUBLIC_URL", raising=False)

    with pytest.raises(ConfigError):
        create_app()
