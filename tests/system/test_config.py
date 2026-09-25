from __future__ import annotations

import pytest

from rocky.system.config import (
    ConfigError,
    LlmSettings,
    Settings,
    SmtpSettings,
    SourcesSettings,
    load_settings,
    load_sources_settings,
)

BASE = {
    "ROCKY_DATABASE_URL": "postgresql://u@h/db",
    "ROCKY_PUBLIC_URL": "http://127.0.0.1:8000/",
}


def test_load_settings_without_smtp() -> None:
    settings = load_settings(BASE)

    assert settings == Settings(
        database_url="postgresql://u@h/db", public_url="http://127.0.0.1:8000"
    )
    assert settings.secure_cookies is False


def test_the_language_model_is_optional_with_a_default_model() -> None:
    assert load_settings(BASE).llm == LlmSettings(
        api_key=None, model="gemini-3.5-flash-lite"
    )

    settings = load_settings(
        {**BASE, "ROCKY_GEMINI_API_KEY": " k-1 ", "ROCKY_GEMINI_MODEL": "gemini-autre"}
    )

    assert settings.llm == LlmSettings(api_key="k-1", model="gemini-autre")


def test_https_public_url_makes_cookies_secure() -> None:
    settings = load_settings({**BASE, "ROCKY_PUBLIC_URL": "https://rocky.example"})

    assert settings.secure_cookies is True


def test_load_settings_reads_smtp() -> None:
    settings = load_settings(
        {
            **BASE,
            "ROCKY_SMTP_HOST": "smtp.example",
            "ROCKY_SMTP_PORT": "465",
            "ROCKY_SMTP_FROM": "Rocky <rocky@example>",
            "ROCKY_SMTP_USERNAME": "rocky",
            "ROCKY_SMTP_PASSWORD": "app-password",
            "ROCKY_SMTP_STARTTLS": "false",
        }
    )

    assert settings.smtp == SmtpSettings(
        host="smtp.example",
        port=465,
        sender="Rocky <rocky@example>",
        username="rocky",
        password="app-password",
        starttls=False,
    )


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"ROCKY_PUBLIC_URL": "http://x"}, "ROCKY_DATABASE_URL"),
        ({"ROCKY_DATABASE_URL": "postgresql://u@h/db"}, "ROCKY_PUBLIC_URL"),
        ({**BASE, "ROCKY_PUBLIC_URL": "127.0.0.1:8000"}, "ROCKY_PUBLIC_URL"),
        ({**BASE, "ROCKY_SMTP_HOST": "smtp.example"}, "go together"),
        ({**BASE, "ROCKY_SMTP_FROM": "rocky@example"}, "go together"),
        (
            {
                **BASE,
                "ROCKY_SMTP_HOST": "h",
                "ROCKY_SMTP_FROM": "f",
                "ROCKY_SMTP_PORT": "x",
            },
            "ROCKY_SMTP_PORT",
        ),
        (
            {
                **BASE,
                "ROCKY_SMTP_HOST": "h",
                "ROCKY_SMTP_FROM": "f",
                "ROCKY_SMTP_STARTTLS": "maybe",
            },
            "ROCKY_SMTP_STARTTLS",
        ),
    ],
)
def test_load_settings_names_the_faulty_variable(
    environ: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_settings(environ)


def test_load_settings_ignores_old_rocky_variables() -> None:
    with pytest.raises(ConfigError):
        load_settings(
            {
                "DATABASE_URL": "postgresql://old@job-assistant-postgres/db",
                "SMTP_HOST": "smtp.example",
            }
        )


def test_sources_are_optional_and_france_travail_waits_by_default() -> None:
    assert load_settings(BASE).sources == SourcesSettings()
    assert SourcesSettings().france_travail_enabled is False
    assert SourcesSettings().results_per_query == 20


def test_load_settings_reads_the_sources() -> None:
    settings = load_settings(
        {
            **BASE,
            "ROCKY_ADZUNA_APP_ID": "id",
            "ROCKY_ADZUNA_APP_KEY": "key",
            "ROCKY_FRANCE_TRAVAIL_ENABLED": "true",
            "ROCKY_FRANCE_TRAVAIL_CLIENT_ID": "client",
            "ROCKY_FRANCE_TRAVAIL_CLIENT_SECRET": "secret",
            "ROCKY_SOURCES_RESULTS_PER_QUERY": "10",
        }
    )

    assert settings.sources == SourcesSettings(
        adzuna_app_id="id",
        adzuna_app_key="key",
        france_travail_enabled=True,
        france_travail_client_id="client",
        france_travail_client_secret="secret",
        results_per_query=10,
    )


@pytest.mark.parametrize("value", ["0", "-3", "vingt"])
def test_results_per_query_must_be_positive(value: str) -> None:
    with pytest.raises(ConfigError, match="ROCKY_SOURCES_RESULTS_PER_QUERY"):
        load_settings({**BASE, "ROCKY_SOURCES_RESULTS_PER_QUERY": value})


def test_source_settings_load_without_database_settings() -> None:
    assert load_sources_settings({"ROCKY_ADZUNA_APP_ID": "id"}).adzuna_app_id == "id"
    with pytest.raises(ConfigError, match="ROCKY_SOURCES_RESULTS_PER_QUERY"):
        load_sources_settings({"ROCKY_SOURCES_RESULTS_PER_QUERY": "abc"})
