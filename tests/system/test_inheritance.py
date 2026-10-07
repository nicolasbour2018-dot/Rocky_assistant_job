"""No boosted gesture inherits a target (decision G6, A1–A3).

The layout boosts every link and form (``hx-boost`` on ``<body>``). HTMX looks for ``hx-target`` and ``hx-swap`` on
the ancestors of a boosted element before it falls back to the body: a container that reads itself again (a screen
polled during a watch or a collection, the drawer) would put the next page inside itself. Every page is read at rest
and while a watch and a collection run.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from bs4 import BeautifulSoup, Tag
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.messages.service import MessagesService
from rocky.offres.sql import SqlStorage
from rocky.offres.watch.model import Trigger
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.scheduler import Scheduler
from tests.messages.fakes import GMAIL, FakeGmail
from tests.system.web_support import logged_in, make_app

PAGES = (
    "/",
    "/offres",
    "/offres?vue=liste",
    "/candidatures",
    "/messages",
    "/bilan",
    "/profil",
    "/systeme",
)
TRACK = {"name": "Data", "titles": "Data analyst", "locations": "Paris"}
# Attributes that make a request explicit: such an element says what it asks, it is not a boosted navigation.
EXPLICIT = ("hx-get", "hx-post", "hx-target", "hx-swap")


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    # Nothing runs by itself: a collection asked for stays pending, as while it runs.
    app.state.scheduler = Scheduler(clock=app.state.auth.clock)
    app.state.messages = MessagesService(
        migrated_engine,
        settings=GMAIL,
        clock=app.state.auth.clock,
        on_collected=lambda account_id, message_ids: None,
        gmail=FakeGmail(),
    )
    return app


def account(app: FastAPI, engine: Engine) -> tuple[TestClient, int]:
    client, email = logged_in(app, engine)
    client.post("/profil/pistes", data=TRACK)
    with engine.connect() as connection:
        found = SqlAuthStore(connection).find_account(email)
    assert found is not None
    return client, found.id


def boosted(element: Tag) -> bool:
    """A link or a form that the layout's ``hx-boost`` turns into an HTMX request."""
    if any(element.has_attr(name) for name in EXPLICIT):
        return False
    if element.name == "a":
        href = str(element.get("href") or "")
        if not href or href.startswith(("#", "http", "mailto:")):
            return False
        if element.get("target") not in (None, "_self"):
            return False
    return all(node.get("hx-boost") != "false" for node in (element, *element.parents))


def inheriting(html: str) -> list[str]:
    """The boosted gestures of ``html`` with an ancestor that declares ``hx-target`` or ``hx-swap``."""
    found = []
    for element in BeautifulSoup(html, "html.parser").find_all(["a", "form"]):
        if not boosted(element):
            continue
        for parent in element.parents:
            if parent.has_attr("hx-target") or parent.has_attr("hx-swap"):
                gesture = element.get("href") or element.get("action")
                found.append(
                    f"{element.name} {gesture} in <{parent.name} id={parent.get('id')}>"
                )
                break
    return found


def run_everything(
    app: FastAPI, engine: Engine, client: TestClient, account_id: int
) -> None:
    """A watch running for an hour, and a collection asked for (pending in the planner)."""
    storage = SqlStorage(engine)
    with storage.transaction() as store:
        store.start_run(
            account_id, Trigger.SCHEDULED, app.state.auth.clock() - timedelta(hours=1)
        )
    assert client.post("/messages/relever").status_code == 303
    assert app.state.scheduler.pending()


def test_no_boosted_gesture_inherits_a_target_at_rest(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = account(app, migrated_engine)

    found = {path: inheriting(client.get(path).text) for path in PAGES}

    assert found == {path: [] for path in PAGES}


def test_no_boosted_gesture_inherits_a_target_while_a_watch_and_a_collection_run(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = account(app, migrated_engine)
    run_everything(app, migrated_engine, client, account_id)

    pages = {path: client.get(path).text for path in PAGES}

    assert 'hx-trigger="every' in pages["/systeme"]
    assert 'hx-trigger="every' in pages["/messages"]
    assert {path: inheriting(html) for path, html in pages.items()} == {
        path: [] for path in PAGES
    }


def test_the_drawer_lends_no_target_to_the_links_it_shows(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """A2: the facts cited by the assistant are boosted links, shown inside the drawer."""
    client, _ = account(app, migrated_engine)

    drawer = BeautifulSoup(client.get("/").text, "html.parser").find(id="rocky-drawer")

    assert isinstance(drawer, Tag)
    assert not drawer.has_attr("hx-target") and not drawer.has_attr("hx-swap")
    loader = drawer.find("div", attrs={"hx-get": "/tiroir"})
    assert isinstance(loader, Tag)
    assert loader.get("hx-trigger") == "toggle[newState=='open'] from:#rocky-drawer"
    assert loader.get("hx-target") == "#drawer-content"


def test_collecting_from_system_by_a_boosted_form_comes_back_to_system(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """A3: a boosted form posts with ``HX-Request``; it wants the next page, not the fragment of 📬."""
    client, _ = account(app, migrated_engine)

    response = client.post(
        "/messages/relever?retour=systeme",
        headers={"HX-Request": "true", "HX-Boosted": "true"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/systeme"


def test_connecting_a_mailbox_leaves_rocky_without_boost(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """A3: Google's consent page is another site; a boosted form could not follow the redirection to it."""
    client, _ = account(app, migrated_engine)

    for path in ("/systeme", "/"):
        page = BeautifulSoup(client.get(path).text, "html.parser")
        forms = page.find_all("form", action="/messages/gmail/connecter")
        assert forms, path
        assert all(form.get("hx-boost") == "false" for form in forms), path
