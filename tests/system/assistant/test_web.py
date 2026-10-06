"""The drawer 🐾 is the assistant (decision G4): the conversation read when it opens, a question at a time."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from rocky.system.llm import LlmUnavailableError
from tests.system.assistant.fakes import Assistant, citing
from tests.system.web_support import HTMX, logged_in, make_app, use_model

ANSWER = citing("Tu as 0 offre à examiner.", "cockpit.offres")


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    return make_app(migrated_engine)


def ask(client: TestClient, question: str, objet: str = "") -> str:
    return client.post(
        "/tiroir/question", data={"question": question, "objet": objet}, headers=HTMX
    ).text


def test_the_layout_holds_the_drawer_and_its_question(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    page = client.get("/candidatures").text

    assert 'id="rocky-drawer" class="drawer" popover="manual"' in page
    assert 'hx-get="/tiroir"' in page
    assert "hx-include=\"[form='rocky-question'][name='objet']\"" in page
    assert '<form id="rocky-question"' in page
    assert 'data-key="Escape">Fermer</button>' in page
    assert "Rocky réfléchit…" in page
    # « À faire ici » is gone (Q6).
    assert "/tiroir?ecran" not in page


def test_the_general_conversation_suggests_and_counts_the_questions_left(
    app: FastAPI, migrated_engine: Engine
) -> None:
    use_model(app, Assistant(ANSWER))
    client, _ = logged_in(app, migrated_engine)

    drawer = client.get("/tiroir", headers=HTMX).text

    assert "Conversation générale" in drawer
    assert "Par quoi je commence aujourd&#39;hui ?" in drawer
    assert "Il te reste 5 questions aujourd'hui." in drawer
    assert "<html" not in drawer
    assert 'class="sidebar"' in client.get("/tiroir").text


def test_a_question_is_answered_with_the_facts_it_cites(
    app: FastAPI, migrated_engine: Engine
) -> None:
    fake = Assistant(ANSWER)
    use_model(app, fake)
    client, _ = logged_in(app, migrated_engine)

    drawer = ask(client, "Par quoi je commence ?")

    assert "Tu as 0 offre à examiner." in drawer
    assert "D'après :" in drawer and ">Offres à examiner</a>" in drawer
    assert "Il te reste 4 questions aujourd'hui." in drawer
    assert 'id="rocky-question-text"' in drawer and 'hx-swap-oob="true"' in drawer
    assert "[cockpit.offres] Offres à examiner" in fake.prompts[0]
    # The conversation is kept: the drawer opened again shows it.
    assert "Tu as 0 offre à examiner." in client.get("/tiroir", headers=HTMX).text


def test_the_sixth_question_meets_the_limit_and_keeps_what_was_typed(
    app: FastAPI, migrated_engine: Engine
) -> None:
    use_model(app, Assistant(ANSWER))
    client, _ = logged_in(app, migrated_engine)

    for _ in range(5):
        ask(client, "Par quoi je commence ?")
    sixth = ask(client, "Et ensuite ?")

    assert "plafond du jour atteint, il revient demain" in sixth
    assert "Plus de question aujourd'hui." in sixth
    assert 'hx-swap-oob="true"' not in sixth


def test_a_failure_or_a_missing_key_says_so(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    without_key = client.get("/tiroir", headers=HTMX).text
    use_model(app, Assistant(LlmUnavailableError("Gemini est en panne (HTTP 503).")))
    failed = ask(client, "Par quoi je commence ?")

    assert (
        "Assistant indisponible : Le modèle de langage n&#39;est pas configuré "
        "(clé Gemini absente)." in without_key
    )
    assert "Assistant indisponible : Gemini est en panne (HTTP 503)." in failed
    assert "Il te reste 5 questions aujourd'hui." in failed


def test_an_object_the_account_does_not_have_is_the_general_conversation(
    app: FastAPI, migrated_engine: Engine
) -> None:
    use_model(app, Assistant(ANSWER))
    client, _ = logged_in(app, migrated_engine)

    drawer = client.get("/tiroir?objet=offre:999999999", headers=HTMX).text

    assert "Conversation générale" in drawer


def test_a_new_conversation_leaves_the_previous_one_aside(
    app: FastAPI, migrated_engine: Engine
) -> None:
    fake = Assistant(ANSWER)
    use_model(app, fake)
    client, _ = logged_in(app, migrated_engine)
    ask(client, "Première question ?")

    fresh = client.post("/tiroir/nouvelle", data={"objet": ""}, headers=HTMX).text
    ask(client, "Deuxième question ?")

    assert "Première question" not in fresh
    assert "Première question" not in fake.prompts[-1]
