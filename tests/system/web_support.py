"""Helpers for tests that drive the web application: a test app and a logged-in browser."""

from __future__ import annotations

import io
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.system.auth.admin import invite
from rocky.system.config import Settings
from rocky.system.web import create_app
from tests.system.auth.fakes import FakeClock, FakeHasher, RecordingMailer

PASSWORD = "un mot de passe solide"


def make_app(engine: Engine, mailer: RecordingMailer | None = None) -> FastAPI:
    settings = Settings(
        database_url="postgresql://unused", public_url="http://testserver"
    )
    return create_app(
        settings,
        engine=engine,
        mailer=mailer or RecordingMailer(),
        hasher=FakeHasher(),
        clock=FakeClock(),
    )


def invitation_token(engine: Engine, email: str) -> str:
    mailer = RecordingMailer()
    invite(
        engine,
        email=email,
        public_url="http://testserver",
        mailer=mailer,
        print_link=False,
        out=io.StringIO(),
        clock=FakeClock(),
    )
    return parse_qs(urlsplit(mailer.sent[-1].link).query)["jeton"][0]


def logged_in(
    app: FastAPI, engine: Engine, *, onboarding: bool = False
) -> tuple[TestClient, str]:
    """A browser with an activated account and an open session; returns it with the address.

    Unless ``onboarding`` is asked for, the onboarding is put off ("Plus tard"), so that main pages show.
    """
    email = f"{uuid4().hex}@example.fr"
    client = TestClient(app, follow_redirects=False)
    response = client.post(
        "/activation",
        data={
            "jeton": invitation_token(engine, email),
            "password": PASSWORD,
            "confirmation": PASSWORD,
        },
    )
    assert response.status_code == 303
    if not onboarding:
        assert client.post("/profil/demarrage/plus-tard").status_code == 303
    return client, email


HTMX = {"HX-Request": "true"}
