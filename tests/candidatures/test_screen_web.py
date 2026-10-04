"""The screen 📝 Candidatures and the step « Suivi » through HTTP (decision D6).

Exit criterion of D6: « Une relance due est retrouvée en moins de 3 clics » — from any page, the navigation opens
« À faire » (click 1), where the follow-up due is listed; its line opens the application on its follow-up (click 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.candidatures.model import NextAction, Stage
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.usecases import change_stage, prepare_application
from rocky.candidatures.web_common import OffresDecisions
from rocky.offres import web as offres_web
from rocky.offres.decisions import application_decision
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import record_offer
from rocky.system.auth.sql import SqlAuthStore
from tests.offres.fakes import DESCRIPTION, NOW, TODAY, equip, posting
from tests.system.web_support import HTMX, logged_in, make_app

OVERDUE = NextAction("Relancer", date(2026, 9, 25))  # TODAY is 29/09/2026


@dataclass(frozen=True)
class Board:
    """An account with three applications: one sent whose follow-up is overdue, one in preparation, one in
    preparation on an offer closing on 30/09/2026."""

    client: TestClient
    sent: int
    preparing: int
    closing: int


def board_with(app: FastAPI, engine: Engine) -> Board:
    client, email = logged_in(app, engine)
    with engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        seeker = equip(connection, account.id, email)
        inputs = scoring_inputs(seeker.profile(connection))

        def opened(external_id: str, description: str = DESCRIPTION) -> int:
            offer_id = record_offer(
                SqlStore(connection),
                account_id=account.id,
                offer=posting(external_id, description=description),
                inputs=inputs,
                origin=Origin.WATCH,
                track_ids=[seeker.tracks["Data"]],
                now=NOW,
                today=TODAY,
            ).offer_id
            deadline = offres_web.offer_deadlines(
                connection, account.id, [offer_id], TODAY
            ).get(offer_id)
            return prepare_application(
                SqlApplicationStore(connection),
                OffresDecisions(connection),
                account_id=account.id,
                offer_id=offer_id,
                interest=application_decision(["target_job"]),
                now=NOW,
                today=TODAY,
                deadline=deadline,
            )

        sent = opened("d6-envoyee")
        change_stage(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=sent,
            stage=Stage.SENT,
            next_action=OVERDUE,
            now=NOW,
        )
        preparing = opened("d6-preparation")
        closing = opened(
            "d6-limite", DESCRIPTION + "\nCandidatures jusqu'au 30 septembre 2026."
        )
    return Board(client, sent, preparing, closing)


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.import_today = lambda: TODAY
    return app


@pytest.fixture
def board(app: FastAPI, migrated_engine: Engine) -> Board:
    return board_with(app, migrated_engine)


def html(board: Board, path: str) -> str:
    response = board.client.get(path)
    assert response.status_code == 200
    return response.text


# Exit criterion of D6.


def test_a_follow_up_due_is_found_in_two_clicks(board: Board) -> None:
    # From any page, the navigation leads to the screen.
    assert 'href="/candidatures"' in html(board, "/offres")

    screen = html(board, "/candidatures")  # click 1

    assert 'aria-current="page">À faire' in screen
    assert "Relancer — 25/09/2026 (en retard)" in screen
    link = f'href="/candidatures/{board.sent}"'
    assert link in screen
    assert (
        f'href="/candidatures/{board.preparing}"' not in screen
    )  # not due: not « À faire »

    dossier = html(board, f"/candidatures/{board.sent}")  # click 2

    assert 'id="suivi"' in dossier  # a sent application opens on its follow-up
    assert "<strong>Relancer</strong> — 25/09/2026 (en retard)" in dossier
    assert "✓ Fait" in dossier


def test_each_tab_counts_its_applications(board: Board) -> None:
    screen = html(board, "/candidatures")

    def count(label: str) -> str:
        start = screen.index(f"{label}\n")
        return screen[start : screen.index("</span>", start)].rsplit(">", 1)[-1]

    assert count("À faire") == "1"
    assert count("En préparation") == "2"
    assert count("Suivi") == "1"
    assert count("Closes") == "0"
    preparing = html(board, "/candidatures?vue=preparation")
    assert f'href="/candidatures/{board.preparing}"' in preparing
    assert f'href="/candidatures/{board.sent}"' not in preparing


def test_fait_from_the_list_proposes_the_next_follow_up(board: Board) -> None:
    done = board.client.post(
        f"/candidatures/{board.sent}/fait", data={"vue": "a-faire"}, headers=HTMX
    ).text

    # Nothing left to do today: the next follow-up is at J+7.
    assert "Rien à faire aujourd'hui." in done
    assert "Prochaine échéance" in done
    dossier = html(board, f"/candidatures/{board.sent}")
    assert "Fait : Relancer ; ensuite : Relancer le 06/10/2026" in dossier

    undone = board.client.post(
        f"/candidatures/{board.sent}/annuler", data={"retour": "suivi"}
    )
    assert undone.headers["location"] == f"/candidatures/{board.sent}?etape=suivi"
    assert "Annulé : « Fait »" in html(board, f"/candidatures/{board.sent}")
    assert "Relancer — 25/09/2026 (en retard)" in html(board, "/candidatures")


def test_fait_comes_after_the_sending(board: Board) -> None:
    refused = board.client.post(
        f"/candidatures/{board.preparing}/fait",
        data={"vue": "preparation"},
        headers=HTMX,
    ).text

    assert "vient après l&#39;envoi" in refused


def test_notes_are_dated_removed_never_rewritten(board: Board) -> None:
    base = f"/candidatures/{board.sent}"

    empty = board.client.post(f"{base}/notes", data={"texte": "  "})
    assert "Écris ta note." in empty.text
    added = board.client.post(f"{base}/notes", data={"texte": "Appel de Julie, RH"})
    assert added.headers["location"] == f"{base}?etape=suivi"
    page = html(board, base)
    assert '<p class="prose">Appel de Julie, RH</p>' in page
    assert "Note : Appel de Julie, RH" in page
    note_id = page.split(f'action="{base}/notes/', 1)[1].split("/", 1)[0]

    removed = board.client.post(f"{base}/notes/{note_id}/retirer")

    assert removed.headers["location"] == f"{base}?etape=suivi"
    page = html(board, base)
    assert '<p class="prose">Appel de Julie, RH</p>' not in page
    assert "Note retirée : « Appel de Julie, RH »" in page
    again = board.client.post(f"{base}/notes/{note_id}/retirer")
    assert "a déjà été retirée" in again.text


def test_the_deadline_bounds_the_proposal_and_shows(board: Board) -> None:
    dossier = html(board, f"/candidatures/{board.closing}")

    assert "Finir le dossier le 30/09/2026" in dossier  # J+2 would be 01/10
    assert "⏰ limite le 30/09/2026" in dossier
    assert "⏰ limite le 30/09" in html(board, "/candidatures?vue=preparation")
    assert "⏰" not in html(board, f"/candidatures/{board.preparing}")


def test_the_language_is_chosen_once_for_the_application(board: Board) -> None:
    base = f"/candidatures/{board.preparing}"

    chosen = board.client.post(
        f"{base}/langue", data={"langue": "en", "etape": "lettre"}
    )

    assert chosen.headers["location"] == f"{base}?etape=lettre"
    page = html(board, f"{base}?etape=suivi")
    assert 'value="en" aria-pressed="true"' in page
    assert "Langue de la candidature : anglais" in page  # a detail of the chronology
    assert board.client.post(f"{base}/langue", data={"langue": "de"}).status_code == 200


def test_the_follow_up_of_another_account_is_not_found(
    app: FastAPI, migrated_engine: Engine, board: Board
) -> None:
    stranger, _ = logged_in(app, migrated_engine)
    base = f"/candidatures/{board.sent}"

    for path, data in (
        ("fait", {}),
        ("notes", {"texte": "x"}),
        ("notes/1/retirer", {}),
        ("langue", {"langue": "en"}),
    ):
        assert stranger.post(f"{base}/{path}", data=data).status_code == 404, path
