"""The cost of the calls to the models (decision G4, Q16, Q18, Q19): tokens, estimated euros, never 0 € unknown."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Connection, Engine

from rocky.system.admin import model_costs
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import CallType, ModelChoice, Provider
from rocky.system.llm.calls import Invocation, record_call
from rocky.system.llm.costs import (
    CallsOf,
    Costs,
    costs,
    euros,
    summary,
    tally,
)
from rocky.system.llm.port import Completion, Usage
from rocky.system.llm.prices import USD_PER_EUR, cost
from rocky.system.web import costs_card

TODAY = date(2026, 10, 7)
# 00:30 in Paris on 07/10 is still 06/10 in UTC: the call is today's.
HALF_PAST_MIDNIGHT = datetime(2026, 10, 6, 22, 30, tzinfo=UTC)
FLASH_LITE = ModelChoice(Provider.GEMINI, "gemini-3.5-flash-lite")
UNKNOWN = ModelChoice(Provider.MISTRAL, "mistral-inconnu")


def test_a_cost_is_estimated_in_euros_from_the_dollar_prices() -> None:
    # 1 M input tokens at 0.30 $ and 1 M output tokens at 2.50 $.
    assert (
        cost(FLASH_LITE, Usage(1_000_000, 1_000_000)) == Decimal("2.80") / USD_PER_EUR
    )


def test_an_unknown_price_or_unknown_tokens_give_no_cost() -> None:
    assert cost(UNKNOWN, Usage(10, 10)) is None
    assert cost(FLASH_LITE, Usage(10, None)) is None


def test_calls_without_a_cost_are_counted_apart_never_at_0_euro() -> None:
    priced = tally(CallsOf(1, CallType.LETTER, FLASH_LITE, 3, 1, 2000, 500, 0))
    unpriced = tally(CallsOf(1, CallType.LETTER, UNKNOWN, 3, 1, 2000, 500, 0))

    assert (priced.calls, priced.failed, priced.unpriced) == (3, 1, 0)
    assert priced.euros > 0
    assert (unpriced.euros, unpriced.unpriced) == (Decimal(0), 2)
    assert (
        summary(priced + unpriced)
        == "6 appels (dont 2 échoués) · 5 000 jetons · ≈ < 0,01 € (+ 2 sans tarif)"
    )


def test_euros_are_shown_rounded_and_small_amounts_as_such() -> None:
    assert euros(Decimal(0)) == "0 €"
    assert euros(Decimal("0.004")) == "< 0,01 €"
    assert euros(Decimal("1.236")) == "1,24 €"


def _account(connection: Connection) -> int:
    return SqlAuthStore(connection).create_account(
        f"{uuid4().hex}@example.fr", HALF_PAST_MIDNIGHT
    )


def _call(
    connection: Connection,
    account_id: int,
    call_type: CallType,
    at: datetime,
    tokens: tuple[int, int] = (1000, 200),
) -> None:
    record_call(
        connection,
        account_id,
        Invocation(call_type, FLASH_LITE, at, 900, Completion({}, Usage(*tokens))),
    )


def test_the_costs_of_an_account_are_per_type_and_per_paris_period(
    db: Connection,
) -> None:
    account_id, other = _account(db), _account(db)
    _call(db, account_id, CallType.ASSISTANT, HALF_PAST_MIDNIGHT)
    # 23:59 in Paris on 06/10: yesterday, within 7 days.
    _call(db, account_id, CallType.ASSISTANT, datetime(2026, 10, 6, 21, 59, tzinfo=UTC))
    _call(db, account_id, CallType.LETTER, datetime(2026, 9, 20, 10, 0, tzinfo=UTC))
    # 31 days ago: out of every period.
    _call(db, account_id, CallType.LETTER, datetime(2026, 9, 6, 10, 0, tzinfo=UTC))
    _call(db, other, CallType.ASSISTANT, HALF_PAST_MIDNIGHT)

    found = costs(db, TODAY, account_id)

    assert [found.total(period).calls for period in range(3)] == [1, 2, 3]
    assert found.of_type(1, CallType.ASSISTANT).calls == 2
    assert found.of_type(2, CallType.LETTER).tokens == 1200
    assert found.accounts() == [account_id]


def test_the_panel_of_systeme_gives_each_period_then_each_type(db: Connection) -> None:
    account_id = _account(db)
    _call(db, account_id, CallType.ASSISTANT, HALF_PAST_MIDNIGHT)
    _call(db, account_id, CallType.SUMMARY, datetime(2026, 9, 20, 10, 0, tzinfo=UTC))

    card = costs_card(costs(db, TODAY, account_id))

    assert card.lines[0].startswith("Aujourd'hui : 1 appel · 1 200 jetons")
    assert card.lines[2].startswith("30 jours : 2 appels")
    assert "tarifs du 07/10/2026" in card.lines[-1]
    assert [label for label, _ in card.details] == ["Assistant", "Résumé d'offre"]
    assert card.details[1][1].startswith(
        "aujourd'hui 0 · 7 jours 0 · 30 jours : 1 appel"
    )
    assert card.action is None and not card.problem


def test_an_account_without_calls_says_so() -> None:
    card = costs_card(Costs(({}, {}, {})))

    assert card.lines[0] == "Aucun appel au modèle sur 30 jours."


def test_the_command_sums_up_every_account(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        account_id = _account(connection)
        _call(connection, account_id, CallType.ASSISTANT, HALF_PAST_MIDNIGHT)
        email = SqlAuthStore(connection).get_account(account_id)
    out = io.StringIO()

    assert model_costs(migrated_engine, today=TODAY, out=out) == 0

    text = out.getvalue()
    assert email is not None and f"{email.email} (30 jours) : 1 appel" in text
    assert "  Assistant : 1 appel · 1 200 jetons" in text
