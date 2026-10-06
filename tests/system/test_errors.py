"""The handler of business errors (step H1): a refusal a route forgot to catch is shown, never a 500."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.candidatures.model import InvalidChangeError
from rocky.profil.cv.rendering import CvRefusedError
from rocky.profil.rules import ProfileInputError
from rocky.system.errors import UserFacingError
from rocky.system.render import RenderError
from tests.system.web_support import HTMX, logged_in, make_app

BOOSTED = {**HTMX, "HX-Boosted": "true"}
ERRORS: dict[str, UserFacingError] = {
    "change": InvalidChangeError("Cette candidature a été annulée."),
    "profil": ProfileInputError("Donne un nom à <la> compétence."),
    "cv": CvRefusedError(("Le CV dépasse une page.", "La photo est illisible.")),
    "rendu": RenderError("Le navigateur n'a pas pu dessiner la page."),
}


@pytest.fixture
def client(migrated_engine: Engine) -> TestClient:
    app: FastAPI = make_app(migrated_engine)

    @app.post("/candidatures/essai/{kind}")
    def fail(kind: str) -> None:
        raise ERRORS[kind]

    # Before the routes of the module, which would take « essai » for an application.
    app.router.routes.insert(0, app.router.routes.pop())
    browser, _ = logged_in(app, migrated_engine)
    return browser


def test_the_business_errors_share_the_base_of_system() -> None:
    assert all(isinstance(error, UserFacingError) for error in ERRORS.values())
    # The local handlers that catch ValueError keep catching them.
    assert isinstance(ERRORS["change"], ValueError)
    assert isinstance(ERRORS["profil"], ValueError)


def test_a_fragment_shows_the_message_in_the_error_area(client: TestClient) -> None:
    response = client.post("/candidatures/essai/profil", headers=HTMX)

    assert response.status_code == 200
    assert response.headers["HX-Retarget"] == "#erreur"
    assert response.headers["HX-Reswap"] == "innerHTML"
    assert 'role="alert"' in response.text
    assert "Donne un nom à &lt;la&gt; compétence." in response.text
    assert "<html" not in response.text


def test_each_reason_of_a_refused_cv_is_a_line(client: TestClient) -> None:
    text = client.post("/candidatures/essai/cv", headers=HTMX).text

    assert "<li>Le CV dépasse une page.</li>" in text
    assert "<li>La photo est illisible.</li>" in text


def test_a_boosted_form_gets_a_whole_page_it_can_swap(client: TestClient) -> None:
    response = client.post("/candidatures/essai/rendu", headers=BOOSTED)

    # HTMX swaps no 4xx answer: the boosted navigation needs a 200 to show the page.
    assert response.status_code == 200
    assert "HX-Retarget" not in response.headers
    assert "<html" in response.text
    assert "Action impossible" in response.text
    assert "Le navigateur n&#39;a pas pu dessiner la page." in response.text
    assert 'href="/candidatures"' in response.text


def test_without_javascript_the_page_says_conflict(client: TestClient) -> None:
    response = client.post("/candidatures/essai/change")

    assert response.status_code == 409
    assert "<html" in response.text
    assert "Cette candidature a été annulée." in response.text


def test_the_error_is_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="rocky.system.shell"):
        client.post("/candidatures/essai/change", headers=HTMX)

    assert any(
        "InvalidChangeError" in record.getMessage()
        and "/candidatures/essai/change" in record.getMessage()
        for record in caplog.records
    )


def test_every_page_has_the_error_area(client: TestClient) -> None:
    page = client.get("/offres").text

    assert 'id="erreur"' in page
