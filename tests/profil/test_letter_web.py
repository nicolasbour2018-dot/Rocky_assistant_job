"""The screen « Ma lettre de motivation » through HTTP (decision D4, Q6, Q9, Q13, Q17)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from rocky.profil.model import StoredLetter
from rocky.profil.sql import SqlProfileStore
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.events import events
from tests.profil.test_letter import ANSWER, LETTER
from tests.profil.test_translation import EchoModel
from tests.system.test_docx_read import docx, paragraph, run
from tests.system.web_support import HTMX, logged_in, make_app, use_model, used_model

TRANSLATIONS = {
    "Data analyste en reconversion, je souhaite rejoindre {entreprise} comme {poste}.": (
        "A data analyst who changed careers, I wish to join {entreprise} as {poste}."
    ),
    "Pendant huit ans, j'ai piloté des projets de bout en bout.": (
        "For eight years, I led projects from start to finish."
    ),
    "{entreprise} m'attire par ses produits de santé.": (
        "{entreprise} appeals to me through its health products."
    ),
    "Je serais heureux d'en parler avec vous.": "I would be glad to talk it over with you.",
}


class LetterModel:
    """Cuts a letter (the answer it is given) or translates it (an ``EchoModel``), by the schema asked."""

    def __init__(self) -> None:
        self.translator = EchoModel(TRANSLATIONS)
        self.calls = 0

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.calls += 1
        if "job_title" in schema["properties"]:
            return ANSWER
        return self.translator.complete_json(instructions, prompt, schema)


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    use_model(app, LetterModel())
    return app


@dataclass(frozen=True)
class Browser:
    client: TestClient
    account_id: int
    engine: Engine

    def letter(self, language: str) -> StoredLetter | None:
        with self.engine.connect() as connection:
            store = SqlProfileStore(connection)
            profile_id = store.find_profile_id(self.account_id)
            assert profile_id is not None
            return store.generic_letter(profile_id, language)


@pytest.fixture
def browser(app: FastAPI, migrated_engine: Engine) -> Browser:
    client, email = logged_in(app, migrated_engine)
    with migrated_engine.connect() as connection:
        account = SqlAuthStore(connection).find_account(email)
    assert account is not None
    return Browser(client, account.id, migrated_engine)


@pytest.fixture
def client(browser: Browser) -> TestClient:
    return browser.client


def save_reviewed(client: TestClient, html: str) -> str:
    """Submit the review form as Rocky filled it."""
    roles = re.findall(r'<option value="(\w+)" selected>', html)
    texts = re.findall(r'<textarea name="texte"[^>]*>([^<]*)</textarea>', html)
    response = client.post(
        "/profil/lettre/enregistrer",
        data={
            "langue": "fr",
            "origine": "import",
            "role": roles,
            "texte": [t.replace("&#39;", "'") for t in texts],
        },
        headers=HTMX,
    )
    assert response.status_code == 200
    return response.text


def test_a_pasted_letter_is_cut_reviewed_then_saved(
    client: TestClient, app: FastAPI, migrated_engine: Engine
) -> None:
    refused = client.post(
        "/profil/lettre/importer", data={"texte": LETTER}, headers=HTMX
    ).text
    assert "Coche l&#39;accord" in refused
    assert used_model(app).calls == 0

    review = client.post(
        "/profil/lettre/importer",
        data={"texte": LETTER, "consentement": "1", "langue": "fr"},
        headers=HTMX,
    ).text

    assert "Relis le découpage de ta lettre" in review
    assert "Rocky a remplacé « Data Analyst » par <strong>{poste}</strong>." in review
    assert "Écarté : formule d&#39;appel" in review
    saved = save_reviewed(client, review)

    assert "Ta lettre est enregistrée." in saved
    assert "{entreprise} m&#39;attire par ses produits de santé." in saved
    assert "Madame, Monsieur," not in saved  # set aside: Rocky writes it
    with migrated_engine.connect() as connection:
        kinds = connection.execute(
            select(events.c.type).where(events.c.type == "profil.cover_letter_saved")
        ).scalars()
        assert "profil.cover_letter_saved" in set(kinds)


def test_a_docx_letter_is_read_from_its_file(client: TestClient) -> None:
    content = docx("".join(paragraph(run(line)) for line in LETTER.split("\n\n")))

    review = client.post(
        "/profil/lettre/importer",
        data={"consentement": "1"},
        files={"fichier": ("lettre.docx", content)},
        headers=HTMX,
    ).text

    assert "Relis le découpage de ta lettre" in review
    assert "pas mot pour mot" not in review


def test_the_english_letter_is_validated_paragraph_by_paragraph(
    browser: Browser,
) -> None:
    client = browser.client
    review = client.post(
        "/profil/lettre/importer",
        data={"texte": LETTER, "consentement": "1"},
        headers=HTMX,
    ).text
    save_reviewed(client, review)

    proposals = client.post(
        "/profil/lettre/anglais", data={"consentement": "1"}, headers=HTMX
    ).text
    assert "Lettre : parcours (§ 2)" in proposals
    keys = re.findall(r'name="cle" value="(letter:\d+)"', proposals)
    prints = re.findall(r'name="empreinte" value="(\w+)"', proposals)
    englishes = re.findall(
        r'<textarea name="anglais"[^>]*>([^<]*)</textarea>', proposals
    )
    assert len(keys) == 4

    early = client.post("/profil/lettre/anglais/creer", headers=HTMX).text
    assert "Il reste 4 paragraphes à valider" in early
    for key, fingerprint, english in zip(keys, prints, englishes, strict=True):
        accepted = client.post(
            "/profil/lettre/anglais/accepter",
            data={"cle": key, "empreinte": fingerprint, "anglais": english},
            headers=HTMX,
        ).text
        assert "✅" in accepted
    created = client.post("/profil/lettre/anglais/creer", headers=HTMX).text

    assert "Ta lettre anglaise est prête." in created
    assert "For eight years, I led projects from start to finish." in created
    french, english = browser.letter("fr"), browser.letter("en")
    assert french is not None and english is not None
    # The English letter knows the French one it was translated from (Q17).
    assert english.source_sha256 == french.sha256
    assert english.letter.paragraphs[0].text.endswith("as {poste}.")


def test_editing_the_letter_adds_a_version(
    client: TestClient, migrated_engine: Engine
) -> None:
    review = client.post(
        "/profil/lettre/importer",
        data={"texte": LETTER, "consentement": "1"},
        headers=HTMX,
    ).text
    save_reviewed(client, review)

    form = client.get("/profil/lettre?modifier=fr").text
    assert "Modifier ta lettre" in form
    roles = re.findall(r'<option value="(\w+)" selected>', form)
    texts = [
        t.replace("&#39;", "'")
        for t in re.findall(r'<textarea name="texte"[^>]*>([^<]*)</textarea>', form)
    ]
    texts[1] = "Pendant huit ans, j'ai mené des projets."
    edited = client.post(
        "/profil/lettre/enregistrer",
        data={"langue": "fr", "origine": "edit", "role": roles, "texte": texts},
        headers=HTMX,
    ).text

    assert "j&#39;ai mené des projets" in edited
    bad = client.post(
        "/profil/lettre/enregistrer",
        data={"langue": "fr", "role": ["opening"], "texte": ["Chez {societe}."]},
        headers=HTMX,
    ).text
    assert "Variable inconnue {societe}" in bad


def test_the_kit_links_to_the_letter(client: TestClient) -> None:
    assert 'href="/profil/lettre"' in client.get("/profil/kit").text
    page = client.get("/profil/lettre").text
    assert "Importer ta lettre" in page
