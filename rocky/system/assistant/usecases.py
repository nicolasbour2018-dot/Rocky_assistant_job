"""Ask the assistant (decision G4): within the day's limit, one call with the frozen facts, the answer checked, then
the call and the turn written in one transaction.

The call is made outside any transaction. A call that failed is recorded as such, not counted (Q8) and adds no turn.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine

from rocky.system.assistant.model import (
    HISTORY_TURNS,
    INSTRUCTIONS,
    QUESTION_MAX,
    SCHEMA,
    AnswerOutcome,
    Checked,
    Fact,
    Subject,
    checked,
    fit,
    prompt,
    unique,
)
from rocky.system.assistant.sql import AssistantStore, TurnRecord
from rocky.system.clock import paris_midnight
from rocky.system.config import CallType
from rocky.system.llm.calls import CallOutcome, Models, calls_since, record_call

ASSISTANT = CallType.ASSISTANT
# Q7: the limit reached, a model not configured, a failure: one plain sentence.
LIMIT_REASON = "Assistant indisponible : plafond du jour atteint, il revient demain."
UNAVAILABLE = "Assistant indisponible : {reason}"
EMPTY_QUESTION = "Écris ta question."
LONG_QUESTION = f"Ta question est trop longue ({QUESTION_MAX} caractères au plus)."
# A question counts when the model answered it, its answer shown or replaced (Q8).
COUNTED = (CallOutcome.OK, CallOutcome.REJECTED)


@dataclass(frozen=True)
class Reply:
    """What the drawer shows after a question: the answer, or the reason there is none; the questions left today."""

    answer: Checked | None
    reason: str | None
    left: int


def questions_left(engine: Engine, models: Models, account_id: int, today: date) -> int:
    with engine.connect() as connection:
        used = calls_since(
            connection, account_id, ASSISTANT, paris_midnight(today), COUNTED
        )
    return max(0, models.settings.assistant_per_day - used)


def conversation(
    engine: Engine, account_id: int, subject: Subject | None
) -> list[TurnRecord]:
    """The turns of the conversation in progress about ``subject`` (Q10: it resumes from one day to the next)."""
    with engine.connect() as connection:
        store = AssistantStore(connection)
        current = store.current(account_id, subject)
        return [] if current is None else store.turns(current)


def start_over(
    engine: Engine, account_id: int, subject: Subject | None, now: datetime
) -> None:
    """« Nouvelle conversation » (Q20): the previous one is kept, no longer sent."""
    with engine.begin() as connection:
        AssistantStore(connection).start(account_id, subject, now)


def ask(
    engine: Engine,
    models: Models,
    *,
    account_id: int,
    subject: Subject | None,
    facts: Callable[[], Sequence[Fact]],
    question: str,
    now: datetime,
    today: date,
) -> Reply:
    """Answer ``question`` from ``facts`` (read only once the question is allowed)."""
    question = question.strip()
    left = questions_left(engine, models, account_id, today)
    if not question:
        return Reply(None, EMPTY_QUESTION, left)
    if len(question) > QUESTION_MAX:
        return Reply(None, LONG_QUESTION, left)
    unavailable = models.unavailable_reason(ASSISTANT)
    if unavailable is not None:
        return Reply(None, UNAVAILABLE.format(reason=unavailable), left)
    if left <= 0:
        return Reply(None, LIMIT_REASON, 0)
    given = fit(unique(facts()))
    history = [turn.exchange for turn in conversation(engine, account_id, subject)]
    invocation = models.invoke(
        ASSISTANT,
        instructions=INSTRUCTIONS,
        prompt=prompt(given, history[-HISTORY_TURNS:], question),
        schema=SCHEMA,
    )
    if invocation.completion is None:
        with engine.begin() as connection:
            record_call(connection, account_id, invocation)
        return Reply(None, UNAVAILABLE.format(reason=invocation.reason), left)
    answer = checked(invocation.completion.value, given)
    with engine.begin() as connection:
        call_id = record_call(
            connection,
            account_id,
            invocation,
            CallOutcome.REJECTED
            if answer.outcome is AnswerOutcome.REJECTED
            else CallOutcome.OK,
        )
        store = AssistantStore(connection)
        current = store.current(account_id, subject)
        if current is None:
            current = store.start(account_id, subject, now)
        store.add_turn(
            conversation_id=current,
            account_id=account_id,
            asked_at=now,
            question=question,
            answer=answer.text,
            cited=answer.cited,
            raw_answer=invocation.completion.value,
            outcome=answer.outcome,
            model_call_id=call_id,
        )
    return Reply(answer, None, left - 1)
