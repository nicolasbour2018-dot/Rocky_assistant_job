"""📬 Messages on screen (decision E1, Q2, Q8): connect a mailbox through Google, collect it, see the raw list,
disconnect it. Google is replayed, never called."""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.messages.classification.model import View
from rocky.messages.model import AccessLostError, MailboxStatus
from rocky.messages.oauth import ACCESS_LOST_REASON
from rocky.messages.service import NOT_CONFIGURED, MessagesService
from rocky.messages.web import EXPIRED, REFUSED, STATE_COOKIE
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.scheduler import Scheduler
from tests.messages.fakes import (
    API_URL,
    GMAIL,
    TOKEN_URL,
    FakeGmail,
    Google,
    json_answer,
    recorded,
)
from tests.system.web_support import HTMX, logged_in, make_app

REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def google() -> Google:
    return Google(
        {
            ("POST", TOKEN_URL): lambda r: json_answer(recorded("oauth_exchange.json")),
            ("GET", f"{API_URL}/profile"): lambda r: json_answer(
                recorded("profile.json")
            ),
            ("POST", REVOKE_URL): lambda r: httpx2.Response(200),
        }
    )


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    """Without Gmail settings, as ``make_app`` builds it; ``configure`` gives it a fake Google."""
    app = make_app(migrated_engine)
    # Only what the screen asks: the hourly collection of the other tests' mailboxes never runs.
    app.state.scheduler = Scheduler(clock=app.state.auth.clock)
    return app


def configure(
    app: FastAPI, engine: Engine, gmail: FakeGmail | None = None
) -> tuple[Google, FakeGmail]:
    fake_google, fake_gmail = google(), gmail or FakeGmail()

    def collected(account_id: int, message_ids: Sequence[int]) -> None:
        app.state.messages_collected(account_id, message_ids)

    app.state.messages = MessagesService(
        engine,
        settings=GMAIL,
        clock=app.state.auth.clock,
        on_collected=collected,
        transport=fake_google.transport(),
        gmail=fake_gmail,
    )
    return fake_google, fake_gmail


def account_of(engine: Engine, email: str) -> int:
    with engine.connect() as connection:
        found = SqlAuthStore(connection).find_account(email)
    assert found is not None
    return found.id


def to_google(client: TestClient) -> dict[str, str]:
    """« Connecter une boîte Gmail »: the parameters of Google's consent page."""
    response = client.post("/messages/gmail/connecter")
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    return {key: values[0] for key, values in parse_qs(location.query).items()}


def connected(app: FastAPI, client: TestClient) -> None:
    params = to_google(client)
    response = client.get(
        "/messages/gmail/retour", params={"code": "4/code", "state": params["state"]}
    )
    assert response.status_code == 303
    scheduler: Scheduler = app.state.scheduler
    scheduler.tick()  # The first collection, asked by the connection.


