"""« Préparer mon CV anglais » through HTTP (decision D3, Q16–Q19): import the French CV, translate its texts, validate
them one by one, create the English template, download the English CV."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine

from rocky.profil import translation_web
from rocky.profil.cv.rendering import CvRefusedError
from rocky.profil.translation_web import html_id
from rocky.system.pdf_read import read_pdf
from rocky.system.render import RenderError
from tests.profil.cv.fixtures import ReaderModel, designed_cv
from tests.profil.cv.test_english import ENGLISH
from tests.profil.test_translation import EchoModel
from tests.system.web_support import HTMX, logged_in, make_app, use_model, used_model

ROW = re.compile(
    r'name="cle" value="([^"]+)">\s*<input type="hidden" name="empreinte" value="(\w+)">.*?'
    r'<textarea name="anglais"[^>]*>([^<]*)</textarea>',
    re.DOTALL,
)


@pytest.fixture
def app(migrated_engine: Engine, tmp_path: Path) -> FastAPI:
    app = make_app(migrated_engine, storage_root=tmp_path)
    use_model(app, ReaderModel())
    return app


@pytest.fixture
def client(app: FastAPI, migrated_engine: Engine) -> TestClient:
    """An account whose imported French CV is its active template."""
    client = logged_in(app, migrated_engine)[0]
    page = client.post(
        "/profil/import-cv",
        data={"consentement": "1"},
        files={"fichier": ("cv.pdf", designed_cv(), "application/pdf")},
    )
    template = re.search(r'action="(/profil/gabarit/\d+/activer)"', page.text)
    assert template
    client.post(template.group(1), headers=HTMX)
    use_model(app, EchoModel(ENGLISH))
    return client


def test_without_a_french_template_the_screen_says_what_to_do(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client = logged_in(app, migrated_engine)[0]

    assert "importe-le d&#39;abord" in client.get("/profil/cv-anglais").text


@pytest.mark.parametrize(
    "failure",
    [
        RenderError("Le navigateur n'a pas pu dessiner la page."),
        CvRefusedError(("Le CV dépasse une page.",)),
    ],
)
def test_a_preview_that_cannot_be_drawn_leaves_the_screen_with_its_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Step H1: a refused drawing of the preview was a 500 instead of the screen."""

    def refused(*_: object, **__: object) -> object:
        raise failure

    monkeypatch.setattr(translation_web, "draw_derived", refused)

    response = client.get("/profil/cv-anglais")

    assert response.status_code == 200
    assert "0 texte validé sur 10" in response.text
    assert str(escape(str(failure))) in response.text
    assert "data:image/png;base64," not in response.text


def test_the_english_cv_is_made_from_the_validated_texts(
    client: TestClient, app: FastAPI
) -> None:
    screen = client.get("/profil/cv-anglais").text
    assert "0 texte validé sur 10" in screen
    assert "Créer mon CV anglais" not in screen

    proposed = client.post(
        "/profil/cv-anglais", data={"consentement": "1"}, headers=HTMX
    ).text
    rows = ROW.findall(proposed)
    assert len(rows) == 10
    model: EchoModel = used_model(app)
    assert "camille.martin@example.org" not in model.prompts[0]
    refused = client.post("/profil/cv-anglais/creer", headers=HTMX).text
    assert "Il reste 10 texte(s) à valider" in refused

    first, *others = rows
    accept(client, *first)
    # A text validated once is never sent again (Q19).
    client.post("/profil/cv-anglais", data={"consentement": "1"}, headers=HTMX)
    french = json.dumps(
        next(fr for fr, en in ENGLISH.items() if en == html.unescape(first[2])),
        ensure_ascii=False,
    )
    assert french in model.prompts[0]
    assert french not in model.prompts[1]
    assert "1 texte validé sur 10" in client.get("/profil/cv-anglais").text

    for row in others:
        accept(client, *row)
    created = client.post("/profil/cv-anglais/creer", headers=HTMX).text
    assert "Ton CV anglais est prêt" in created
    cv = client.get("/profil/cv/pdf?langue=en")
    assert cv.headers["content-type"] == "application/pdf"
    assert "Demand forecasting per warehouse." in " ".join(
        read_pdf(cv.content)[0].text.split()
    )


def test_a_validated_text_can_be_corrected_when_it_is_too_long(
    client: TestClient,
) -> None:
    proposed = client.post(
        "/profil/cv-anglais", data={"consentement": "1"}, headers=HTMX
    ).text
    key, footprint, english = ROW.findall(proposed)[0]
    accept(client, key, footprint, english)

    reopened = client.post(
        "/profil/cv-anglais/modifier", data={"cle": key}, headers=HTMX
    ).text
    assert ROW.findall(reopened) == [(key, footprint, english)]
    accept(client, key, footprint, "Shorter")

    screen = client.get("/profil/cv-anglais").text
    assert "→ Shorter" in screen
    assert "1 texte validé sur 10" in screen


def accept(client: TestClient, key: str, footprint: str, english: str) -> None:
    accepted = client.post(
        "/profil/cv-anglais/accepter",
        data={"cle": key, "empreinte": footprint, "anglais": html.unescape(english)},
        headers=HTMX,
    ).text
    assert "Enregistré" in accepted


def test_a_row_id_is_a_valid_selector() -> None:
    assert html_id("label:Stack technique") == "label-Stack-technique"
    assert html_id("project:12:stack") == "project-12-stack"
