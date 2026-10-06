"""Application settings read from environment variables prefixed with ``ROCKY_``."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from rocky.system.crypto import is_valid_key

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
# The model of each call type (decision G4, Q24, Q28): a provider and a model name, by default and per call type.
MODEL_PROVIDER_VAR = "ROCKY_MODEL_PROVIDER"
MODEL_NAME_VAR = "ROCKY_MODEL_NAME"
# Before G4, the only model was Gemini's: still read when ``ROCKY_MODEL_NAME`` is missing, with a warning.
GEMINI_MODEL_VAR = "ROCKY_GEMINI_MODEL"
ASSISTANT_DAY_LIMIT_VAR = "ROCKY_ASSISTANT_DAY_LIMIT"
MAIL_MODEL_HOUR_LIMIT_VAR = "ROCKY_LLM_MAIL_HOUR_LIMIT"
MAIL_MODEL_DAY_LIMIT_VAR = "ROCKY_LLM_MAIL_DAY_LIMIT"
SCHEDULER_ENABLED_VAR = "ROCKY_SCHEDULER_ENABLED"
STORAGE_ROOT_VAR = "ROCKY_STORAGE_ROOT"
WORKSTATION_URL_VAR = "ROCKY_WORKSTATION_URL"
GOOGLE_CLIENT_ID_VAR = "ROCKY_GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_VAR = "ROCKY_GOOGLE_CLIENT_SECRET"  # noqa: S105  (variable name)
SECRET_KEY_VAR = "ROCKY_SECRET_KEY"  # noqa: S105  (variable name, not a key)
# The workstation runs on the user's computer (decision D5, Q1); Docker reaches it under this name.
DEFAULT_WORKSTATION_URL = "http://host.docker.internal:8765"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
# The questions to the assistant per account and per Paris day (decision G4, Q8).
DEFAULT_ASSISTANT_DAY_LIMIT = 5
# The calls to the model per account for the classification of the messages (decision E2, Q18).
DEFAULT_MAIL_MODEL_HOUR_LIMIT = 20
DEFAULT_MAIL_MODEL_DAY_LIMIT = 60

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


logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid."""


class Provider(StrEnum):
    """The providers of language models Rocky can call (decision G4, Q23)."""

    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MISTRAL = "mistral"


class CallType(StrEnum):
    """What a call to the model is for (decision G4, Q18): each type may have its own model and is counted apart."""

    ASSISTANT = "assistant"
    SUMMARY = "summary"
    CV = "cv"
    TRANSLATION = "translation"
    LETTER = "letter"
    RECRUITER_MESSAGE = "recruiter_message"
    MAIL_CLASSIFICATION = "mail_classification"


def api_key_var(provider: Provider) -> str:
    """``ROCKY_GEMINI_API_KEY``, ``ROCKY_ANTHROPIC_API_KEY``…"""
    return f"ROCKY_{provider.upper()}_API_KEY"


def provider_var(call_type: CallType) -> str:
    """``ROCKY_ASSISTANT_MODEL_PROVIDER``, ``ROCKY_LETTER_MODEL_PROVIDER``…"""
    return f"ROCKY_{call_type.upper()}_MODEL_PROVIDER"


def name_var(call_type: CallType) -> str:
    """``ROCKY_ASSISTANT_MODEL_NAME``, ``ROCKY_LETTER_MODEL_NAME``…"""
    return f"ROCKY_{call_type.upper()}_MODEL_NAME"


@dataclass(frozen=True)
class ModelChoice:
    """A model: its provider and its name at that provider."""

    provider: Provider
    name: str


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
class LlmSettings:
    """The language models (decision G4, Q24, Q25): one by default, another per call type when set, a key per
    provider. Without the key of its provider, a call type says it is not configured; the start never fails for it."""

    default: ModelChoice = ModelChoice(Provider.GEMINI, DEFAULT_GEMINI_MODEL)
    overrides: Mapping[CallType, ModelChoice] = field(default_factory=dict)
    keys: Mapping[Provider, str] = field(default_factory=dict)
    mail_per_hour: int = DEFAULT_MAIL_MODEL_HOUR_LIMIT
    mail_per_day: int = DEFAULT_MAIL_MODEL_DAY_LIMIT
    assistant_per_day: int = DEFAULT_ASSISTANT_DAY_LIMIT

    def choice(self, call_type: CallType) -> ModelChoice:
        return self.overrides.get(call_type, self.default)

    def key(self, provider: Provider) -> str | None:
        return self.keys.get(provider)


@dataclass(frozen=True)
class GmailSettings:
    """Gmail (decision E1, Q2, Q3): the Google OAuth client and the key that encrypts the refresh tokens."""

    client_id: str | None = None
    client_secret: str | None = None
    secret_key: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.secret_key)


@dataclass(frozen=True)
class Settings:
    database_url: str
    public_url: str
    smtp: SmtpSettings | None = None
    sources: SourcesSettings = SourcesSettings()
    llm: LlmSettings = LlmSettings()
    gmail: GmailSettings = GmailSettings()
    # The planner (daily watch, rescoring, purge; D12): on for the application (``load_settings``), off by default
    # for settings built in code, so that the tests never start its thread.
    scheduler_enabled: bool = False
    # Root of the account files (photos, CV templates; D2). Without it, the features that store files say so.
    storage_root: Path | None = None
    # The Rocky workstation that opens postings in a visible browser on the user's computer (decisions D5, E5): the
    # lecture assistée of the offers; its prefilling of forms is DORMANT (``candidatures.web.PREFILL_ENABLED``).
    workstation_url: str = DEFAULT_WORKSTATION_URL

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
        llm=load_llm_settings(env),
        gmail=_gmail(env),
        scheduler_enabled=_boolean(env, SCHEDULER_ENABLED_VAR, default=True),
        storage_root=_storage_root(env),
        workstation_url=_workstation_url(env),
    )


