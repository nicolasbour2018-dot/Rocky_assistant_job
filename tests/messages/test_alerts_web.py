"""📬 Messages and 🔎 Offres on screen, job alerts (E3, Q5): what an alert gave and why a posting was not read, on the
alert's row; where an offer comes from, on its sheet."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select

from rocky.messages.classification.model import View
from rocky.messages.model import Query
from rocky.messages.service import MessagesService
from rocky.offres.sql import job_offers
from rocky.system.scheduler import Scheduler
from tests.messages.fakes import recorded_alert, store_mail
from tests.messages.test_web import account_of, configure, connected
from tests.offres.fakes import equip
from tests.system.web_support import logged_in, make_app


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.scheduler = Scheduler(clock=app.state.auth.clock)
    return app


def text_of(response_text: str) -> str:
    return re.sub(r"\s+", " ", response_text)


class Screen:
    def __init__(self, app: FastAPI, engine: Engine) -> None:
        configure(app, engine)
        self.client, email = logged_in(app, engine)
        connected(app, self.client)
        self.engine = engine
        self.account_id = account_of(engine, email)
        self.service: MessagesService = app.state.messages
        self.mailbox_id = self.service.state(self.account_id).mailboxes[0].mailbox.id
        with engine.begin() as connection:
            equip(connection, self.account_id, email)

    def alert(self, name: str) -> int:
        data = recorded_alert(name)
        message_id = store_mail(
            self.service.storage,
            self.mailbox_id,
            sender=data["sender"],
            subject=data["subject"],
            body=data["body_text"],
            body_html=data["body_html"],
            found_by=Query.ALERTS,
        )
        self.service.classify(self.account_id, use_model=False)
        return message_id

    def alerts_view(self) -> str:
        response = self.client.get(f"/messages?vue={View.ALERTS.value}")
        assert response.status_code == 200
        return text_of(response.text)


@pytest.fixture
def screen(app: FastAPI, migrated_engine: Engine) -> Screen:
    return Screen(app, migrated_engine)


def test_an_alert_not_read_yet_says_so(screen: Screen) -> None:
    screen.alert("hellowork_alerte")

    assert (
        "Offres pas encore tirées de cette alerte : au plus 10 alertes par jour"
        in screen.alerts_view()
    )


def test_an_alert_shows_its_offers_and_why_their_postings_were_not_read(
    screen: Screen,
) -> None:
    screen.alert("hellowork_alerte")
    screen.service.read_alerts(screen.account_id, links=False)

    page = screen.alerts_view()

    assert "4 offres (4 nouvelles) · 0 fiche lue · 4 non lues" in page
    assert "Data Analyst H/F</a> · Marvesting" in page
    assert "Passage sans lecture des fiches." in page
    with screen.engine.connect() as connection:
        offer_id = connection.execute(
            select(job_offers.c.id).where(
                job_offers.c.account_id == screen.account_id,
                job_offers.c.title == "Data Analyst H/F",
            )
        ).scalar_one()
    assert f'href="/offres/{offer_id}/fiche"' in page


def test_an_alert_of_an_unknown_format_is_shown_with_its_reason(
    screen: Screen,
) -> None:
    store_mail(
        screen.service.storage,
        screen.mailbox_id,
        sender="JobLeads <mailer@jobleads.com>",
        subject="Il y a 3 nouvelles offres d’emploi correspondant à votre recherche",
        found_by=Query.ALERTS,
    )
    screen.service.classify(screen.account_id, use_model=False)
    screen.service.read_alerts(screen.account_id, links=False)

    page = screen.alerts_view()

    assert "Format d&#39;alerte non lu" in page
    assert "mailer@jobleads.com" in page


def test_the_sheet_of_an_offer_says_it_comes_from_an_alert(screen: Screen) -> None:
    screen.alert("hellowork_alerte")
    screen.service.read_alerts(screen.account_id, links=False)
    with screen.engine.connect() as connection:
        offer_id = connection.execute(
            select(job_offers.c.id).where(
                job_offers.c.account_id == screen.account_id,
                job_offers.c.title == "Data Analyst H/F",
            )
        ).scalar_one()

    response = screen.client.get(f"/offres/{offer_id}/fiche")

    page = text_of(response.text)
    assert response.status_code == 200
    assert "Tirée d&#39;une alerte Hellowork" in page
    assert "Tirée d&#39;une alerte Hellowork. Passage sans lecture des fiches." in page
