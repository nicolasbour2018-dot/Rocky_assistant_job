from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine

from rocky.system.auth.model import Account
from rocky.system.shell import (
    HTMX_SCRIPT,
    NAVIGATION,
    Action,
    Card,
    Drawer,
    add_drawer,
    add_today_cards,
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


@pytest.mark.parametrize(
    "entry",
    [
        e
        for e in NAVIGATION
        if e.key
        not in {"today", "offers", "profile", "applications", "messages", "system"}
    ],
    ids=lambda e: e.key,
)
def test_pages_not_built_yet_explain_themselves(
    app: FastAPI, migrated_engine: Engine, entry: object
) -> None:
    client, _ = logged_in(app, migrated_engine)
    path, step = entry.path, entry.arrives_in  # type: ignore[attr-defined]

    page = client.get(path)

    assert page.status_code == 200
    assert f"étape {step}" in page.text


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


def _cards(*cards: Card) -> object:
    return lambda request, account: list(cards)


def _today(app: FastAPI, **providers: object) -> None:
    """Replace the modules' blocks of 🏠 Aujourd'hui by ``providers`` (key → cards)."""
    app.state.today_cards = dict(providers)


def test_an_empty_today_says_so_and_offers_one_main_action(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _today(app)

    page = client.get("/").text

    assert "Rien ne demande ton attention pour l'instant." in page
    assert page.count("btn-primary") == 1
    assert 'class="btn btn-primary card-action" href="/offres?vue=liste"' in page


def test_today_orders_its_blocks_and_has_one_main_action(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _today(
        app,
        offres=_cards(Card("🔎 Offres", ("12 à examiner",), action=LINK)),
        messages=_cards(Card("📬 Messages", action=Action("Lire", "/messages"))),
    )

    page = client.get("/").text

    assert page.index("📬 Messages") < page.index("🔎 Offres")
    assert page.count("btn-primary") == 1
    assert 'class="btn btn-primary card-action" href="/messages"' in page
    assert 'class="btn card-action" href="/offres"' in page


def test_a_problem_takes_the_main_action_as_a_form(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _today(
        app,
        veille=_cards(Card("⚠️ Veille", action=FIX, problem=True)),
        offres=_cards(Card("🔎 Offres", action=LINK)),
    )

    page = client.get("/").text

    assert page.count("btn-primary") == 1
    assert '<form method="post" action="/reparer"' in page
    assert 'class="btn btn-primary">Réparer</button>' in page


def test_blocks_without_action_leave_the_main_action_to_the_empty_one(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _today(app, veille=_cards(Card("🔄 Veille en cours", polling=True)))

    page = client.get("/").text

    assert page.count("btn-primary") == 1
    assert (
        'hx-get="/" hx-trigger="every 15s" hx-target="this" hx-swap="outerHTML"' in page
    )


def test_today_polled_by_htmx_is_its_cards_alone(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _today(app, offres=_cards(Card("🔎 Offres", action=LINK)))

    fragment = client.get("/", headers=HTMX).text

    assert fragment.lstrip().startswith('<div id="cards"')
    assert "<html" not in fragment


def test_a_block_with_an_unknown_place_is_refused(app: FastAPI) -> None:
    with pytest.raises(KeyError):
        add_today_cards(app, "ailleurs", _cards())  # type: ignore[arg-type]


def test_the_drawer_shows_the_screen_s_actions_and_shortcuts(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    def drawer(request: object, account: Account) -> Drawer:
        return Drawer(actions=(LINK,), shortcuts=(("j", "Offre suivante"),))

    add_drawer(app, "offers", drawer)

    fragment = client.get("/tiroir?ecran=offers", headers=HTMX).text
    other = client.get("/tiroir?ecran=inconnu", headers=HTMX).text
    whole = client.get("/tiroir?ecran=offers").text

    assert "À faire ici" in fragment
    assert '<a class="btn card-action" href="/offres">Voir</a>' in fragment
    assert "<kbd>j</kbd>" in fragment
    assert "<html" not in fragment
    assert "Rien de particulier à faire sur cet écran" in other
    assert 'class="sidebar"' in whole


def test_the_drawer_is_loaded_when_it_opens_for_the_active_screen(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    page = client.get("/candidatures").text

    assert 'hx-get="/tiroir?ecran=applications"' in page
    assert "hx-trigger=\"toggle[newState=='open']\"" in page
