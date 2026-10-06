"""The cost of the calls to the language models (decision G4, Q16, Q18, Q19): calls, tokens and estimated euros,
per account and per call type, today, over 7 and over 30 days (days of Paris).

A call whose price or tokens are unknown is counted apart: never 0 €.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Connection, func, select

from rocky.system.clock import paris_midnight
from rocky.system.config import CallType, ModelChoice, Provider
from rocky.system.llm.calls import CallOutcome, model_calls
from rocky.system.llm.port import Usage
from rocky.system.llm.prices import PRICES_DATE, USD_PER_EUR, cost

CALL_TYPE_LABELS = {
    CallType.ASSISTANT: "Assistant",
    CallType.SUMMARY: "Résumé d'offre",
    CallType.CV: "Import du CV",
    CallType.TRANSLATION: "Traduction",
    CallType.LETTER: "Lettre",
    CallType.RECRUITER_MESSAGE: "Message au recruteur",
    CallType.MAIL_CLASSIFICATION: "Classement des messages",
}
# Q18: today, 7 days, 30 days, each ending today.
PERIODS = (("Aujourd'hui", 1), ("7 jours", 7), ("30 jours", 30))


@dataclass(frozen=True)
class Tally:
    calls: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    euros: Decimal = Decimal(0)
    # Calls answered whose cost is unknown: a model without a price, or tokens not given.
    unpriced: int = 0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Tally) -> Tally:
        return Tally(
            self.calls + other.calls,
            self.failed + other.failed,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.euros + other.euros,
            self.unpriced + other.unpriced,
        )


@dataclass(frozen=True)
class CallsOf:
    """The calls of one account, one type and one model since a moment."""

    account_id: int
    call_type: CallType
    choice: ModelChoice
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    # Calls answered without their tokens.
    uncounted: int


def tally(calls: CallsOf) -> Tally:
    answered = calls.calls - calls.failed
    euros = cost(calls.choice, Usage(calls.input_tokens, calls.output_tokens))
    unpriced = answered if euros is None else calls.uncounted
    return Tally(
        calls.calls,
        calls.failed,
        calls.input_tokens,
        calls.output_tokens,
        euros or Decimal(0),
        unpriced,
    )


def calls_of(
    connection: Connection, since: datetime, account_id: int | None = None
) -> list[CallsOf]:
    """The calls since ``since``, of ``account_id`` or of every account."""
    failed = model_calls.c.outcome == CallOutcome.FAILED
    uncounted = (~failed) & (
        model_calls.c.input_tokens.is_(None) | model_calls.c.output_tokens.is_(None)
    )
    query = (
        select(
            model_calls.c.account_id,
            model_calls.c.call_type,
            model_calls.c.provider,
            model_calls.c.model,
            func.count().label("calls"),
            func.count().filter(failed).label("failed"),
            func.coalesce(func.sum(model_calls.c.input_tokens), 0).label("input"),
            func.coalesce(func.sum(model_calls.c.output_tokens), 0).label("output"),
            func.count().filter(uncounted).label("uncounted"),
        )
        .where(model_calls.c.called_at >= since)
        .group_by(
            model_calls.c.account_id,
            model_calls.c.call_type,
            model_calls.c.provider,
            model_calls.c.model,
        )
    )
    if account_id is not None:
        query = query.where(model_calls.c.account_id == account_id)
    return [
        CallsOf(
            row.account_id,
            CallType(row.call_type),
            ModelChoice(Provider(row.provider), row.model),
            row.calls,
            row.failed,
            row.input,
            row.output,
            row.uncounted,
        )
        for row in connection.execute(query)
    ]


@dataclass(frozen=True)
class Costs:
    """For each period of ``PERIODS``, the tally of each (account, call type)."""

    periods: tuple[Mapping[tuple[int, CallType], Tally], ...]

    def of_type(self, period: int, call_type: CallType) -> Tally:
        return _sum(
            tally
            for (_, kind), tally in self.periods[period].items()
            if kind == call_type
        )

    def of_account(self, period: int, account_id: int) -> Tally:
        return _sum(
            tally
            for (account, _), tally in self.periods[period].items()
            if account == account_id
        )

    def total(self, period: int) -> Tally:
        return _sum(self.periods[period].values())

    def accounts(self) -> list[int]:
        return sorted({account for account, _ in self.periods[-1]})


def _sum(tallies: Iterable[Tally]) -> Tally:
    total = Tally()
    for one in tallies:
        total += one
    return total


def costs(connection: Connection, today: date, account_id: int | None = None) -> Costs:
    """The costs of ``account_id`` (or of every account) for each period ending ``today``."""
    periods = []
    for _, days in PERIODS:
        since = paris_midnight(today - timedelta(days=days - 1))
        by_key: dict[tuple[int, CallType], Tally] = {}
        for calls in calls_of(connection, since, account_id):
            key = (calls.account_id, calls.call_type)
            by_key[key] = by_key.get(key, Tally()) + tally(calls)
        periods.append(by_key)
    return Costs(tuple(periods))


def euros(value: Decimal) -> str:
    """« 0,12 € », « < 0,01 € »."""
    if value == 0:
        return "0 €"
    if value < Decimal("0.01"):
        return "< 0,01 €"
    return f"{value:.2f} €".replace(".", ",")


def number(value: int) -> str:
    """« 12 300 »."""
    return f"{value:,}".replace(",", " ")


def summary(one: Tally) -> str:
    """« 4 appels (dont 1 échoué) · 12 300 jetons · ≈ 0,02 € (+ 1 sans tarif) »."""
    text = f"{number(one.calls)} appel{'s' if one.calls > 1 else ''}"
    if one.failed:
        text += f" (dont {one.failed} échoué{'s' if one.failed > 1 else ''})"
    text += f" · {number(one.tokens)} jetons · ≈ {euros(one.euros)}"
    if one.unpriced:
        text += f" (+ {one.unpriced} sans tarif)"
    return text


def prices_note() -> str:
    rate = f"{USD_PER_EUR}".replace(".", ",")
    return (
        f"Estimation : tarifs du {PRICES_DATE:%d/%m/%Y}, convertis au cours de la BCE "
        f"(1 € = {rate} $)."
    )
