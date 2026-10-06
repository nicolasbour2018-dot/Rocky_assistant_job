"""Ask the assistant (decision G4, Q8, Q10, Q12, Q20): the day's limit, failures not counted, the conversation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from rocky.system.assistant.model import (
    NO_FACTS_ANSWER,
    AnswerOutcome,
    Fact,
    Subject,
    SubjectKind,
)
from rocky.system.assistant.usecases import (
    EMPTY_QUESTION,
    LIMIT_REASON,
    Reply,
    ask,
    conversation,
    start_over,
)
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import CallType, LlmSettings, ModelChoice, Provider
from rocky.system.llm import LlmUnavailableError
from rocky.system.llm.calls import Models, model_calls
from tests.system.assistant.fakes import Assistant

TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
OFFER = Subject(SubjectKind.OFFER, 12)
SCORE = Fact("offre.score", "Score", "62 sur 100", "/offres/12/fiche")
ANSWER = {
    "reponse": "Ton score est de 62.",
    "faits": ["offre.score"],
    "sans_reponse": False,
}


@pytest.fixture
def account_id(migrated_engine: Engine) -> int:
    with migrated_engine.begin() as connection:
        return SqlAuthStore(connection).create_account(f"{uuid4().hex}@example.fr", NOW)


def models(engine: Engine, fake: Assistant, limit: int = 5) -> Models:
    return Models(
        engine,
        LlmSettings(keys={Provider.GEMINI: "k"}, assistant_per_day=limit),
        lambda: NOW,
        model_of=lambda call_type: fake,
    )


def question(
    engine: Engine, chosen: Models, account_id: int, text: str = "Pourquoi ce score ?"
) -> Reply:
    return ask(
        engine,
        chosen,
        account_id=account_id,
        subject=OFFER,
        facts=lambda: [SCORE],
        question=text,
        now=NOW,
        today=TODAY,
    )


def test_an_answer_is_shown_with_its_facts_and_kept(
    migrated_engine: Engine, account_id: int
) -> None:
    fake = Assistant(ANSWER)

    reply = question(migrated_engine, models(migrated_engine, fake), account_id)

    assert reply.reason is None and reply.answer is not None
    assert reply.answer.text == "Ton score est de 62."
    assert reply.answer.cited == (SCORE,)
    assert reply.left == 4
    assert "[offre.score] Score : 62 sur 100" in fake.prompts[0]
    (turn,) = conversation(migrated_engine, account_id, OFFER)
    assert (turn.question, turn.outcome) == (
        "Pourquoi ce score ?",
        AnswerOutcome.ANSWERED,
    )
    assert conversation(migrated_engine, account_id, None) == []


def test_the_sixth_question_of_the_day_meets_the_limit(
    migrated_engine: Engine, account_id: int
) -> None:
    fake = Assistant(ANSWER)
    chosen = models(migrated_engine, fake)

    for _ in range(5):
        assert question(migrated_engine, chosen, account_id).answer is not None
    sixth = question(migrated_engine, chosen, account_id)

    assert (sixth.answer, sixth.reason, sixth.left) == (None, LIMIT_REASON, 0)
    assert len(fake.prompts) == 5


def test_a_failure_of_the_model_is_said_and_not_counted(
    migrated_engine: Engine, account_id: int
) -> None:
    fake = Assistant(
        LlmUnavailableError("Gemini ne répond pas (délai dépassé)."), ANSWER
    )
    chosen = models(migrated_engine, fake, limit=1)

    failed = question(migrated_engine, chosen, account_id)
    answered = question(migrated_engine, chosen, account_id)

    assert (
        failed.reason
        == "Assistant indisponible : Gemini ne répond pas (délai dépassé)."
    )
    assert failed.left == 1
    assert answered.answer is not None and answered.left == 0
    assert len(conversation(migrated_engine, account_id, OFFER)) == 1
    with migrated_engine.connect() as connection:
        outcomes = (
            connection.execute(
                select(model_calls.c.outcome)
                .where(model_calls.c.account_id == account_id)
                .order_by(model_calls.c.id)
            )
            .scalars()
            .all()
        )
    assert outcomes == ["failed", "ok"]


def test_an_answer_citing_no_known_fact_is_replaced_and_counted(
    migrated_engine: Engine, account_id: int
) -> None:
    fake = Assistant(
        {
            "reponse": "Ton score est de 90.",
            "faits": ["offre.salaire"],
            "sans_reponse": False,
        }
    )

    reply = question(migrated_engine, models(migrated_engine, fake), account_id)

    assert reply.answer is not None
    assert (reply.answer.text, reply.answer.outcome) == (
        NO_FACTS_ANSWER,
        AnswerOutcome.REJECTED,
    )
    assert reply.left == 4
    with migrated_engine.connect() as connection:
        outcome = connection.execute(
            select(model_calls.c.outcome).where(model_calls.c.account_id == account_id)
        ).scalar_one()
    assert outcome == "rejected"


def test_the_conversation_sends_its_last_six_turns_and_starts_over_on_demand(
    migrated_engine: Engine, account_id: int
) -> None:
    fake = Assistant(ANSWER)
    chosen = models(migrated_engine, fake, limit=10)
    for index in range(8):
        question(migrated_engine, chosen, account_id, f"Question {index}")

    last = fake.prompts[-1]
    assert "Question : Question 0\n" not in last
    assert "Question : Question 1\nRéponse : Ton score est de 62." in last

    start_over(migrated_engine, account_id, OFFER, NOW)
    question(migrated_engine, chosen, account_id, "Et maintenant ?")

    assert "Échanges précédents" not in fake.prompts[-1]
    assert [
        turn.question for turn in conversation(migrated_engine, account_id, OFFER)
    ] == ["Et maintenant ?"]


def test_an_empty_question_or_a_model_without_key_sends_nothing(
    migrated_engine: Engine, account_id: int
) -> None:
    fake = Assistant(ANSWER)
    without_key = Models(
        migrated_engine,
        LlmSettings(
            overrides={
                CallType.ASSISTANT: ModelChoice(Provider.ANTHROPIC, "claude-sonnet-5-5")
            },
            keys={Provider.GEMINI: "k"},
        ),
        lambda: NOW,
    )

    empty = question(migrated_engine, models(migrated_engine, fake), account_id, "  ")
    unavailable = question(migrated_engine, without_key, account_id)

    assert empty.reason == EMPTY_QUESTION
    assert unavailable.reason == (
        "Assistant indisponible : Le modèle de langage n'est pas configuré (clé Anthropic absente)."
    )
    assert fake.prompts == []
