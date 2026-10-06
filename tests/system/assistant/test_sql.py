"""The conversations with the assistant (decision G4, Q10, Q20): one general and one per object, resumed."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from rocky.system.assistant.model import AnswerOutcome, Fact, Subject, SubjectKind
from rocky.system.assistant.sql import AssistantStore, CitedFact
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import CallType, ModelChoice, Provider
from rocky.system.llm.calls import Invocation, record_call
from rocky.system.llm.port import Completion, Usage

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
OFFER = Subject(SubjectKind.OFFER, 12)
SCORE = Fact("offre.score", "Score", "62 sur 100", "/offres/12/fiche")


def _account(db: Connection) -> int:
    return SqlAuthStore(db).create_account(f"{uuid4().hex}@example.fr", NOW)


def _call(db: Connection, account_id: int) -> int:
    return record_call(
        db,
        account_id,
        Invocation(
            CallType.ASSISTANT,
            ModelChoice(Provider.GEMINI, "gemini-3.5-flash-lite"),
            NOW,
            800,
            Completion({}, Usage(10, 5)),
        ),
    )


def test_the_general_and_each_object_have_their_own_conversation(
    db: Connection,
) -> None:
    account_id = _account(db)
    store = AssistantStore(db)

    assert store.current(account_id, None) is None
    general = store.start(account_id, None, NOW)
    offer = store.start(account_id, OFFER, NOW)

    assert store.current(account_id, None) == general
    assert store.current(account_id, OFFER) == offer
    assert store.current(account_id, Subject(SubjectKind.OFFER, 13)) is None
    assert store.current(_account(db), OFFER) is None
    # A new conversation: the latest is the one in progress (Q20).
    again = store.start(account_id, OFFER, NOW)
    assert again != offer
    assert store.current(account_id, OFFER) == again


def test_a_turn_keeps_its_question_answer_facts_and_call(db: Connection) -> None:
    account_id = _account(db)
    store = AssistantStore(db)
    conversation = store.start(account_id, OFFER, NOW)

    store.add_turn(
        conversation_id=conversation,
        account_id=account_id,
        asked_at=NOW,
        question="Pourquoi ce score ?",
        answer="Ton score est de 62.",
        cited=[SCORE],
        raw_answer={"reponse": "Ton score est de 62.", "faits": ["offre.score"]},
        outcome=AnswerOutcome.ANSWERED,
        model_call_id=_call(db, account_id),
    )

    (turn,) = store.turns(conversation)
    assert (turn.question, turn.answer, turn.outcome) == (
        "Pourquoi ce score ?",
        "Ton score est de 62.",
        AnswerOutcome.ANSWERED,
    )
    assert turn.cited == (CitedFact("Score", "/offres/12/fiche"),)
    assert turn.exchange.answer == "Ton score est de 62."


def test_an_empty_question_is_refused(db: Connection) -> None:
    account_id = _account(db)
    store = AssistantStore(db)

    with pytest.raises(IntegrityError, match="question_given"):
        store.add_turn(
            conversation_id=store.start(account_id, None, NOW),
            account_id=account_id,
            asked_at=NOW,
            question="",
            answer="…",
            cited=[],
            raw_answer=None,
            outcome=AnswerOutcome.REJECTED,
            model_call_id=_call(db, account_id),
        )
