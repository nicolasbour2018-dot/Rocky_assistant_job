"""Every call to a language model, per account (decision G4, Q9, Q17): its type, its model, its tokens, its outcome.

The calls are measured to decide the limits of the beta from their costs (Q8, Q16); only the assistant is limited
here. A call is recorded when a request left: a model without its key sends nothing and writes nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import Request
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    Engine,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Table,
    Text,
    func,
    insert,
    select,
)

from rocky.system.auth.model import Account
from rocky.system.config import CallType, LlmSettings, ModelChoice, Provider
from rocky.system.db import metadata
from rocky.system.llm import adapter_for
from rocky.system.llm.port import (
    LABELS,
    Completion,
    HttpAdapter,
    JsonModel,
    LlmUnavailableError,
    Usage,
)

type Clock = Callable[[], datetime]
# A model of the tests, or another one, given in place of the settings' for every call type.
type ModelOf = Callable[[CallType], JsonModel]


class CallOutcome(StrEnum):
    # The provider answered (the caller checks the shape of the answer).
    OK = "ok"
    FAILED = "failed"
    # The assistant refused the answer: no fact cited, or an unknown one (Q12).
    REJECTED = "rejected"


def _in(column: str, values: type[StrEnum]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


model_calls = Table(
    "model_calls",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("call_type", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("called_at", DateTime(timezone=True), nullable=False),
    Column("outcome", Text, nullable=False),
    Column("reason", Text),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("duration_ms", Integer, nullable=False),
    CheckConstraint(_in("call_type", CallType), name="call_type"),
    CheckConstraint(_in("provider", Provider), name="provider"),
    CheckConstraint(_in("outcome", CallOutcome), name="outcome"),
    CheckConstraint("outcome <> 'failed' OR reason IS NOT NULL", name="failure_reason"),
    CheckConstraint(
        "input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_positive"
    ),
    CheckConstraint(
        "output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_positive"
    ),
    CheckConstraint("duration_ms >= 0", name="duration_positive"),
    Index(
        "ix_model_calls_account_id_call_type_called_at",
        "account_id",
        "call_type",
        "called_at",
    ),
)


@dataclass(frozen=True)
class Invocation:
    """One call made, not yet recorded: its answer, or the reason it gave none."""

    call_type: CallType
    choice: ModelChoice
    called_at: datetime
    duration_ms: int
    completion: Completion | None = None
    reason: str | None = None

    @property
    def usage(self) -> Usage:
        return self.completion.usage if self.completion is not None else Usage()


def invoke(
    model: JsonModel,
    *,
    call_type: CallType,
    choice: ModelChoice,
    clock: Clock,
    instructions: str,
    prompt: str,
    schema: Mapping[str, Any],
) -> Invocation:
    """Call ``model``, outside any transaction; a failure is an invocation with its reason, never an exception."""
    called_at, start = clock(), time.monotonic()
    try:
        completion = _complete(model, instructions, prompt, schema)
    except LlmUnavailableError as error:
        return Invocation(
            call_type, choice, called_at, _since(start), reason=error.reason
        )
    return Invocation(call_type, choice, called_at, _since(start), completion)


def _complete(
    model: JsonModel, instructions: str, prompt: str, schema: Mapping[str, Any]
) -> Completion:
    if isinstance(model, HttpAdapter):
        return model.complete(instructions, prompt, schema)
    # A model that does not count its tokens (the fakes of the tests).
    return Completion(model.complete_json(instructions, prompt, schema), Usage())


def _since(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))


def record_call(
    connection: Connection,
    account_id: int,
    invocation: Invocation,
    outcome: CallOutcome | None = None,
) -> int:
    """Write ``invocation`` in the caller's transaction; ``outcome`` by default: ok, or failed with its reason."""
    if outcome is None:
        outcome = CallOutcome.FAILED if invocation.reason else CallOutcome.OK
    usage = invocation.usage
    call_id: int = connection.execute(
        insert(model_calls)
        .values(
            account_id=account_id,
            call_type=invocation.call_type,
            provider=invocation.choice.provider,
            model=invocation.choice.name,
            called_at=invocation.called_at,
            outcome=outcome,
            reason=invocation.reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            duration_ms=invocation.duration_ms,
        )
        .returning(model_calls.c.id)
    ).scalar_one()
    return call_id


