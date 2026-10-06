"""Applications through HTTP (D1): the box of an offer's sheet, the reasons of « Préparer », the plain list."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.candidatures.rules import dossier
from rocky.candidatures.sql import SqlApplicationStore
from rocky.offres import web as offres_web
from rocky.offres.decisions import APPLICATION_STARTED, Decision, DecisionValue
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import record_decision, record_offer
from rocky.system.auth.sql import SqlAuthStore
from tests.offres.fakes import NOW, TODAY, Seeker, equip, posting
from tests.system.web_support import HTMX, logged_in, make_app


@dataclass(frozen=True)
class Desk:
    client: TestClient
    seeker: Seeker
    engine: Engine
    offer_id: int

    def decision(self) -> DecisionValue | None:
        with self.engine.connect() as connection:
            return offres_web.decision_in_force(
                connection, self.seeker.account_id, self.offer_id
            )

    def reasons(self) -> tuple[str, ...]:
        with self.engine.connect() as connection:
            rows = SqlStore(connection).decision_rows(
                self.seeker.account_id, self.offer_id
            )
        decision = rows[-1].decision
        assert decision is not None
        return decision.reasons

    def application_id(self) -> int:
        with self.engine.connect() as connection:
            application = SqlApplicationStore(connection).application_of_offer(
                self.seeker.account_id, self.offer_id
            )
        assert application is not None
        return application.id

    def prepare(self, *reasons: str, note: str = "") -> str:
        response = self.client.post(
            f"/candidatures/offre/{self.offer_id}/preparer",
            data={"motifs": list(reasons), "precision": note},
            headers=HTMX,
        )
        assert response.status_code == 200
        return response.text

    def post(self, path: str, **data: str) -> str:
        response = self.client.post(
            f"/candidatures/{self.application_id()}/{path}", data=data, headers=HTMX
        )
        assert response.status_code == 200
        return response.text


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.import_today = lambda: TODAY
    return app


def desk_with(app: FastAPI, engine: Engine, decision: Decision | None = None) -> Desk:
    client, email = logged_in(app, engine)
    with engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        seeker = equip(connection, account.id, email)
        store = SqlStore(connection)
        offer_id = record_offer(
            store,
            account_id=account.id,
            offer=posting("d1"),
            inputs=scoring_inputs(seeker.profile(connection)),
            origin=Origin.WATCH,
            track_ids=[seeker.tracks["Data"]],
            now=NOW,
            today=TODAY,
        ).offer_id
        if decision is not None:
            record_decision(
                store,
                account_id=account.id,
                offer_id=offer_id,
                decision=decision,
                track_id=None,
                now=NOW,
            )
    return Desk(client, seeker, engine, offer_id)


@pytest.fixture
def desk(app: FastAPI, migrated_engine: Engine) -> Desk:
    return desk_with(app, migrated_engine)


def test_the_sheet_of_an_offer_loads_its_application_box(desk: Desk) -> None:
    sheet = desk.client.get(f"/offres/{desk.offer_id}/fiche", headers=HTMX).text
    assert f'hx-get="/candidatures/offre/{desk.offer_id}"' in sheet

    box = desk.client.get(f"/candidatures/offre/{desk.offer_id}", headers=HTMX).text
    assert "Préparer la candidature" in box
    assert f'hx-get="/candidatures/offre/{desk.offer_id}/preparer"' in box


def test_preparing_asks_the_reasons_of_interested(desk: Desk) -> None:
    panel = desk.client.get(
        f"/candidatures/offre/{desk.offer_id}/preparer", headers=HTMX
    ).text

    assert 'value="target_job"' in panel
    assert APPLICATION_STARTED not in panel
    assert "Choisis au moins un motif" in desk.prepare()
    assert desk.decision() is None


def test_preparing_opens_the_application_and_lands_on_it(desk: Desk) -> None:
    response = desk.client.post(
        f"/candidatures/offre/{desk.offer_id}/preparer",
        data={"motifs": ["target_job"]},
        headers=HTMX,
    )

    application = f"/candidatures/{desk.application_id()}"
    assert response.headers["HX-Redirect"] == application
    page = desk.client.get(application).text
    assert '<span class="badge badge-accent">En préparation</span>' in page
    assert "Finir le dossier le 01/10/2026" in page
    box = desk.client.get(f"/candidatures/offre/{desk.offer_id}", headers=HTMX).text
    assert "Candidature : <strong>En préparation</strong>" in box
    assert desk.decision() is DecisionValue.INTERESTED
    assert desk.reasons() == (APPLICATION_STARTED, "target_job")


def test_an_interested_offer_opens_its_application_without_reasons(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(
        app, migrated_engine, Decision(DecisionValue.INTERESTED, ("salary",))
    )
    box = desk.client.get(f"/candidatures/offre/{desk.offer_id}", headers=HTMX).text
    assert f'hx-post="/candidatures/offre/{desk.offer_id}/preparer"' in box

    desk.prepare()
    assert (
        "En préparation"
        in desk.client.get(f"/candidatures/{desk.application_id()}").text
    )
    assert desk.reasons() == ("salary",)


def test_an_interested_offer_without_application_is_to_prepare_in_one_click(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(
        app, migrated_engine, Decision(DecisionValue.INTERESTED, ("salary",))
    )
    to_prepare = "/candidatures?vue=a-preparer"
    listed = desk.client.get(to_prepare).text
    assert f'id="a-preparer-{desk.offer_id}"' in listed
    assert f'action="/candidatures/offre/{desk.offer_id}/preparer"' in listed

    opened = desk.client.post(f"/candidatures/offre/{desk.offer_id}/preparer")

    assert opened.headers["location"] == f"/candidatures/{desk.application_id()}"
    assert f'id="a-preparer-{desk.offer_id}"' not in desk.client.get(to_prepare).text
    preparing = desk.client.get("/candidatures?vue=preparation").text
    assert f'href="/candidatures/{desk.application_id()}"' in preparing


def test_an_offer_put_aside_is_not_to_prepare(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(app, migrated_engine, Decision(DecisionValue.LATER, ("reread",)))

    listed = desk.client.get("/candidatures?vue=a-preparer").text
    assert f'id="a-preparer-{desk.offer_id}"' not in listed


def test_a_rejected_offer_cannot_be_prepared(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(
        app, migrated_engine, Decision(DecisionValue.REJECTED, ("too_senior",))
    )
    box = desk.client.get(f"/candidatures/offre/{desk.offer_id}", headers=HTMX).text
    assert "Offre écartée" in box

    assert "change d&#39;abord ta décision" in desk.prepare("target_job")
    assert desk.decision() is DecisionValue.REJECTED


def test_the_list_follows_the_stages_and_the_next_action(desk: Desk) -> None:
    empty = desk.client.get("/candidatures").text
    assert (
        "Rien à faire aujourd&#39;hui." in empty or "Rien à faire aujourd'hui." in empty
    )
    desk.prepare("target_job")

    listed = desk.client.get("/candidatures?vue=preparation").text
    assert "Data analyst (H/F)" in listed
    assert "Finir le dossier — 01/10/2026" in listed
    # Nothing due today: « À faire » names the next deadline (decision D6, Q1).
    assert "Prochaine échéance" in desk.client.get("/candidatures").text

    # « Envoyée » is confirmed with its date, channel and documents (decision D5, Q5): the list leads to the form.
    to_confirm = desk.client.post(
        f"/candidatures/{desk.application_id()}/etape",
        data={"etape": "sent"},
        headers=HTMX,
    )
    assert to_confirm.headers["HX-Redirect"] == (
        f"/candidatures/{desk.application_id()}/envoi"
    )

    sent = desk.post("etape", etape="in_discussion", vue="suivi")
    assert "Relancer — 06/10/2026" in sent
    assert 'aria-current="page">Suivi' in sent  # the gesture keeps its tab

    deferred = desk.post("differer", jours="3", vue="suivi")
    assert "Relancer — 09/10/2026" in deferred

    edited = desk.post(
        "action", action="Appeler la recruteuse", echeance="2026-10-02", vue="suivi"
    )
    assert "Appeler la recruteuse — 02/10/2026" in edited

    cleared = desk.post("action", action="", echeance="", vue="suivi")
    assert "Aucune" in cleared


def test_an_interview_asks_its_date(desk: Desk) -> None:
    desk.prepare("target_job")

    asked = desk.post("etape", etape="interview", vue="preparation")
    assert 'name="saisie"' in asked
    assert 'value="Préparer l&#39;entretien"' in asked

    missing = desk.post(
        "etape",
        etape="interview",
        saisie="1",
        action="Préparer l'entretien",
        vue="preparation",
    )
    assert "Indique la date" in missing

    done = desk.post(
        "etape",
        etape="interview",
        saisie="1",
        action="Préparer l'entretien",
        echeance="2026-10-03",
        vue="suivi",
    )
    assert "Préparer l&#39;entretien — 03/10/2026" in done


def test_annuler_undoes_the_changes_then_the_application_and_its_decision(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(app, migrated_engine, Decision(DecisionValue.LATER, ("reread",)))
    desk.prepare("target_job")
    desk.post("etape", etape="ready")

    back = desk.post("annuler", vue="preparation")
    assert "Finir le dossier" in back
    assert desk.decision() is DecisionValue.INTERESTED

    gone = desk.post("annuler")
    assert "Un dossier s'ouvre depuis une offre" in gone
    assert desk.decision() is DecisionValue.LATER
    with migrated_engine.connect() as connection:
        changes = SqlApplicationStore(connection).changes(desk.application_id())
    assert not dossier(changes).open


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("etape", {"etape": "ready"}),
        ("action", {"action": "Relancer", "echeance": "2026-10-20"}),
    ],
)
def test_a_change_to_a_cancelled_application_says_why(
    desk: Desk, path: str, data: dict[str, str]
) -> None:
    """Step H1: the refusal of a cancelled application was a 500."""
    desk.prepare("target_job")
    desk.post("annuler")

    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/{path}", data=data, headers=HTMX
    )

    assert response.status_code == 200
    assert response.headers["HX-Retarget"] == "#erreur"
    assert "Cette candidature a été annulée." in response.text


def test_without_htmx_preparing_goes_to_the_application_and_changes_to_the_list(
    desk: Desk,
) -> None:
    response = desk.client.post(
        f"/candidatures/offre/{desk.offer_id}/preparer",
        data={"motifs": ["target_job"]},
    )
    assert (response.status_code, response.headers["location"]) == (
        303,
        f"/candidatures/{desk.application_id()}",
    )

    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/etape", data={"etape": "ready"}
    )
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/candidatures",
    )
    page = desk.client.get("/candidatures?vue=pretes")
    assert "Envoyer la candidature" in page.text
    assert "<title>Candidatures · Rocky</title>" in page.text


def test_another_account_sees_nothing(
    app: FastAPI, migrated_engine: Engine, desk: Desk
) -> None:
    desk.prepare("target_job")
    application_id = desk.application_id()
    stranger, _ = logged_in(app, migrated_engine)

    assert stranger.get(f"/candidatures/offre/{desk.offer_id}").status_code == 404
    assert (
        stranger.post(
            f"/candidatures/offre/{desk.offer_id}/preparer",
            data={"motifs": ["target_job"]},
        ).status_code
        == 404
    )
    for path, data in (
        ("etape", {"etape": "sent"}),
        ("action", {"action": "", "echeance": ""}),
        ("differer", {"jours": "1"}),
        ("annuler", {}),
    ):
        response = stranger.post(f"/candidatures/{application_id}/{path}", data=data)
        assert response.status_code == 404, path
    assert "Data analyst" not in stranger.get("/candidatures?vue=preparation").text


def test_an_unknown_stage_is_refused(desk: Desk) -> None:
    desk.prepare("target_job")

    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/etape",
        data={"etape": "hired"},
        headers=HTMX,
    )
    assert response.status_code == 404


def test_the_triage_prepares_the_application_of_an_interesting_offer(
    desk: Desk,
) -> None:
    """« Intéressé et préparer » from the triage (decision D6, Q8): the reasons chosen go with the application."""
    panel = desk.client.get(
        f"/offres/{desk.offer_id}/motifs?decision=interested&contexte=tri",
        headers=HTMX,
    ).text
    assert 'data-key="d"' in panel
    assert f'formaction="/candidatures/offre/{desk.offer_id}/preparer"' in panel
    sheet = desk.client.get(
        f"/offres/{desk.offer_id}/motifs?decision=interested&contexte=fiche",
        headers=HTMX,
    ).text
    assert 'data-key="d"' not in sheet  # the sheet has its own box « Préparer »

    refused = desk.client.post(
        f"/candidatures/offre/{desk.offer_id}/preparer",
        data={"contexte": "tri", "decision": "interested"},
        headers=HTMX,
    ).text
    assert "Choisis au moins un motif" in refused
    assert 'hx-target="#decision-area"' in refused  # back in the triage, not the sheet
    assert desk.decision() is None

    prepared = desk.client.post(
        f"/candidatures/offre/{desk.offer_id}/preparer",
        data={"contexte": "tri", "decision": "interested", "motifs": ["skills_match"]},
        headers=HTMX,
    )

    assert prepared.headers["HX-Redirect"] == f"/candidatures/{desk.application_id()}"
    assert desk.decision() is DecisionValue.INTERESTED
    assert desk.reasons() == (APPLICATION_STARTED, "skills_match")
