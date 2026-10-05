"""📬 Messages on screen, decisions (E4): « Ce qui a bougé » and its counter in the navigation (Q5), « Appliquer »,
« Vu », « Juste », « Corriger », « Créer la candidature » (Q4, Q6, Q7), the messages of a dossier (Q8)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from rocky.candidatures.model import Stage
from rocky.candidatures.rules import dossier
from rocky.candidatures.sql import SqlApplicationStore
from rocky.messages.service import MessagesService
from rocky.system.scheduler import Scheduler
from tests.messages.fakes import sent_application, store_mail
from tests.messages.test_web import account_of, configure, connected
from tests.offres.fakes import equip
from tests.system.web_support import logged_in, make_app

HTMX = {"HX-Request": "true"}
REFUSAL = (
    "Après une étude approfondie, nous ne donnerons pas suite à votre candidature."
)


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
            seeker = equip(connection, self.account_id, email)
            self.application_id = sent_application(
                connection,
                seeker,
                company="French bee",
                title="Data Analyst - Data Steward H/F",
            )

    def mail(self, sender: str, subject: str, body: str = "") -> int:
        message_id = store_mail(
            self.service.storage,
            self.mailbox_id,
            sender=sender,
            subject=subject,
            body=body,
        )
        self.service.classify(self.account_id, use_model=False)
        return message_id

    def refusal(self) -> int:
        """A refusal through an ATS, by the employer's name and the offer's title: confidence medium, proposed."""
        return self.mail(
            "Recrutment department - French Bee <message@beetween-software.com>",
            "French Bee - RETOUR CANDIDATURE AU POSTE DE Data Analyst - Data Steward H/F",
            REFUSAL,
        )

    def moved_ids(self) -> list[int]:
        return [
            line.transition.id for line in self.service.state(self.account_id).moved
        ]

    def stage(self, application_id: int | None = None) -> Stage | None:
        with self.engine.connect() as connection:
            changes = SqlApplicationStore(connection).changes(
                application_id or self.application_id
            )
        return dossier(changes).stage


@pytest.fixture
def screen(app: FastAPI, migrated_engine: Engine) -> Screen:
    return Screen(app, migrated_engine)


def test_what_moved_is_on_top_with_its_counter_in_the_navigation(
    screen: Screen,
) -> None:
    screen.refusal()

    page = text_of(screen.client.get("/messages").text)
    elsewhere = text_of(screen.client.get("/candidatures").text)

    assert "Ce qui a bougé" in page
    assert "Envoyée → Refusée" in page and "proposé" in page
    assert "Appliquer" in page and "Ignorer" in page
    assert 'id="nav-count-messages" class="nav-count" title="1 à traiter">1<' in page
    assert (
        'id="tab-count-messages" class="nav-count" title="1 à traiter">1<' in elsewhere
    )


def test_applying_a_proposal_moves_the_application_and_empties_the_block(
    screen: Screen,
) -> None:
    screen.refusal()
    transition_id = screen.moved_ids()[0]

    response = screen.client.post(
        f"/messages/mouvements/{transition_id}/appliquer", headers=HTMX
    )

    assert response.status_code == 200
    assert "Étape de la candidature changée." in response.text
    assert "Ce qui a bougé" not in response.text
    assert screen.stage() is Stage.REJECTED
    # The counter of the navigation follows, out of band, and is hidden at 0.
    assert (
        'id="nav-count-messages" class="nav-count" title="0 à traiter" hx-swap-oob="true" hidden>'
        in (response.text)
    )
    assert 'id="nav-count-messages" class="nav-count" title="0 à traiter" hidden>' in (
        screen.client.get("/messages").text
    )


def test_a_gesture_without_htmx_goes_back_to_the_page(screen: Screen) -> None:
    screen.refusal()

    response = screen.client.post(
        f"/messages/mouvements/{screen.moved_ids()[0]}/ignorer", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/messages"
    assert screen.stage() is Stage.SENT


def test_a_gesture_refused_says_why(screen: Screen) -> None:
    screen.refusal()
    transition_id = screen.moved_ids()[0]
    screen.client.post(f"/messages/mouvements/{transition_id}/ignorer", headers=HTMX)

    again = screen.client.post(f"/messages/mouvements/{transition_id}/vu", headers=HTMX)
    unknown = screen.client.post(
        f"/messages/mouvements/{transition_id}/effacer", headers=HTMX
    )

    assert again.status_code == 400
    assert "Ce changement n&#39;est plus à traiter." in again.text
    assert unknown.status_code == 404


def test_correcting_a_message_from_its_panel(screen: Screen) -> None:
    message_id = screen.mail(
        "Léa Martin via LinkedIn <messages-noreply@linkedin.com>",
        "Léa vous a envoyé un message",
        "Bonjour Camille, un poste de data analyst ?",
    )

    panel = text_of(
        screen.client.get(
            f"/messages/{message_id}/corriger",
            headers={**HTMX, "HX-Target": f"panneau-{message_id}"},
        ).text
    )
    saved = text_of(
        screen.client.post(
            f"/messages/{message_id}/corriger",
            data={
                "categorie": "recruiter_approach",
                "candidature": "",
                "toujours": "1",
            },
            headers=HTMX,
        ).text
    )

    assert "Approche d&#39;un recruteur" in panel
    assert "Toujours pour messages-noreply@linkedin.com" in panel
    assert "Créer la candidature…" in panel and 'hx-target="#panneau-' in panel
    assert "Correction enregistrée." in saved
    assert (
        "Règle ajoutée : messages-noreply@linkedin.com → Approche d&#39;un recruteur."
        in saved
    )
    assert "Tes règles de tri (1)" in saved
    assert "par toi" in saved


def test_a_panel_without_htmx_goes_back_to_the_page(screen: Screen) -> None:
    message_id = screen.refusal()

    response = screen.client.get(
        f"/messages/{message_id}/corriger", follow_redirects=False
    )

    assert response.status_code == 303


def test_confirming_a_decision(screen: Screen) -> None:
    message_id = screen.refusal()

    response = screen.client.post(f"/messages/{message_id}/juste", headers=HTMX)

    assert "Merci : classement confirmé." in response.text
    assert screen.service.labels(screen.account_id)[0].gesture == "user.confirmed"


def test_creating_an_application_from_a_message(screen: Screen) -> None:
    message_id = screen.mail(
        "Hellowork <emploi@emails.hellowork.com>",
        "Votre candidature est arrivée chez ATHEIA",
    )
    listed = screen.client.get("/messages?vue=accuses").text

    panel = screen.client.get(f"/messages/{message_id}/creer", headers=HTMX).text
    created = text_of(
        screen.client.post(
            f"/messages/{message_id}/creer",
            data={"employeur": "ATHEIA", "intitule": "Data Analyst", "lien": ""},
            headers={
                **HTMX,
                "HX-Current-URL": "http://testserver/messages?vue=accuses",
            },
        ).text
    )
    bad_link = screen.client.post(
        f"/messages/{message_id}/creer",
        data={"employeur": "ATHEIA", "intitule": "Data Analyst", "lien": "pas un lien"},
        headers=HTMX,
    )

    # The platform names an employer without application: « Créer la candidature » is offered on the line.
    assert f'hx-post="/messages/{message_id}/creer-en-un-clic"' in listed
    assert 'value="ATHEIA"' in panel
    # The gesture keeps the view the page shows.
    assert 'href="/messages?vue=accuses" aria-current="page"' in created
    assert "Candidature chez ATHEIA créée, à l&#39;étape « Envoyée »." in created
    found = re.search(r'href="/candidatures/(\d+)">Ouvrir le dossier', created)
    assert found is not None
    assert screen.stage(int(found.group(1))) is Stage.SENT
    assert bad_link.status_code == 400


def test_the_dossier_loads_its_messages(screen: Screen) -> None:
    screen.refusal()

    follow = screen.client.get(
        f"/candidatures/{screen.application_id}?etape=suivi"
    ).text
    block = screen.client.get(
        f"/messages/candidature/{screen.application_id}", headers=HTMX
    ).text
    direct = screen.client.get(
        f"/messages/candidature/{screen.application_id}", follow_redirects=False
    )

    assert f'hx-get="/messages/candidature/{screen.application_id}"' in follow
    assert "RETOUR CANDIDATURE" in block and "Refus" in block
    assert direct.status_code == 303


def test_another_accounts_message_is_not_found(
    screen: Screen, app: FastAPI, migrated_engine: Engine
) -> None:
    message_id = screen.refusal()
    other, _ = logged_in(app, migrated_engine)

    panel = other.get(f"/messages/{message_id}/corriger", headers=HTMX)
    corrected = other.post(
        f"/messages/{message_id}/corriger",
        data={"categorie": "unrelated", "candidature": ""},
        headers=HTMX,
    )

    assert panel.status_code == 404
    assert corrected.status_code == 404
    assert screen.service.labels(screen.account_id) == []


def test_an_application_is_created_in_one_click(screen: Screen) -> None:
    """Q13: the employer cited and the title the platform writes; the link is the message's."""
    message_id = screen.mail(
        "Hellowork <contact@emails.hellowork.com>",
        "Votre candidature est arrivée chez GEODIS",
        'Votre candidature est enregistrée.\n"Finance Bi & Data Analyst H/F" pour l\'entreprise GEODIS.',
    )

    created = text_of(
        screen.client.post(
            f"/messages/{message_id}/creer-en-un-clic", headers=HTMX
        ).text
    )

    assert (
        "Candidature « Finance Bi &amp; Data Analyst H/F » chez GEODIS créée" in created
    )
    found = re.search(r'href="/candidatures/(\d+)">Ouvrir le dossier', created)
    assert found is not None
    assert screen.stage(int(found.group(1))) is Stage.SENT
    assert "nav-count" in created


def test_without_a_readable_title_the_form_opens_prefilled(screen: Screen) -> None:
    message_id = screen.mail(
        "Hellowork <contact@emails.hellowork.com>",
        "Votre candidature est arrivée chez GEODIS",
        "Bonjour, à bientôt.",
    )

    response = screen.client.post(
        f"/messages/{message_id}/creer-en-un-clic", headers=HTMX
    )

    assert response.status_code == 200
    assert response.headers["HX-Retarget"] == f"#panneau-{message_id}"
    assert response.headers["HX-Reswap"] == "innerHTML"
    assert "pas pu lire l&#39;intitulé du poste" in response.text
    assert 'value="GEODIS"' in response.text
    assert screen.service.state(screen.account_id).moved == ()