def calls_since(
    connection: Connection,
    account_id: int,
    call_type: CallType,
    since: datetime,
    outcomes: tuple[CallOutcome, ...],
) -> int:
    """The calls of ``call_type`` since ``since`` with one of ``outcomes``."""
    found: int = connection.execute(
        select(func.count())
        .select_from(model_calls)
        .where(
            model_calls.c.account_id == account_id,
            model_calls.c.call_type == call_type,
            model_calls.c.called_at >= since,
            model_calls.c.outcome.in_(outcomes),
        )
    ).scalar_one()
    return found


class RecordedModel:
    """A model whose every call is recorded for one account, in its own short transaction."""

    def __init__(
        self,
        model: JsonModel,
        *,
        engine: Engine,
        clock: Clock,
        call_type: CallType,
        choice: ModelChoice,
        account_id: int,
    ) -> None:
        self._model = model
        self._engine = engine
        self._clock = clock
        self._call_type = call_type
        self._choice = choice
        self._account_id = account_id

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        invocation = invoke(
            self._model,
            call_type=self._call_type,
            choice=self._choice,
            clock=self._clock,
            instructions=instructions,
            prompt=prompt,
            schema=schema,
        )
        with self._engine.begin() as connection:
            record_call(connection, self._account_id, invocation)
        if invocation.completion is None:
            raise LlmUnavailableError(invocation.reason or "")
        return invocation.completion.value


class Models:
    """The model of each call type (Q25), on ``app.state.models``; the tests give theirs with ``model_of``."""

    def __init__(
        self,
        engine: Engine,
        settings: LlmSettings,
        clock: Clock,
        *,
        model_of: ModelOf | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.clock = clock
        self._model_of = model_of

    def choice(self, call_type: CallType) -> ModelChoice:
        return self.settings.choice(call_type)

    def model(self, call_type: CallType) -> JsonModel:
        """The model of ``call_type``, not recorded."""
        if self._model_of is not None:
            return self._model_of(call_type)
        return adapter_for(self.settings, call_type)

    def unavailable_reason(self, call_type: CallType) -> str | None:
        """Why ``call_type`` cannot call its model (its provider's key is missing); None when it can."""
        if self._model_of is not None:
            return None
        provider = self.choice(call_type).provider
        if self.settings.key(provider):
            return None
        return f"Le modèle de langage n'est pas configuré (clé {LABELS[provider]} absente)."

    def for_call(self, call_type: CallType, account_id: int) -> JsonModel:
        """The model of ``call_type`` for ``account_id``, its calls recorded; without its key, it says so at each
        call and writes nothing."""
        model = self.model(call_type)
        if self.unavailable_reason(call_type) is not None:
            return model
        return self.recorded(model, call_type, account_id)

    def recorded(
        self, model: JsonModel, call_type: CallType, account_id: int
    ) -> JsonModel:
        return RecordedModel(
            model,
            engine=self.engine,
            clock=self.clock,
            call_type=call_type,
            choice=self.choice(call_type),
            account_id=account_id,
        )

    def invoke(
        self,
        call_type: CallType,
        *,
        instructions: str,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Invocation:
        """One call of ``call_type``, not recorded: the caller records it with what it writes."""
        return invoke(
            self.model(call_type),
            call_type=call_type,
            choice=self.choice(call_type),
            clock=self.clock,
            instructions=instructions,
            prompt=prompt,
            schema=schema,
        )


def model_for(request: Request, call_type: CallType, account: Account) -> JsonModel:
    """The model of ``call_type`` for the account of a route, its calls recorded."""
    models: Models = request.app.state.models
    return models.for_call(call_type, account.id)
