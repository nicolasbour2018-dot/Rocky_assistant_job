"""The handler of business errors (step H1): a refusal a route forgot to catch is shown, never a 500."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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


def test_htmx_is_told_to_show_the_4xx_answers(client: TestClient) -> None:
    """Decision G6 (A4, A9): HTMX 2 drops a 4xx answer unless told otherwise."""
    page = client.get("/").text

    assert '<meta name="htmx-config"' in page
    assert '{"code": "4..", "swap": true}' in page


@pytest.mark.parametrize(
    ("path", "status_code", "words"),
    [
        (
            "/offres/999999/motifs/interested",
            404,
            "Rocky ne trouve pas ce que ce geste demande",
        ),
        ("/offres/999999/actions", 404, "Rocky ne trouve pas ce que ce geste demande"),
    ],
    ids=["reasons", "actions"],
)
def test_a_refusal_without_words_is_shown_in_the_error_area(
    client: TestClient, path: str, status_code: int, words: str
) -> None:
    """Decision G6, A9: an empty 404 of 🔎 Offres said nothing on screen."""
    response = client.get(path, headers=HTMX)

    assert response.status_code == status_code
    assert response.headers["HX-Retarget"] == "#erreur"
    assert words in response.text


def test_a_refused_form_shows_its_reason(client: TestClient) -> None:
    """The JSON of a form FastAPI refuses becomes words in the error area."""
    response = client.post("/offres/1/decision", data={}, headers=HTMX)

    assert response.status_code == 422
    assert response.headers["HX-Retarget"] == "#erreur"
    assert "Il manque quelque chose à cette demande" in response.text


def test_a_refusal_with_its_own_html_is_left_to_its_target(
    migrated_engine: Engine,
) -> None:
    app: FastAPI = make_app(migrated_engine)

    @app.get("/essai-refus")
    def refused() -> HTMLResponse:
        return HTMLResponse("<p>Le nom est obligatoire.</p>", status_code=422)

    browser, _ = logged_in(app, migrated_engine)
    response = browser.get("/essai-refus", headers=HTMX)

    assert response.status_code == 422
    assert "HX-Retarget" not in response.headers
    assert response.text == "<p>Le nom est obligatoire.</p>"


def test_a_refusal_without_htmx_is_left_as_it_is(client: TestClient) -> None:
    response = client.get("/offres/999999/actions")

    assert response.status_code == 404
    assert "HX-Retarget" not in response.headers
