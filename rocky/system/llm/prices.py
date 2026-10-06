"""The prices of the models, to estimate the cost of the calls (decision G4, Q16, Q33).

Tokens are the fact measured; euros are an estimate, shown as such with the date of the prices. A model missing here
has an unknown price, never 0 €. The prices are read by hand on the providers' pages (sources below) and checked by
Nicolas before the recette; a change of price is a new entry here, dated by the history of this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rocky.system.config import ModelChoice, Provider
from rocky.system.llm.port import Usage

PRICES_DATE = date(2026, 10, 7)
# ECB reference rate of 06/10/2026: 1 € = 1.1269 $ (ecb.europa.eu, euro reference exchange rates).
USD_PER_EUR = Decimal("1.1269")
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens, standard tier, short prompts."""

    usd_in: Decimal
    usd_out: Decimal


def _price(usd_in: str, usd_out: str) -> Price:
    return Price(Decimal(usd_in), Decimal(usd_out))


PRICES: dict[ModelChoice, Price] = {
    # https://ai.google.dev/gemini-api/docs/pricing (paid tier, text input, output with thinking).
    ModelChoice(Provider.GEMINI, "gemini-3.5-flash-lite"): _price("0.30", "2.50"),
    ModelChoice(Provider.GEMINI, "gemini-3.5-flash"): _price("1.50", "9.00"),
    # Until 31/12/2026; twice these from 01/01/2027.
    ModelChoice(Provider.GEMINI, "gemini-3.6-flash"): _price("0.75", "3.75"),
    ModelChoice(Provider.GEMINI, "gemini-3.7-flash"): _price("0.75", "3.75"),
    ModelChoice(Provider.GEMINI, "gemini-3.8-flash"): _price("0.75", "3.75"),
    ModelChoice(Provider.GEMINI, "gemini-3.1-flash-lite"): _price("0.25", "1.50"),
    ModelChoice(Provider.GEMINI, "gemini-2.5-pro"): _price("1.25", "10.00"),
    ModelChoice(Provider.GEMINI, "gemini-2.5-flash"): _price("0.30", "2.50"),
    ModelChoice(Provider.GEMINI, "gemini-2.5-flash-lite"): _price("0.10", "0.40"),
    # https://platform.claude.com/docs (models overview, prices of 25/09/2026).
    ModelChoice(Provider.ANTHROPIC, "claude-fable-5-1"): _price("10.00", "50.00"),
    ModelChoice(Provider.ANTHROPIC, "claude-opus-5-5"): _price("4.00", "20.00"),
    ModelChoice(Provider.ANTHROPIC, "claude-opus-5"): _price("5.00", "25.00"),
    ModelChoice(Provider.ANTHROPIC, "claude-sonnet-5-5"): _price("2.00", "10.00"),
    ModelChoice(Provider.ANTHROPIC, "claude-sonnet-5"): _price("2.00", "10.00"),
    ModelChoice(Provider.ANTHROPIC, "claude-haiku-4-5"): _price("1.00", "5.00"),
    # https://developers.openai.com/api/docs/pricing (standard tier, short context).
    ModelChoice(Provider.OPENAI, "gpt-6-astra"): _price("10.00", "50.00"),
    ModelChoice(Provider.OPENAI, "gpt-6.1-sol"): _price("2.00", "10.00"),
    ModelChoice(Provider.OPENAI, "gpt-6-luna"): _price("0.10", "0.50"),
    ModelChoice(Provider.OPENAI, "gpt-5.5"): _price("5.00", "30.00"),
    ModelChoice(Provider.OPENAI, "gpt-5.4"): _price("2.50", "15.00"),
    ModelChoice(Provider.OPENAI, "gpt-5.4-mini"): _price("0.75", "4.50"),
    ModelChoice(Provider.OPENAI, "gpt-5.4-nano"): _price("0.20", "1.25"),
    ModelChoice(Provider.OPENAI, "gpt-5"): _price("1.25", "10.00"),
    ModelChoice(Provider.OPENAI, "gpt-5-mini"): _price("0.25", "2.00"),
    ModelChoice(Provider.OPENAI, "gpt-5-nano"): _price("0.05", "0.40"),
    # https://mistral.ai/pricing gives Mistral Large only.
    ModelChoice(Provider.MISTRAL, "mistral-large-latest"): _price("0.50", "1.50"),
    # Not on Mistral's pages on 07/10/2026: read on a third-party comparison, TO BE CHECKED by Nicolas.
    ModelChoice(Provider.MISTRAL, "mistral-medium-latest"): _price("1.50", "7.50"),
    ModelChoice(Provider.MISTRAL, "mistral-medium-3-5-26-04"): _price("1.50", "7.50"),
    ModelChoice(Provider.MISTRAL, "mistral-small-latest"): _price("0.15", "0.60"),
    ModelChoice(Provider.MISTRAL, "mistral-small-4-0-26-03"): _price("0.15", "0.60"),
}


def cost(choice: ModelChoice, usage: Usage) -> Decimal | None:
    """The estimated cost in euros of ``usage`` on ``choice``; None when its price or its tokens are unknown."""
    price = PRICES.get(choice)
    if price is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    usd = (
        price.usd_in * usage.input_tokens + price.usd_out * usage.output_tokens
    ) / MILLION
    return usd / USD_PER_EUR
