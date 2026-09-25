"""« Importer une annonce » through HTTP, as HTMX drives it (``HX-Request``) and without JavaScript."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine

from rocky.offres.imports.rules import VISIBLE_TEXT_REASON
from rocky.offres.imports.usecases import PASTE_HINT
from rocky.offres.imports.web import offer_facts
from rocky.offres.sources.model import CollectedOffer
from tests.offres.sources.replay import Answer, Replay, answer
from tests.system.web_support import HTMX, logged_in, make_app

DATA = Path(__file__).parent / "data"
HELLOWORK = "https://www.hellowork.com/fr-fr/emplois/77695894.html"
SEARCH = "https://www.hellowork.com/fr-fr/emploi/recherche.html"


def html_page(name: str) -> Answer:
    return answer((DATA / name).read_text(), content_type="text/html; charset=utf-8")


@pytest.fixture
def replay() -> Replay:
    return Replay(
        {
            ("GET", "/fr-fr/emplois/77695894.html"): html_page(
                "hellowork.com/posting.html"
            ),
            ("GET", "/fr-fr/emploi/recherche.html"): html_page(
                "hellowork.com/page.html"
            ),
            ("GET", "/fr-fr/emplois/1.html"): answer(
                status=403, content_type="text/html"
            ),
            ("GET", "/fr-fr/emplois/2.html"): answer(
                status=404, content_type="text/html"
            ),
        }
    )


@pytest.fixture
def app(migrated_engine: Engine, replay: Replay) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.import_http = replay.http
    app.state.import_today = lambda: date(2026, 9, 25)
    return app


@pytest.fixture
def client(app: FastAPI, migrated_engine: Engine) -> TestClient:
    return logged_in(app, migrated_engine)[0]


def text_of(html: str) -> str:
    return html.replace("&#39;", "'").replace("&amp;", "&")


def test_the_offers_screen_leads_to_the_import(client: TestClient) -> None:
    assert 'href="/offres/importer"' in client.get("/offres").text

    page = client.get("/offres/importer")

    assert page.status_code == 200
    assert "Importer une annonce" in page.text
    assert 'hx-post="/offres/importer"' in page.text
    assert 'aria-current="page"' in page.text  # 🔎 Offres stays the active entry


def test_a_boosted_navigation_to_the_import_gets_the_whole_page(
    client: TestClient,
) -> None:
    # The layout boosts every link (hx-boost): following "Importer une annonce" is an HTMX request.
    page = client.get("/offres/importer", headers={**HTMX, "HX-Boosted": "true"})

    assert "<html" in page.text
    assert "<title>Importer une annonce · Rocky</title>" in page.text


def test_the_import_needs_a_session(app: FastAPI) -> None:
    response = TestClient(app).get("/offres/importer", follow_redirects=False)

    assert response.status_code in {302, 303, 307}


@pytest.mark.parametrize("htmx", [True, False], ids=["htmx", "whole-page"])
def test_an_invalid_link_shows_its_reason(
    client: TestClient, replay: Replay, htmx: bool
) -> None:
    response = client.post(
        "/offres/importer", data={"lien": "pas-une-url"}, headers=HTMX if htmx else {}
    )

    assert response.status_code == (200 if htmx else 400)
    assert "Le lien doit commencer par http:// ou https://." in text_of(response.text)
    assert 'role="alert"' in response.text
    assert ("<html" in response.text) is not htmx
    assert replay.requests == []
    # An invalid link is corrected, not pasted.
    assert "Coller la description" not in response.text


def test_a_link_to_the_server_network_shows_its_reason(client: TestClient) -> None:
    response = client.post(
        "/offres/importer", data={"lien": "http://127.0.0.1/admin"}, headers=HTMX
    )

    assert "Le lien vise une adresse privée ou locale (127.0.0.1)" in text_of(
        response.text
    )


def test_a_posting_link_shows_its_preview(client: TestClient) -> None:
    response = client.post("/offres/importer", data={"lien": HELLOWORK}, headers=HTMX)
    page = text_of(response.text)

    assert response.status_code == 200
    assert "Data Analyst Banque Expérimenté H/F" in page
    assert "hellowork.com" in page
    assert "Lue par : données structurées de l'annonce" in page
    assert "Description complète" in page
    assert "<dt>Employeur</dt><dd>Alteca</dd>" in page
    assert "<dt>Date limite</dt><dd>08/10/2026</dd>" in page
    assert "Aperçu seulement" in page
    assert "Coller la description" not in page


def test_a_page_without_posting_shows_its_text_and_offers_to_paste(
    client: TestClient,
) -> None:
    response = client.post("/offres/importer", data={"lien": SEARCH}, headers=HTMX)
    page = text_of(response.text)

    assert "Description incomplète" in page
    assert str(escape(VISIBLE_TEXT_REASON)).replace("&#39;", "'") in page
    assert "Coller la description" in page


def test_a_refused_link_shows_the_refusal_and_offers_to_paste(
    client: TestClient, replay: Replay
) -> None:
    response = client.post(
        "/offres/importer",
        data={"lien": "https://www.hellowork.com/fr-fr/emplois/1.html"},
        headers=HTMX,
    )
    page = text_of(response.text)

    assert "Refusé par hellowork.com" in page
    assert PASTE_HINT in page
    assert 'name="lien" value="https://www.hellowork.com/fr-fr/emplois/1.html"' in page
    assert len(replay.requests) == 1  # never retried


def test_a_missing_posting_says_so(client: TestClient) -> None:
    response = client.post(
        "/offres/importer",
        data={"lien": "https://www.hellowork.com/fr-fr/emplois/2.html"},
    )

    assert response.status_code == 200
    assert "L'annonce n'existe plus, ou le lien est faux (HTTP 404)." in text_of(
        response.text
    )


def test_a_pasted_description_gives_the_preview(client: TestClient) -> None:
    response = client.post(
        "/offres/importer/texte",
        data={
            "lien": HELLOWORK,
            "intitule": "Data analyst",
            "employeur": "Alteca",
            "texte": "Missions : tableaux de bord.",
        },
        headers=HTMX,
    )
    page = text_of(response.text)

    assert "Lue par : description collée" in page
    assert "Description complète" in page
    assert "Missions : tableaux de bord." in page


@pytest.mark.parametrize("htmx", [True, False], ids=["htmx", "whole-page"])
def test_an_unusable_paste_keeps_what_was_typed(client: TestClient, htmx: bool) -> None:
    response = client.post(
        "/offres/importer/texte",
        data={
            "lien": HELLOWORK,
            "intitule": "",
            "employeur": "Alteca",
            "texte": "Missions.",
        },
        headers=HTMX if htmx else {},
    )
    page = text_of(response.text)

    assert response.status_code == (200 if htmx else 400)
    assert "Indique l'intitulé de l'annonce." in page
    assert 'value="Alteca"' in page
    assert "Missions.</textarea>" in page


def test_the_facts_show_only_what_the_posting_says() -> None:
    offer = CollectedOffer(
        source="site.example",
        external_id="1",
        url="https://site.example/1",
        title="Data analyst",
        description="",
        description_complete=False,
        location="Paris",
        country="FR",
        salary_min=45000,
        salary_max=55000,
        salary_currency="EUR",
        salary_period="YEAR",
        published_on=date(2026, 9, 1),
    )

    assert offer_facts(offer) == [
        ("Lieu", "Paris, FR"),
        ("Salaire", "45 000 – 55 000 EUR YEAR"),
        ("Publiée le", "01/09/2026"),
    ]