def load_llm_settings(env: Mapping[str, str]) -> LlmSettings:
    """The models (decision G4, Q28). A provider without a model name, or the reverse, stops the start; a missing key
    does not."""
    keys = {
        provider: key
        for provider in Provider
        if (key := _value(env, api_key_var(provider)))
    }
    overrides = {
        call_type: choice
        for call_type in CallType
        if (choice := _override(env, call_type)) is not None
    }
    return LlmSettings(
        default=_default_model(env),
        overrides=overrides,
        keys=keys,
        mail_per_hour=_count(
            env, MAIL_MODEL_HOUR_LIMIT_VAR, DEFAULT_MAIL_MODEL_HOUR_LIMIT
        ),
        mail_per_day=_count(
            env, MAIL_MODEL_DAY_LIMIT_VAR, DEFAULT_MAIL_MODEL_DAY_LIMIT
        ),
        assistant_per_day=_count(
            env, ASSISTANT_DAY_LIMIT_VAR, DEFAULT_ASSISTANT_DAY_LIMIT
        ),
    )


def _default_model(env: Mapping[str, str]) -> ModelChoice:
    provider = _provider(env, MODEL_PROVIDER_VAR) or Provider.GEMINI
    name = _value(env, MODEL_NAME_VAR)
    if name:
        return ModelChoice(provider, name)
    if provider is not Provider.GEMINI:
        raise ConfigError(
            f"{MODEL_PROVIDER_VAR} is set: {MODEL_NAME_VAR} is needed too"
        )
    legacy = _value(env, GEMINI_MODEL_VAR)
    if legacy:
        logger.warning(
            "%s is deprecated: rename it %s (with %s=gemini)",
            GEMINI_MODEL_VAR,
            MODEL_NAME_VAR,
            MODEL_PROVIDER_VAR,
        )
    return ModelChoice(provider, legacy or DEFAULT_GEMINI_MODEL)


def _override(env: Mapping[str, str], call_type: CallType) -> ModelChoice | None:
    provider = _provider(env, provider_var(call_type))
    name = _value(env, name_var(call_type))
    if provider is None and not name:
        return None
    if provider is None or not name:
        raise ConfigError(
            f"{provider_var(call_type)} and {name_var(call_type)} go together"
        )
    return ModelChoice(provider, name)


def _provider(env: Mapping[str, str], name: str) -> Provider | None:
    raw = _value(env, name).lower()
    if not raw:
        return None
    try:
        return Provider(raw)
    except ValueError:
        known = ", ".join(provider.value for provider in Provider)
        raise ConfigError(f"{name} must be one of: {known}") from None


def _gmail(env: Mapping[str, str]) -> GmailSettings:
    """Missing values leave Gmail "not configured"; a key that is not a Fernet key stops the start (E1)."""
    secret_key = _value(env, SECRET_KEY_VAR) or None
    if secret_key is not None and not is_valid_key(secret_key):
        raise ConfigError(
            f"{SECRET_KEY_VAR} is not a Fernet key (see docs/procedures/e1-gmail/)"
        )
    return GmailSettings(
        client_id=_value(env, GOOGLE_CLIENT_ID_VAR) or None,
        client_secret=_value(env, GOOGLE_CLIENT_SECRET_VAR) or None,
        secret_key=secret_key,
    )


def _workstation_url(env: Mapping[str, str]) -> str:
    url = (_value(env, WORKSTATION_URL_VAR) or DEFAULT_WORKSTATION_URL).rstrip("/")
    if not url.startswith("http://"):
        raise ConfigError(f"{WORKSTATION_URL_VAR} must start with http://")
    return url


def _storage_root(env: Mapping[str, str]) -> Path | None:
    raw = _value(env, STORAGE_ROOT_VAR)
    if not raw:
        return None
    root = Path(raw)
    if not root.is_absolute():
        raise ConfigError(f"{STORAGE_ROOT_VAR} must be an absolute path")
    return root


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
    if not (raw.isascii() and raw.isdigit()) or int(raw) == 0:
        raise ConfigError(f"{name} must be a positive number")
    return int(raw)


def _port(env: Mapping[str, str]) -> int:
    raw = _value(env, SMTP_PORT_VAR)
    if not raw:
        return DEFAULT_SMTP_PORT
    if not (raw.isascii() and raw.isdigit()):
        raise ConfigError(f"{SMTP_PORT_VAR} must be a number")
    return int(raw)


def _count(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _value(env, name)
    if not raw:
        return default
    if not (raw.isascii() and raw.isdigit()):
        raise ConfigError(f"{name} must be a whole number")
    return int(raw)


def _boolean(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = _value(env, name).lower()
    if not raw:
        return default
    if raw not in BOOLEANS:
        raise ConfigError(f"{name} must be true or false")
    return BOOLEANS[raw]
