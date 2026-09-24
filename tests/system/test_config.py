from __future__ import annotations

import pytest

from rocky.system.config import ConfigError, Settings, SmtpSettings, load_settings

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
