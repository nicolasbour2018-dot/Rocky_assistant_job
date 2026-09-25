"""Application settings read from environment variables prefixed with ``ROCKY_``."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DATABASE_URL_VAR = "ROCKY_DATABASE_URL"
PUBLIC_URL_VAR = "ROCKY_PUBLIC_URL"
SMTP_HOST_VAR = "ROCKY_SMTP_HOST"
SMTP_PORT_VAR = "ROCKY_SMTP_PORT"
SMTP_USERNAME_VAR = "ROCKY_SMTP_USERNAME"
SMTP_PASSWORD_VAR = "ROCKY_SMTP_PASSWORD"  # noqa: S105  (variable name, not a password)
SMTP_FROM_VAR = "ROCKY_SMTP_FROM"
SMTP_STARTTLS_VAR = "ROCKY_SMTP_STARTTLS"
ADZUNA_APP_ID_VAR = "ROCKY_ADZUNA_APP_ID"
ADZUNA_APP_KEY_VAR = "ROCKY_ADZUNA_APP_KEY"
FRANCE_TRAVAIL_ENABLED_VAR = "ROCKY_FRANCE_TRAVAIL_ENABLED"
FRANCE_TRAVAIL_CLIENT_ID_VAR = "ROCKY_FRANCE_TRAVAIL_CLIENT_ID"
FRANCE_TRAVAIL_CLIENT_SECRET_VAR = "ROCKY_FRANCE_TRAVAIL_CLIENT_SECRET"  # noqa: S105  (variable name)
RESULTS_PER_QUERY_VAR = "ROCKY_SOURCES_RESULTS_PER_QUERY"

DEFAULT_SMTP_PORT = 587
DEFAULT_RESULTS_PER_QUERY = 20
BOOLEANS = {
    "true": True,
    "1": True,
    "yes": True,
    "false": False,
    "0": False,
    "no": False,
}


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid."""


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    starttls: bool = True


@dataclass(frozen=True)
class SourcesSettings:
    """Job sources: keys of the official APIs (each optional) and the size of one page of results."""

    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    # France Travail waits for access (D8): off until access is granted.
    france_travail_enabled: bool = False
    france_travail_client_id: str | None = None
    france_travail_client_secret: str | None = None
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY


@dataclass(frozen=True)
class Settings:
    database_url: str
    public_url: str
    smtp: SmtpSettings | None = None
    sources: SourcesSettings = SourcesSettings()

    @property
    def secure_cookies(self) -> bool:
        """Cookies are ``Secure`` whenever Rocky is served over HTTPS."""
        return self.public_url.startswith("https://")


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build the settings from ``environ`` (the process environment by default)."""
    env = os.environ if environ is None else environ
    return Settings(
        database_url=_required(env, DATABASE_URL_VAR),
        public_url=_public_url(env),
        smtp=_smtp(env),
        sources=load_sources_settings(env),
    )


def _value(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _required(env: Mapping[str, str], name: str) -> str:
    value = _value(env, name)
    if not value:
        raise ConfigError(f"missing required environment variable {name}")
    return value


def _public_url(env: Mapping[str, str]) -> str:
    url = _required(env, PUBLIC_URL_VAR).rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{PUBLIC_URL_VAR} must start with http:// or https://")
    return url


def _smtp(env: Mapping[str, str]) -> SmtpSettings | None:
    """SMTP is optional, but all or nothing: a host needs a sender, and the reverse."""
    host, sender = _value(env, SMTP_HOST_VAR), _value(env, SMTP_FROM_VAR)
    if not host and not sender:
        return None
    if not host or not sender:
        raise ConfigError(f"{SMTP_HOST_VAR} and {SMTP_FROM_VAR} go together")
    return SmtpSettings(
        host=host,
        port=_port(env),
        sender=sender,
        username=_value(env, SMTP_USERNAME_VAR) or None,
        password=_value(env, SMTP_PASSWORD_VAR) or None,
        starttls=_boolean(env, SMTP_STARTTLS_VAR, default=True),
    )


def load_sources_settings(environ: Mapping[str, str] | None = None) -> SourcesSettings:
    """The job source settings alone (no database needed: used by the capture procedure too)."""
    env = os.environ if environ is None else environ
    return SourcesSettings(
        adzuna_app_id=_value(env, ADZUNA_APP_ID_VAR) or None,
        adzuna_app_key=_value(env, ADZUNA_APP_KEY_VAR) or None,
        france_travail_enabled=_boolean(env, FRANCE_TRAVAIL_ENABLED_VAR, default=False),
        france_travail_client_id=_value(env, FRANCE_TRAVAIL_CLIENT_ID_VAR) or None,
        france_travail_client_secret=_value(env, FRANCE_TRAVAIL_CLIENT_SECRET_VAR)
        or None,
        results_per_query=_positive(
            env, RESULTS_PER_QUERY_VAR, default=DEFAULT_RESULTS_PER_QUERY
        ),
    )


def _positive(env: Mapping[str, str], name: str, *, default: int) -> int:
    raw = _value(env, name)
    if not raw:
        return default
    if not raw.isdigit() or int(raw) == 0:
        raise ConfigError(f"{name} must be a positive number")
    return int(raw)


def _port(env: Mapping[str, str]) -> int:
    raw = _value(env, SMTP_PORT_VAR)
    if not raw:
        return DEFAULT_SMTP_PORT
    if not raw.isdigit():
        raise ConfigError(f"{SMTP_PORT_VAR} must be a number")
    return int(raw)


def _boolean(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = _value(env, name).lower()
    if not raw:
        return default
    if raw not in BOOLEANS:
        raise ConfigError(f"{name} must be true or false")
    return BOOLEANS[raw]
