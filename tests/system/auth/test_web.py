from __future__ import annotations

import io
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.system.auth.admin import invite
from rocky.system.config import Settings
from rocky.system.web import create_app
from tests.system.auth.fakes import FakeClock, FakeHasher, RecordingMailer

PASSWORD = "un mot de passe solide"
SEVEN_DAYS = 7 * 24 * 3600


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def app(migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock) -> FastAPI:
    settings = Settings(
        database_url="postgresql://unused", public_url="http://testserver"
    )
    return create_app(
        settings,
        engine=migrated_engine,
        mailer=mailer,
        hasher=FakeHasher(),
        clock=clock,
    )


def browser(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


def unique_email() -> str:
    return f"{uuid4().hex}@example.fr"


def token_of(link: str) -> str:
    return parse_qs(urlsplit(link).query)["jeton"][0]


def invitation_token(
    engine: Engine, mailer: RecordingMailer, clock: FakeClock, email: str
) -> str:
    code = invite(
        engine,
        email=email,
        public_url="http://testserver",
        mailer=mailer,
        print_link=False,
        out=io.StringIO(),
        clock=clock,
    )
    assert code == 0
    return token_of(mailer.sent[-1].link)


def activated(
    app: FastAPI, engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> tuple[TestClient, str]:
    email = unique_email()
    client = browser(app)
    response = client.post(
        "/activation",
        data={
            "jeton": invitation_token(engine, mailer, clock, email),
            "password": PASSWORD,
            "confirmation": PASSWORD,
        },
    )
    assert response.status_code == 303
    return client, email


def session_cookie_header(response_headers: list[str]) -> str:
    [header] = [h for h in response_headers if h.startswith("rocky_session=")]
    return header


def test_session_survives_reload_direct_url_and_restart_until_logout(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    email = unique_email()
    token = invitation_token(migrated_engine, mailer, clock, email)
    first = browser(app)

    activation = first.post(
        "/activation",
        data={"jeton": token, "password": PASSWORD, "confirmation": PASSWORD},
    )
    assert activation.status_code == 303
    assert activation.headers["location"] == "/"
    cookie = session_cookie_header(activation.headers.get_list("set-cookie"))
    assert "HttpOnly" in cookie
    assert f"Max-Age={SEVEN_DAYS}" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie  # http://testserver; Secure comes with https

    # Reload.
    for _ in range(2):
        page = first.get("/")
        assert page.status_code == 200
        assert email in page.text

    # Direct URL without a session, then back to it after logging in.
    second = browser(app)
    blocked = second.get("/?vue=liste")
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/connexion?suite=%2F%3Fvue%3Dliste"
    logged = second.post(
        "/connexion",
        data={"email": email, "password": PASSWORD, "suite": "/?vue=liste"},
    )
    assert logged.status_code == 303
    assert logged.headers["location"] == "/?vue=liste"
    assert second.get("/?vue=liste").status_code == 200

    # Browser restart: a new browser that only kept the persistent cookie.
    session_token = first.cookies["rocky_session"]
    restarted = browser(app)
    restarted.cookies.set("rocky_session", session_token)
    assert restarted.get("/").status_code == 200

    # Logout invalidates the session on the server, not only in this browser.
    logout = first.post("/deconnexion")
    assert logout.status_code == 303
    assert logout.headers["location"] == "/connexion"
    assert first.get("/").status_code == 303
    replayed = browser(app)
    replayed.cookies.set("rocky_session", session_token)
    assert replayed.get("/").status_code == 303
    # The other browser's session is untouched.
    assert second.get("/").status_code == 200


def test_session_slides_then_expires_after_seven_idle_days(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    client, _ = activated(app, migrated_engine, mailer, clock)

    clock.advance(timedelta(days=6))
    renewed = client.get("/")
    assert renewed.status_code == 200
    assert f"Max-Age={SEVEN_DAYS}" in session_cookie_header(
        renewed.headers.get_list("set-cookie")
    )

    clock.advance(timedelta(minutes=10))
    assert client.get("/").headers.get_list("set-cookie") == []

    clock.advance(timedelta(days=7))
    expired = client.get("/")
    assert expired.status_code == 303
    assert "Max-Age=0" in session_cookie_header(expired.headers.get_list("set-cookie"))


def test_wrong_password_is_refused_with_a_neutral_message(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    _, email = activated(app, migrated_engine, mailer, clock)

    for address in (email, unique_email()):
        response = browser(app).post(
            "/connexion", data={"email": address, "password": "pas le bon mot de passe"}
        )
        assert response.status_code == 401
        assert "Adresse ou mot de passe incorrect." in response.text


def test_login_never_redirects_to_another_site(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    _, email = activated(app, migrated_engine, mailer, clock)

    response = browser(app).post(
        "/connexion",
        data={"email": email, "password": PASSWORD, "suite": "https://evil.example"},
    )

    assert response.headers["location"] == "/"


def test_activation_requires_matching_passwords(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    token = invitation_token(migrated_engine, mailer, clock, unique_email())

    response = browser(app).post(
        "/activation",
        data={"jeton": token, "password": PASSWORD, "confirmation": PASSWORD + "!"},
    )

    assert response.status_code == 400
    assert "ne sont pas identiques" in response.text


def test_a_used_activation_link_is_refused(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    token = invitation_token(migrated_engine, mailer, clock, unique_email())
    data = {"jeton": token, "password": PASSWORD, "confirmation": PASSWORD}
    browser(app).post("/activation", data=data)

    response = browser(app).post("/activation", data=data)

    assert response.status_code == 400
    assert "invalide, a déjà servi ou a expiré" in response.text


def test_password_reset_flow_closes_existing_sessions(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    client, email = activated(app, migrated_engine, mailer, clock)

    asked = browser(app).post("/mot-de-passe-oublie", data={"email": email})
    assert asked.status_code == 200
    assert "Si un compte actif correspond" in asked.text
    link = mailer.sent[-1].link
    assert link.startswith("http://testserver/reinitialisation?jeton=")

    new_password = "un autre mot de passe"
    reset = browser(app).post(
        "/reinitialisation",
        data={
            "jeton": token_of(link),
            "password": new_password,
            "confirmation": new_password,
        },
    )
    assert reset.status_code == 303
    assert reset.headers["location"] == "/connexion?info=password_changed"
    assert client.get("/").status_code == 303
    relogged = browser(app).post(
        "/connexion", data={"email": email, "password": new_password}
    )
    assert relogged.status_code == 303


def test_forgotten_password_answers_the_same_for_unknown_addresses(
    app: FastAPI, mailer: RecordingMailer
) -> None:
    response = browser(app).post("/mot-de-passe-oublie", data={"email": unique_email()})

    assert response.status_code == 200
    assert "Si un compte actif correspond" in response.text
    assert mailer.sent == []


def test_a_failed_reset_e_mail_is_shown(
    app: FastAPI, migrated_engine: Engine, mailer: RecordingMailer, clock: FakeClock
) -> None:
    _, email = activated(app, migrated_engine, mailer, clock)
    mailer.fail = True

    response = browser(app).post("/mot-de-passe-oublie", data={"email": email})

    assert response.status_code == 503
    # Jinja escapes the apostrophe of "n'a".
    assert "n&#39;a pas pu être envoyé" in response.text


def test_health_needs_no_session(app: FastAPI) -> None:
    response = browser(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
