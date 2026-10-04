"""📬 « Messages triés » on screen (decision E2, Q14): the collection's hook classifies, the views filter,
« Pourquoi ? » shows the proof, the messages waiting say why; no correction, no stage changed (E4)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from rocky.candidatures.sql import application_changes
from rocky.messages.classification.usecases import NOT_CONFIGURED_REASON
from rocky.messages.service import MessagesService
from rocky.system.scheduler import Scheduler
from tests.messages.fakes import NOW, ScriptedModel, sent_application, store_mail
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


def collected_client(app: FastAPI, engine: Engine) -> tuple[TestClient, int]:
    """A mailbox connected and collected: the hook of the screen classified its three messages (rules only)."""
    configure(app, engine)
    client, email = logged_in(app, engine)
    connected(app, client)
    return client, account_of(engine, email)


def test_the_collection_is_followed_by_the_classification(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = collected_client(app, migrated_engine)

    default = text_of(client.get("/messages").text)
    alerts = text_of(client.get("/messages?vue=alertes").text)
    everything = text_of(client.get("/messages?vue=tous").text)

    # The recruiter's reply: an acknowledgement (« Merci pour votre candidature »), shown by default.
    assert "Votre candidature : Data Analyst" in default
    assert "Accusé de réception" in default
    assert "Pourquoi ?" in default and "Phrase explicite" in default
    assert "3 nouvelles offres pour Data analyst" not in default
    # Indeed's alert address: in « Alertes » only.
    assert "3 nouvelles offres pour Data analyst" in alerts
    assert "Adresse qui n&#39;envoie que des alertes emploi." in alerts
    assert "Votre candidature : Data Analyst" not in alerts
    assert everything.count("Pourquoi ?") == 3
    assert "en attente de classement" not in everything


def test_a_message_the_rules_leave_waits_for_the_model_and_says_why(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = collected_client(app, migrated_engine)
    service: MessagesService = app.state.messages
    mailbox_id = service.state(account_id).mailboxes[0].mailbox.id
    store_mail(
        service.storage,
        mailbox_id,
        sender="Thales Group <recruiting@jobalerts.thalesgroup.com>",
        subject="Application Update",
        body="Hello Camille, a quick update regarding your application.",
    )
    service.classify(account_id)

    waiting = text_of(client.get("/messages?vue=en-attente").text)
    default = text_of(client.get("/messages").text)

    assert "1 message en attente de classement." in default
    assert NOT_CONFIGURED_REASON.replace("'", "&#39;") in default
    assert "Application Update" in waiting and "En attente" in waiting


def test_a_decision_links_its_application_and_changes_no_stage(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, account_id = collected_client(app, migrated_engine)
    service: MessagesService = app.state.messages
    with migrated_engine.begin() as connection:
        seeker = equip(connection, account_id, "camille@example.fr")
        application_id = sent_application(
            connection,
            seeker,
            company="French bee",
            title="Data Analyst - Data Steward H/F",
        )
        changes = connection.execute(
            select(func.count()).select_from(application_changes)
        ).scalar_one()
    mailbox_id = service.state(account_id).mailboxes[0].mailbox.id
    store_mail(
        service.storage,
        mailbox_id,
        sender="Recrutment department - French Bee <message@beetween-software.com>",
        subject="French Bee - RETOUR CANDIDATURE AU POSTE DE Data Analyst - Data Steward H/F",
        body="Après une étude approfondie, nous ne donnerons pas suite à votre candidature.",
    )
    service.classify(account_id)

    page = text_of(client.get("/messages").text)

    assert "Refus" in page
    assert f'href="/candidatures/{application_id}"' in page
    assert "French bee — Data Analyst - Data Steward H/F" in page
    assert "Confiance moyenne" in page
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(application_changes)
            ).scalar_one()
            == changes
        )


def test_a_decision_of_the_model_says_so(app: FastAPI, migrated_engine: Engine) -> None:
    client, account_id = collected_client(app, migrated_engine)
    service: MessagesService = app.state.messages
    service.model = ScriptedModel(
        {
            "categorie": "employer_update",
            "candidature": "",
            "extrait": "a quick update regarding your application",
            "raison": "Point d'étape du recruteur.",
        }
    )
    mailbox_id = service.state(account_id).mailboxes[0].mailbox.id
    store_mail(
        service.storage,
        mailbox_id,
        sender="Thales Group <recruiting@jobalerts.thalesgroup.com>",
        subject="Application Update",
        body="Hello Camille, a quick update regarding your application.",
        received_at=NOW,
    )
    service.classify(account_id)

    page = text_of(client.get("/messages?vue=retours").text)

    assert "Message de l&#39;employeur" in page
    assert "Modèle de langage" in page
    assert "Point d&#39;étape du recruteur." in page


def test_an_unknown_view_is_the_default_one(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = collected_client(app, migrated_engine)

    page = client.get("/messages?vue=inconnue")

    assert page.status_code == 200
    assert 'aria-current="page">À regarder' in page.text
