"""Every call to a language model is recorded per account (decision G4, Q9, Q17)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import CallType, LlmSettings, ModelChoice, Provider
from rocky.system.llm import GeminiModel, LlmUnavailableError
from rocky.system.llm.calls import (
    CallOutcome,
    Invocation,
    Models,
    calls_since,
    invoke,
    model_calls,
    record_call,
)
from rocky.system.llm.port import Completion, Usage

NOW = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)
CHOICE = ModelChoice(Provider.GEMINI, "gemini-3.5-flash-lite")
SCHEMA = {"type": "object"}


class Answering:
    def __init__(self, answer: Any = None, error: str | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls = 0

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.calls += 1
        if self.error is not None:
            raise LlmUnavailableError(self.error)
        return self.answer


def _account(connection: Connection) -> int:
    return SqlAuthStore(connection).create_account(f"{uuid4().hex}@example.fr", NOW)


def _rows(connection: Connection, account_id: int) -> list[Any]:
    return list(
        connection.execute(
            select(model_calls)
            .where(model_calls.c.account_id == account_id)
            .order_by(model_calls.c.id)
        )
    )


def test_an_invocation_keeps_the_answer_and_its_tokens() -> None:
    adapter = GeminiModel(
        "gemini-3.5-flash-lite",
        "k",
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 2},
                },
            )
        ),
    )

    invocation = invoke(
        adapter,
        call_type=CallType.SUMMARY,
        choice=CHOICE,
        clock=lambda: NOW,
        instructions="c",
        prompt="p",
        schema=SCHEMA,
    )

    assert invocation.completion == Completion({}, Usage(8, 2))
    assert invocation.called_at == NOW
    assert invocation.reason is None


def test_a_failure_is_an_invocation_with_its_reason() -> None:
    invocation = invoke(
        Answering(error="Gemini ne répond pas (délai dépassé)."),
        call_type=CallType.SUMMARY,
        choice=CHOICE,
        clock=lambda: NOW,
        instructions="c",
        prompt="p",
        schema=SCHEMA,
    )

    assert invocation.completion is None
    assert invocation.reason == "Gemini ne répond pas (délai dépassé)."
    assert invocation.usage == Usage()


def test_a_call_is_recorded_with_its_type_model_tokens_and_outcome(
    db: Connection,
) -> None:
    account_id = _account(db)
    answered = Invocation(
        CallType.ASSISTANT, CHOICE, NOW, 1200, Completion({}, Usage(500, 80))
    )
    failed = Invocation(CallType.ASSISTANT, CHOICE, NOW, 30000, reason="délai")

    record_call(db, account_id, answered)
    record_call(db, account_id, failed)
    record_call(db, account_id, answered, CallOutcome.REJECTED)

    rows = _rows(db, account_id)
    assert [
        (row.call_type, row.provider, row.model, row.outcome, row.reason)
        for row in rows
    ] == [
        ("assistant", "gemini", "gemini-3.5-flash-lite", "ok", None),
        ("assistant", "gemini", "gemini-3.5-flash-lite", "failed", "délai"),
        ("assistant", "gemini", "gemini-3.5-flash-lite", "rejected", None),
    ]
    assert (rows[0].input_tokens, rows[0].output_tokens) == (500, 80)
    assert rows[1].duration_ms == 30000
    assert (
        calls_since(
            db,
            account_id,
            CallType.ASSISTANT,
            NOW,
            (CallOutcome.OK, CallOutcome.REJECTED),
        )
        == 2
    )
    assert (
        calls_since(
            db,
            account_id,
            CallType.ASSISTANT,
            NOW + timedelta(seconds=1),
            (CallOutcome.OK,),
        )
        == 0
    )


def test_a_failed_call_without_its_reason_is_refused(db: Connection) -> None:
    account_id = _account(db)

    with pytest.raises(IntegrityError, match="failure_reason"):
        record_call(
            db,
            account_id,
            Invocation(CallType.CV, CHOICE, NOW, 10),
            CallOutcome.FAILED,
        )


def test_the_model_of_a_call_records_each_call_in_its_own_transaction(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        account_id = _account(connection)
    fake = Answering(answer={"texte": "ok"})
    models = Models(
        migrated_engine,
        LlmSettings(keys={Provider.GEMINI: "k"}),
        lambda: NOW,
        model_of=lambda call_type: fake,
    )

    assert models.for_call(CallType.LETTER, account_id).complete_json(
        "c", "p", SCHEMA
    ) == {"texte": "ok"}
    fake.error = "Gemini est en panne (HTTP 503)."
    with pytest.raises(LlmUnavailableError, match="en panne"):
        models.for_call(CallType.LETTER, account_id).complete_json("c", "p", SCHEMA)

    with migrated_engine.connect() as connection:
        rows = _rows(connection, account_id)
    assert [(row.call_type, row.outcome) for row in rows] == [
        ("letter", "ok"),
        ("letter", "failed"),
    ]


def test_a_model_without_its_key_sends_nothing_and_writes_nothing(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        account_id = _account(connection)
    settings = LlmSettings(
        overrides={CallType.ASSISTANT: ModelChoice(Provider.MISTRAL, "mistral-x")},
        keys={Provider.GEMINI: "k"},
    )
    models = Models(migrated_engine, settings, lambda: NOW)

    assert models.unavailable_reason(CallType.LETTER) is None
    assert (
        models.unavailable_reason(CallType.ASSISTANT)
        == "Le modèle de langage n'est pas configuré (clé Mistral absente)."
    )
    with pytest.raises(LlmUnavailableError, match="clé Mistral absente"):
        models.for_call(CallType.ASSISTANT, account_id).complete_json("c", "p", SCHEMA)
    with migrated_engine.connect() as connection:
        assert _rows(connection, account_id) == []
