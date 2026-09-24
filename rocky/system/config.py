"""Application settings read from environment variables prefixed with ``ROCKY_``."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DATABASE_URL_VAR = "ROCKY_DATABASE_URL"


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    database_url: str


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build the settings from ``environ`` (the process environment by default)."""
    env = os.environ if environ is None else environ
    return Settings(database_url=_required(env, DATABASE_URL_VAR))


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"missing required environment variable {name}")
    return value
