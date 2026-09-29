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


def test_preparing_opens_the_application_and_records_interested(desk: Desk) -> None:
    response = desk.client.post(
        f"/candidatures/offre/{desk.offer_id}/preparer",
        data={"motifs": ["target_job"]},
        headers=HTMX,
    )

    assert "Candidature : <strong>En préparation</strong>" in response.text
    assert "Finir le dossier le 01/10/2026" in response.text
    assert response.headers["HX-Trigger"] == "offers-changed"
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

    assert "En préparation" in desk.prepare()
    assert desk.reasons() == ("salary",)


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
    assert "Aucune candidature en cours" in empty
    desk.prepare("target_job")

    listed = desk.client.get("/candidatures").text
    assert "Data analyst (H/F)" in listed
    assert "Finir le dossier — 01/10/2026" in listed

    sent = desk.post("etape", etape="sent")
    assert "Relancer — 06/10/2026" in sent

    deferred = desk.post("differer", jours="3")
    assert "Relancer — 09/10/2026" in deferred

    edited = desk.post("action", action="Appeler la recruteuse", echeance="2026-10-02")
    assert "Appeler la recruteuse — 02/10/2026" in edited

    cleared = desk.post("action", action="", echeance="")
    assert "Aucune" in cleared


def test_an_interview_asks_its_date(desk: Desk) -> None:
    desk.prepare("target_job")

    asked = desk.post("etape", etape="interview")
    assert 'name="saisie"' in asked
    assert 'value="Préparer l&#39;entretien"' in asked

    missing = desk.post(
        "etape", etape="interview", saisie="1", action="Préparer l'entretien"
    )
    assert "Indique la date" in missing

    done = desk.post(
        "etape",
        etape="interview",
        saisie="1",
        action="Préparer l'entretien",
        echeance="2026-10-03",
    )
    assert "Préparer l&#39;entretien — 03/10/2026" in done


def test_annuler_undoes_the_changes_then_the_application_and_its_decision(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(app, migrated_engine, Decision(DecisionValue.LATER, ("reread",)))
    desk.prepare("target_job")
    desk.post("etape", etape="sent")

    back = desk.post("annuler")
    assert "Finir le dossier" in back
    assert desk.decision() is DecisionValue.INTERESTED

    gone = desk.post("annuler")
    assert "Aucune candidature en cours" in gone
    assert desk.decision() is DecisionValue.LATER
    with migrated_engine.connect() as connection:
        changes = SqlApplicationStore(connection).changes(desk.application_id())
    assert not dossier(changes).open


def test_without_htmx_changes_redirect_to_the_list(desk: Desk) -> None:
    response = desk.client.post(
        f"/candidatures/offre/{desk.offer_id}/preparer",
        data={"motifs": ["target_job"]},
    )
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/candidatures",
    )

    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/etape", data={"etape": "ready"}
    )
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/candidatures",
    )
    page = desk.client.get("/candidatures")
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
    assert "Aucune candidature en cours" in stranger.get("/candidatures").text


def test_an_unknown_stage_is_refused(desk: Desk) -> None:
    desk.prepare("target_job")

    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/etape",
        data={"etape": "hired"},
        headers=HTMX,
    )
    assert response.status_code == 404
