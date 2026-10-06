"""Helpers for tests that drive the web application: a test app and a logged-in browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import BytecodeCache
from jinja2.bccache import Bucket
from sqlalchemy import Engine

from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import Auth, Invited
from rocky.system.config import CallType, Settings
from rocky.system.llm import JsonModel
from rocky.system.llm.calls import Models
from rocky.system.web import create_app
from tests.system.auth.fakes import FakeClock, FakeHasher, RecordingMailer

PASSWORD = "un mot de passe solide"


class SharedBytecode(BytecodeCache):
    """Compiled templates kept for the whole run, in memory: each test builds a new application, whose Jinja
    environment would compile every template again (decision G1). Filters and globals are read when rendering,
    so the compiled code is the same for every application."""

    def __init__(self) -> None:
        self._code: dict[str, bytes] = {}

    def load_bytecode(self, bucket: Bucket) -> None:
        code = self._code.get(bucket.key)
        if code is not None:
            bucket.bytecode_from_string(code)

    def dump_bytecode(self, bucket: Bucket) -> None:
        self._code[bucket.key] = bucket.bytecode_to_string()


SHARED_BYTECODE = SharedBytecode()


def make_app(
    engine: Engine,
    mailer: RecordingMailer | None = None,
    *,
    storage_root: Path | None = None,
) -> FastAPI:
    settings = Settings(
        database_url="postgresql://unused",
        public_url="http://testserver",
        storage_root=storage_root,
    )
    app = create_app(
        settings,
        engine=engine,
        mailer=mailer or RecordingMailer(),
        hasher=FakeHasher(),
        clock=FakeClock(),
    )
    app.state.templates.env.bytecode_cache = SHARED_BYTECODE
    return app


def invitation_token(engine: Engine, email: str) -> str:
    """The invitation use case of ``rocky-admin invite`` (tested in ``test_admin``), without its argon2 hasher:
    building one costs a real hash (40 ms), and an invitation hashes nothing (decision G1)."""
    with engine.begin() as connection:
        invited = Auth(
            SqlAuthStore(connection),
            hasher=FakeHasher(),
            clock=FakeClock(),
            public_url="http://testserver",
        ).invite(email)
    assert isinstance(invited, Invited)
    return parse_qs(urlsplit(invited.mail.link).query)["jeton"][0]


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


def use_model(app: FastAPI, model: JsonModel) -> None:
    """Every call type of ``app`` calls ``model`` (a fake), its calls recorded like the real ones (decision G4)."""
    app.state.models = Models(
        app.state.engine,
        app.state.settings.llm,
        app.state.auth.clock,
        model_of=lambda call_type: model,
    )


def used_model(app: FastAPI) -> Any:
    """The fake given by ``use_model``."""
    models: Models = app.state.models
    return models.model(CallType.ASSISTANT)
