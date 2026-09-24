from __future__ import annotations

import pytest

from rocky.system.config import ConfigError, Settings, load_settings


def test_load_settings_reads_database_url() -> None:
    settings = load_settings({"ROCKY_DATABASE_URL": "postgresql://u@h/db"})

    assert settings == Settings(database_url="postgresql://u@h/db")


@pytest.mark.parametrize("environ", [{}, {"ROCKY_DATABASE_URL": "  "}])
def test_load_settings_names_the_missing_variable(environ: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="ROCKY_DATABASE_URL"):
        load_settings(environ)


def test_load_settings_ignores_old_rocky_variable() -> None:
    with pytest.raises(ConfigError):
        load_settings({"DATABASE_URL": "postgresql://old@job-assistant-postgres/db"})
