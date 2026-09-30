"""The screen « Traduire en anglais » through HTTP (decision D3, Q6, Q13, Q14)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.profil.rules import make_project
from rocky.profil.sql import SqlProfileStore
from rocky.profil.usecases import ProfileEditor
from rocky.system.auth.sql import SqlAuthStore
from tests.profil.test_translation import EchoModel
from tests.system.auth.fakes import FakeClock
from tests.system.web_support import HTMX, logged_in, make_app

TRANSLATIONS = {
    "Tri des messages": "Message triage",
    "Python\nBase vectorielle": "Python\nVector database",
}


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.llm_model = EchoModel(TRANSLATIONS)
    return app


@pytest.fixture
def client(app: FastAPI, migrated_engine: Engine) -> TestClient:
    client, email = logged_in(app, migrated_engine)
    with migrated_engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        ProfileEditor(
            SqlProfileStore(connection),
            clock=FakeClock(),
            account_id=account.id,
            email=email,
        ).add_project(
            make_project(name_fr="Tri des messages", stack="Python\nBase vectorielle")
        )
    return client


def test_the_screen_lists_what_has_no_english_and_asks_consent(
    client: TestClient,
) -> None:
    html = client.get("/profil/traduction?retour=/candidatures/1").text

    assert "Projet « Tri des messages » : stack" in html
    assert "J'accepte l'envoi du texte de ces 2 champs à Gemini." in html
    assert 'value="/candidatures/1"' in html

    refused = client.post("/profil/traduction", data={}, headers=HTMX).text
    assert "Coche l&#39;accord" in refused


def test_proposals_are_reviewed_then_accepted_field_by_field(
    client: TestClient, app: FastAPI
) -> None:
    html = client.post(
        "/profil/traduction", data={"consentement": "1"}, headers=HTMX
    ).text
    assert "Message triage" in html
    assert "Python\nVector database" in html
    model: EchoModel = app.state.llm_model
    assert len(model.prompts) == 1

    key = re.search(r'name="cle" value="(project:\d+:stack)"', html)
    footprint = re.search(
        r'name="cle" value="project:\d+:stack">\s*<input type="hidden" name="empreinte" value="(\w+)"',
        html,
    )
    assert key and footprint
    row = client.post(
        "/profil/traduction/accepter",
        data={
            "cle": key.group(1),
            "empreinte": footprint.group(1),
            "anglais": "Python\nVector database",
        },
        headers=HTMX,
    ).text
    assert "Enregistré dans ton profil" in row

    after = client.get("/profil/traduction").text
    assert "Projet « Tri des messages » : stack" not in after
    assert "Projet « Tri des messages » : nom" in after


def test_a_glossary_term_is_added_and_removed(client: TestClient) -> None:
    html = client.post(
        "/profil/glossaire", data={"fr": "Pilotage", "en": "Steering"}, headers=HTMX
    ).text
    assert "Pilotage → <strong>Steering</strong>" in html

    term = re.search(r"/profil/glossaire/(\d+)/supprimer", html)
    assert term
    removed = client.post(
        f"/profil/glossaire/{term.group(1)}/supprimer", headers=HTMX
    ).text
    assert "Aucun terme pour l'instant." in removed


def test_the_way_back_stays_inside_rocky(client: TestClient) -> None:
    html = client.get("/profil/traduction?retour=//exemple.org").text

    assert 'value="/profil/kit"' in html
