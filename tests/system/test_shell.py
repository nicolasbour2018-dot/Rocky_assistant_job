from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine

from rocky.system.shell import (
    HTMX_SCRIPT,
    NAVIGATION,
    Action,
    Card,
    main_action,
)
from tests.system.web_support import HTMX, invitation_token, logged_in, make_app


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    return make_app(migrated_engine)


def test_the_shell_shows_the_seven_entries_and_the_active_one(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, email = logged_in(app, migrated_engine)

    page = client.get("/candidatures")

    assert page.status_code == 200
    sidebar = page.text.split('class="sidebar"')[1].split("</nav>")[0]
    for entry in NAVIGATION:
        assert f'href="{entry.path}"' in sidebar
        assert str(escape(entry.label)) in sidebar
    assert re.search(r'href="/candidatures"[^>]*aria-current="page"', sidebar)
    assert email in page.text
    assert HTMX_SCRIPT in page.text


def test_the_phone_bar_keeps_four_entries_and_a_more_menu(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    tabbar = client.get("/").text.split('class="tabbar"')[1].split("</nav>")[0]

    assert [e.path for e in NAVIGATION if e.primary] == [
        "/",
        "/offres",
        "/candidatures",
        "/messages",
    ]
    assert tabbar.count('class="tab"') == 5
    assert 'popovertarget="more-menu"' in tabbar


def test_shell_pages_require_a_session(app: FastAPI) -> None:
    anonymous = TestClient(app, follow_redirects=False)

    response = anonymous.get("/bilan")

    assert response.status_code == 303
    assert response.headers["location"] == "/connexion?suite=%2Fbilan"


def test_an_htmx_request_without_session_reloads_to_the_login_page(
    app: FastAPI,
) -> None:
    anonymous = TestClient(app, follow_redirects=False)

    response = anonymous.get("/offres/liste", headers=HTMX)

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/connexion?suite=%2Foffres%2Fliste"
    assert response.text == ""


@pytest.mark.parametrize(
    "path",
    [
        "/static/rocky.css",
        "/static/rocky.js",
        "/static/favicon.svg",
        f"/static/{HTMX_SCRIPT}",
    ],
)
def test_static_files_are_served_without_session(app: FastAPI, path: str) -> None:
    assert TestClient(app).get(path).status_code == 200


def test_account_pages_use_the_style_without_the_navigation(app: FastAPI) -> None:
    page = TestClient(app).get("/connexion")

    assert "/static/rocky.css" in page.text
    assert 'class="sidebar"' not in page.text


def test_set_password_page_names_the_account_for_password_managers(
    app: FastAPI, migrated_engine: Engine
) -> None:
    email = "gestionnaire@example.fr"
    token = invitation_token(migrated_engine, email)

    page = TestClient(app).get(f"/activation?jeton={token}")

    assert re.search(
        rf'name="username" autocomplete="username" value="{email}"', page.text
    )


def test_a_dead_link_says_so_before_asking_for_a_password(app: FastAPI) -> None:
    page = TestClient(app).get("/activation?jeton=forged")

    assert page.status_code == 400
    assert "invalide, a déjà servi ou a expiré" in page.text
    assert 'name="password"' not in page.text


# The cross-cutting screens (step F1)

LINK = Action("Voir", "/offres")
FIX = Action("Réparer", "/reparer", post=True)


@pytest.mark.parametrize(
    ("cards", "main"),
    [
        ([], None),
        ([Card("Sans geste")], None),
        ([Card("A"), Card("B", action=LINK), Card("C", action=LINK)], 1),
        ([Card("A", action=LINK), Card("B", action=FIX, problem=True)], 1),
        ([Card("A", problem=True), Card("B", action=LINK)], 1),
    ],
    ids=[
        "none",
        "no-action",
        "first-action",
        "problem-first",
        "problem-without-action",
    ],
)
def test_the_main_action_is_the_first_problem_else_the_first_action(
    cards: list[Card], main: int | None
) -> None:
    assert main_action(cards) == main