def test_without_gmail_settings_the_page_says_what_is_missing(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    page = client.get("/messages")
    refused = client.post("/messages/gmail/connecter")

    assert page.status_code == 200
    assert NOT_CONFIGURED.replace("'", "&#39;") in page.text
    assert "Connecter une boîte Gmail" not in page.text
    assert refused.status_code == 400
    assert NOT_CONFIGURED.replace("'", "&#39;") in refused.text


def test_a_mailbox_is_connected_through_google_then_collected(
    app: FastAPI, migrated_engine: Engine
) -> None:
    fake_google, _ = configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    collected: list[list[int]] = []
    app.state.messages_collected = lambda account_id, ids: collected.append(list(ids))

    params = to_google(client)
    cookie = client.cookies.get(STATE_COOKIE)
    back = client.get(
        "/messages/gmail/retour", params={"code": "4/code", "state": params["state"]}
    )

    assert params["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert params["redirect_uri"] == "http://testserver/messages/gmail/retour"
    assert cookie is not None and params["state"] not in cookie
    assert back.status_code == 303
    assert back.headers["location"] == "/messages?boite=connectee"
    assert client.cookies.get(STATE_COOKIE) is None
    scheduler: Scheduler = app.state.scheduler
    assert len(scheduler.pending()) == 1

    scheduler.tick()
    page = client.get("/messages?boite=connectee&vue=tous")

    assert "camille.dupont@example.com" in page.text
    assert "Connectée" in page.text
    assert "Boîte connectée : son premier relevé est lancé." in page.text
    assert "Votre candidature : Data Analyst" in page.text
    assert "3 nouveaux messages" in re.sub(r"\s+", " ", page.text)
    # The hook was replaced: nothing is decided, the messages wait in the default view.
    assert "3 messages en attente" in re.sub(r"\s+", " ", page.text)
    assert "Messages triés" in page.text
    assert len(collected) == 1 and len(collected[0]) == 3
    assert [request.method for request in fake_google.requests] == ["POST", "GET"]


def test_system_shows_the_connected_mailbox(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """Decision F1, Q11, Q12: ⚙️ Système tells the mailbox and its last collection; « Relever maintenant » from there
    comes back to it."""
    configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    connected(app, client)

    system = client.get("/systeme").text
    collected = client.post("/messages/relever?retour=systeme")

    assert "<dt>camille.dupont@example.com</dt>" in system
    assert "Connectée · dernier relevé le" in system
    assert "3 nouveaux messages" in system
    assert '<form method="post" action="/messages/relever?retour=systeme"' in system
    assert "🔔 Alertes emploi · 7 derniers jours" in system
    assert collected.headers["location"] == "/systeme"


@pytest.mark.parametrize("state", ["", "un-autre-etat"], ids=["missing", "foreign"])
def test_a_return_whose_state_was_not_sent_by_this_browser_is_refused(
    app: FastAPI, migrated_engine: Engine, state: str
) -> None:
    fake_google, _ = configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    to_google(client)

    response = client.get(
        "/messages/gmail/retour", params={"code": "4/code", "state": state}
    )

    assert response.status_code == 400
    assert EXPIRED.replace("'", "&#39;") in response.text
    assert fake_google.requests == []


def test_a_return_without_its_cookie_is_refused(
    app: FastAPI, migrated_engine: Engine
) -> None:
    configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    params = to_google(client)
    client.cookies.delete(STATE_COOKIE, path="/messages/gmail")

    response = client.get(
        "/messages/gmail/retour", params={"code": "4/code", "state": params["state"]}
    )

    assert response.status_code == 400


def test_the_state_of_another_account_is_refused(
    app: FastAPI, migrated_engine: Engine
) -> None:
    configure(app, migrated_engine)
    first, _ = logged_in(app, migrated_engine)
    params = to_google(first)
    cookie = first.cookies.get(STATE_COOKIE)
    second, _ = logged_in(app, migrated_engine)
    assert cookie is not None
    second.cookies.set(STATE_COOKIE, cookie, path="/messages/gmail")

    response = second.get(
        "/messages/gmail/retour", params={"code": "4/code", "state": params["state"]}
    )

    assert response.status_code == 400


def test_a_refusal_at_google_connects_nothing_and_says_so(
    app: FastAPI, migrated_engine: Engine
) -> None:
    configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    params = to_google(client)

    response = client.get(
        "/messages/gmail/retour",
        params={"error": "access_denied", "state": params["state"]},
    )

    assert response.status_code == 400
    assert REFUSED.replace("'", "&#39;") in response.text
    assert "Aucune boîte connectée" in response.text


def test_a_refused_exchange_shows_google_s_reason(
    app: FastAPI, migrated_engine: Engine
) -> None:
    fake_google, _ = configure(app, migrated_engine)
    fake_google.routes[("POST", TOKEN_URL)] = lambda r: json_answer(
        {**recorded("oauth_exchange.json"), "scope": "openid"}
    )
    client, _ = logged_in(app, migrated_engine)
    params = to_google(client)

    response = client.get(
        "/messages/gmail/retour", params={"code": "4/code", "state": params["state"]}
    )

    assert response.status_code == 400
    assert "coche cette autorisation chez Google" in response.text


def test_collect_now_runs_once_and_the_screen_follows_it(
    app: FastAPI, migrated_engine: Engine
) -> None:
    _, gmail = configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    connected(app, client)
    scheduler: Scheduler = app.state.scheduler

    first = client.post("/messages/relever", headers=HTMX)
    client.post("/messages/relever", headers=HTMX)

    assert scheduler.pending() == [scheduler.pending()[0]]
    assert 'hx-trigger="every 3s"' in first.text
    assert "Relevé en cours…" in first.text
    gets = len(gmail.reader_.gets)
    scheduler.tick()
    fragment = client.get("/messages/contenu?vue=tous", headers=HTMX)

    assert 'hx-trigger="every 3s"' not in fragment.text
    assert "0 nouveau message (3 déjà relevés)" in re.sub(r"\s+", " ", fragment.text)
    # The list follows the collection in the same fragment.
    assert "Votre candidature : Data Analyst" in fragment.text
    assert len(gmail.reader_.gets) == gets  # Nothing downloaded again.


def test_while_a_collection_runs_only_the_mailboxes_are_read_again(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """Decision G6, A5: an open « Corriger » panel is no longer wiped every 3 s; the content is read once, at the
    end."""
    configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    connected(app, client)
    scheduler: Scheduler = app.state.scheduler

    asked = client.post("/messages/relever", headers=HTMX)
    running = client.get("/messages/boites", headers=HTMX)
    scheduler.tick()
    ended = client.get("/messages/boites", headers=HTMX)

    assert '<div id="messages-contenu" class="profile-sections">' in asked.text
    assert (
        '<div hidden hx-get="/messages/boites" hx-trigger="every 3s" hx-target="#boites" '
        'hx-swap="outerHTML"></div>'
    ) in asked.text
    assert "Relevé en cours…" in running.text
    assert "HX-Trigger" not in running.headers
    assert '<section id="boites"' in ended.text
    assert ended.headers["HX-Trigger"] == "messages-changed"
    assert client.get("/messages/boites").status_code == 303


def test_the_content_fragment_is_never_a_page(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    response = client.get("/messages/contenu")

    assert response.status_code == 303
    assert response.headers["location"] == "/messages"


def test_a_mailbox_google_withdrew_asks_to_be_reconnected(
    app: FastAPI, migrated_engine: Engine
) -> None:
    configure(
        app, migrated_engine, FakeGmail(refusal=AccessLostError(ACCESS_LOST_REASON))
    )
    client, _ = logged_in(app, migrated_engine)
    connected(app, client)

    page = client.get("/messages")

    assert "À reconnecter" in page.text
    assert ACCESS_LOST_REASON.replace("'", "&#39;") in page.text
    assert "Reconnecter" in page.text
    assert "Relever les messages" not in page.text


def test_disconnecting_revokes_at_google_and_keeps_the_messages(
    app: FastAPI, migrated_engine: Engine
) -> None:
    fake_google, _ = configure(app, migrated_engine)
    client, email = logged_in(app, migrated_engine)
    connected(app, client)
    service: MessagesService = app.state.messages
    state = service.state(account_of(migrated_engine, email))
    mailbox_id = state.mailboxes[0].mailbox.id

    response = client.post(f"/messages/boites/{mailbox_id}/deconnecter")

    assert response.status_code == 303
    assert response.headers["location"] == "/messages?boite=deconnectee"
    assert fake_google.requests[-1].url == REVOKE_URL
    after = service.state(account_of(migrated_engine, email))
    assert after.mailboxes[0].mailbox.status is MailboxStatus.DISCONNECTED
    assert (
        len(service.state(account_of(migrated_engine, email), View.ALL).messages) == 3
    )
    page = client.get("/messages?boite=deconnectee&vue=tous")
    assert "Déconnectée" in page.text
    assert "Votre candidature : Data Analyst" in page.text


def test_a_mailbox_of_another_account_cannot_be_disconnected(
    app: FastAPI, migrated_engine: Engine
) -> None:
    configure(app, migrated_engine)
    owner, email = logged_in(app, migrated_engine)
    connected(app, owner)
    service: MessagesService = app.state.messages
    mailbox_id = (
        service.state(account_of(migrated_engine, email)).mailboxes[0].mailbox.id
    )
    other, _ = logged_in(app, migrated_engine)

    response = other.post(f"/messages/boites/{mailbox_id}/deconnecter")

    assert response.status_code == 404


class TakingScheduler(Scheduler):
    """A planner whose thread already took the task from its queue, before the collection wrote its row."""

    def pending(self) -> list[str]:
        return []


def test_the_screen_follows_a_collection_the_planner_already_took(
    app: FastAPI, migrated_engine: Engine
) -> None:
    configure(app, migrated_engine)
    client, _ = logged_in(app, migrated_engine)
    connected(app, client)
    app.state.scheduler = TakingScheduler(clock=app.state.auth.clock)

    asked = client.post("/messages/relever", headers=HTMX)
    back = client.get("/messages?boite=connectee")
    later = client.get("/messages/contenu", headers=HTMX)

    assert 'hx-trigger="every 3s"' in asked.text
    assert 'hx-trigger="every 3s"' in back.text
    assert 'hx-trigger="every 3s"' not in later.text
