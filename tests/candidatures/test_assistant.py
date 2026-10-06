"""The assistant 🐾 on an offer and an application (decision G4, Q2, Q11, Q15 point 3): the facts it is given, and
nothing written but its call and its turn."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, event

from tests.candidatures.test_web import Desk, desk_with
from tests.offres.fakes import NOW
from tests.system.assistant.fakes import Assistant, citing
from tests.system.web_support import HTMX, make_app, use_model

# What a question may write (Q15, point 3); the session renewed by the authentication is not the assistant's.
ALLOWED_WRITES = re.compile(
    r"^(INSERT INTO (model_calls|assistant_conversations|assistant_turns)\b|UPDATE sessions\b)"
)


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.auth.clock.now = NOW
    return app


@pytest.fixture
def desk(app: FastAPI, migrated_engine: Engine) -> Desk:
    desk = desk_with(app, migrated_engine)
    desk.prepare("target_job")
    return desk


@contextmanager
def statements(engine: Engine) -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def ask(desk: Desk, objet: str, question: str = "Où j'en suis ?") -> str:
    return desk.client.post(
        "/tiroir/question", data={"question": question, "objet": objet}, headers=HTMX
    ).text


def test_the_drawer_of_an_application_gives_its_facts_and_suggestions(
    app: FastAPI, desk: Desk
) -> None:
    application_id = desk.application_id()
    fake = Assistant(citing("Ton dossier est en préparation.", "candidature.etape"))
    use_model(app, fake)

    drawer = desk.client.get(
        f"/tiroir?objet=candidature:{application_id}", headers=HTMX
    ).text
    answer = ask(desk, f"candidature:{application_id}")

    assert "Où j&#39;en suis ?" in drawer
    assert "Ton dossier est en préparation." in answer
    assert f'<a href="/candidatures/{application_id}">Étape</a>' in answer
    prompt = fake.prompts[0]
    assert "[candidature.etape] Étape : En préparation" in prompt
    assert "[candidature.prochaine_action] Prochaine action :" in prompt
    assert f"[compte.candidature_{application_id}] Candidature :" in prompt
    assert "[compte.piste_1] Piste de recherche :" in prompt
    assert "[cockpit.dossiers]" in prompt


def test_the_drawer_of_an_offer_gives_its_score_and_its_reasons(
    app: FastAPI, desk: Desk
) -> None:
    fake = Assistant(
        citing("Ton score vient surtout de tes compétences.", "offre.score")
    )
    use_model(app, fake)

    drawer = desk.client.get(f"/tiroir?objet=offre:{desk.offer_id}", headers=HTMX).text
    answer = ask(desk, f"offre:{desk.offer_id}", "Pourquoi ce score ?")

    assert "Pourquoi ce score ?" in drawer
    assert f'<a href="/offres/{desk.offer_id}/fiche">Score</a>' in answer
    prompt = fake.prompts[0]
    assert "[offre.intitule] Intitulé :" in prompt
    assert "[offre.score] Score :" in prompt
    assert "[offre.score.skills] Score, compétences :" in prompt
    assert "[offre.decision] Ta décision : Intéressé le" in prompt
    assert "[offre.description] Annonce :" in prompt


def test_a_question_writes_only_its_call_and_its_turn(
    app: FastAPI, desk: Desk, migrated_engine: Engine
) -> None:
    """Q15, point 3: the facts are read, never written nor locked; nothing goes to the journal."""
    use_model(app, Assistant(citing("Réponse.", "offre.score", "candidature.etape")))
    application_id = desk.application_id()

    with statements(migrated_engine) as seen:
        desk.client.get(f"/tiroir?objet=offre:{desk.offer_id}", headers=HTMX)
        ask(desk, f"offre:{desk.offer_id}")
        ask(desk, f"candidature:{application_id}")
        ask(desk, "")
        desk.client.post("/tiroir/nouvelle", data={"objet": ""}, headers=HTMX)

    writes = [s for s in seen if not s.upper().startswith(("SELECT", "WITH"))]
    assert writes and all(ALLOWED_WRITES.match(s) for s in writes), writes
    assert not [s for s in seen if "FOR UPDATE" in s.upper()]
    assert any(s.startswith("INSERT INTO assistant_turns") for s in writes)
