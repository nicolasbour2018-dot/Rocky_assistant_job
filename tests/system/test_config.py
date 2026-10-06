from __future__ import annotations

import pytest

from rocky.system.config import (
    CallType,
    ConfigError,
    GmailSettings,
    LlmSettings,
    ModelChoice,
    Provider,
    Settings,
    SmtpSettings,
    SourcesSettings,
    load_settings,
    load_sources_settings,
)

# A Fernet key made for the tests (not a secret).
KEY = "dGVzdHMtb25seS1rZXktZm9yLXJvY2t5LWUxLTMyYnk="

BASE = {
    "ROCKY_DATABASE_URL": "postgresql://u@h/db",
    "ROCKY_PUBLIC_URL": "http://127.0.0.1:8000/",
}


def test_load_settings_without_smtp() -> None:
    settings = load_settings(BASE)

    assert settings == Settings(
        database_url="postgresql://u@h/db",
        public_url="http://127.0.0.1:8000",
        scheduler_enabled=True,
    )
    assert settings.secure_cookies is False


def test_the_language_model_is_optional_with_a_default_model() -> None:
    assert load_settings(BASE).llm == LlmSettings(
        default=ModelChoice(Provider.GEMINI, "gemini-3.5-flash-lite")
    )

    settings = load_settings(
        {
            **BASE,
            "ROCKY_MODEL_PROVIDER": "Anthropic",
            "ROCKY_MODEL_NAME": " claude-sonnet-5-5 ",
            "ROCKY_ANTHROPIC_API_KEY": " k-1 ",
            "ROCKY_ASSISTANT_DAY_LIMIT": "8",
        }
    )

    assert settings.llm.default == ModelChoice(Provider.ANTHROPIC, "claude-sonnet-5-5")
    assert settings.llm.key(Provider.ANTHROPIC) == "k-1"
    assert settings.llm.key(Provider.GEMINI) is None
    assert settings.llm.assistant_per_day == 8


def test_each_call_type_may_have_its_own_model() -> None:
    settings = load_settings(
        {
            **BASE,
            "ROCKY_ASSISTANT_MODEL_PROVIDER": "mistral",
            "ROCKY_ASSISTANT_MODEL_NAME": "mistral-medium",
        }
    )

    assert settings.llm.choice(CallType.ASSISTANT) == ModelChoice(
        Provider.MISTRAL, "mistral-medium"
    )
    assert settings.llm.choice(CallType.LETTER) == settings.llm.default


@pytest.mark.parametrize(
    "half",
    [
        {"ROCKY_LETTER_MODEL_PROVIDER": "openai"},
        {"ROCKY_LETTER_MODEL_NAME": "gpt-autre"},
    ],
)
def test_a_half_given_override_stops_the_start(half: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="ROCKY_LETTER_MODEL_PROVIDER and"):
        load_settings({**BASE, **half})


def test_an_unknown_provider_stops_the_start() -> None:
    with pytest.raises(ConfigError, match="ROCKY_MODEL_PROVIDER must be one of"):
        load_settings({**BASE, "ROCKY_MODEL_PROVIDER": "ollama"})


def test_another_default_provider_needs_its_model_name() -> None:
    with pytest.raises(ConfigError, match="ROCKY_MODEL_NAME is needed"):
        load_settings({**BASE, "ROCKY_MODEL_PROVIDER": "openai"})


def test_the_former_gemini_model_is_still_read_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = load_settings(
        {**BASE, "ROCKY_GEMINI_API_KEY": "k-1", "ROCKY_GEMINI_MODEL": "gemini-autre"}
    )

    assert settings.llm.default == ModelChoice(Provider.GEMINI, "gemini-autre")
    assert settings.llm.key(Provider.GEMINI) == "k-1"
    assert "ROCKY_GEMINI_MODEL is deprecated" in caplog.text
    assert "k-1" not in caplog.text


def test_gmail_is_not_configured_until_the_client_and_the_key_are_given() -> None:
    assert load_settings(BASE).gmail == GmailSettings()
    assert GmailSettings().configured is False

    settings = load_settings(
        {
            **BASE,
            "ROCKY_GOOGLE_CLIENT_ID": " id.apps.googleusercontent.com ",
            "ROCKY_GOOGLE_CLIENT_SECRET": "s",
            "ROCKY_SECRET_KEY": KEY,
        }
    )

    assert settings.gmail == GmailSettings(
        client_id="id.apps.googleusercontent.com", client_secret="s", secret_key=KEY
    )
    assert settings.gmail.configured is True
    assert GmailSettings(client_id="id", client_secret="s").configured is False


def test_a_secret_key_that_is_not_a_fernet_key_stops_the_start() -> None:
    with pytest.raises(ConfigError, match="ROCKY_SECRET_KEY"):
        load_settings({**BASE, "ROCKY_SECRET_KEY": "trop-courte"})


def test_the_workstation_is_reached_from_docker_by_default() -> None:
    assert load_settings(BASE).workstation_url == "http://host.docker.internal:8765"
    assert (
        load_settings({**BASE, "ROCKY_WORKSTATION_URL": "http://127.0.0.1:9000/"})
    ).workstation_url == "http://127.0.0.1:9000"
    with pytest.raises(ConfigError, match="ROCKY_WORKSTATION_URL"):
        load_settings({**BASE, "ROCKY_WORKSTATION_URL": "file:///poste"})


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


@pytest.mark.parametrize("value", ["0", "-3", "vingt", "²"])
def test_results_per_query_must_be_positive(value: str) -> None:
    with pytest.raises(ConfigError, match="ROCKY_SOURCES_RESULTS_PER_QUERY"):
        load_settings({**BASE, "ROCKY_SOURCES_RESULTS_PER_QUERY": value})


def test_source_settings_load_without_database_settings() -> None:
    assert load_sources_settings({"ROCKY_ADZUNA_APP_ID": "id"}).adzuna_app_id == "id"
    with pytest.raises(ConfigError, match="ROCKY_SOURCES_RESULTS_PER_QUERY"):
        load_sources_settings({"ROCKY_SOURCES_RESULTS_PER_QUERY": "abc"})


def test_the_planner_runs_in_the_application_unless_turned_off() -> None:
    assert load_settings(BASE).scheduler_enabled
    assert not load_settings(
        {**BASE, "ROCKY_SCHEDULER_ENABLED": "false"}
    ).scheduler_enabled
    # Settings built in code (the tests) never start its thread.
    assert not Settings(database_url="x", public_url="http://x").scheduler_enabled
