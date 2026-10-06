"""The port to the language models and what the adapters share: one HTTP request, a bounded wait, no retry.

Decisions ``docs/decisions/C3-analyse.md`` (the model never gives a fact nor a score; the caller checks the shape of
the answer) and ``docs/decisions/G4-assistant.md`` (Q23: several providers behind the same port, each answer with
the tokens it used). The key never appears in a reason, a URL nor the logs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx2

from rocky.system.config import Provider

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
# How each provider is named in a reason shown to the user.
LABELS = {
    Provider.GEMINI: "Gemini",
    Provider.ANTHROPIC: "Anthropic",
    Provider.OPENAI: "OpenAI",
    Provider.MISTRAL: "Mistral",
}


class LlmUnavailableError(Exception):
    """The model gave no usable answer; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JsonModel(Protocol):
    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        """The decoded JSON answer to ``prompt``; raises ``LlmUnavailableError``."""
        ...


@dataclass(frozen=True)
class Usage:
    """The tokens a call used, as its provider counted them (None when it did not say)."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class Completion:
    value: Any
    usage: Usage


class Adapter(JsonModel, Protocol):
    """A model of one provider: its answer with the tokens it used."""

    @property
    def provider(self) -> Provider: ...

    @property
    def name(self) -> str: ...

    def complete(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Completion:
        """Raises ``LlmUnavailableError``."""
        ...


class HttpAdapter:
    """What the HTTP adapters share: the key check, the request, the reasons of a refusal."""

    provider: Provider

    def __init__(
        self,
        name: str,
        api_key: str | None,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout_seconds

    @property
    def label(self) -> str:
        return LABELS[self.provider]

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        return self.complete(instructions, prompt, schema).value

    def complete(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Completion:
        raise NotImplementedError

    def key(self) -> str:
        """The key, checked before anything is sent."""
        if not self._api_key:
            raise LlmUnavailableError(
                f"Le modèle de langage n'est pas configuré (clé {self.label} absente)."
            )
        if not self._api_key.isascii():
            # An HTTP header takes ASCII only: a pasted character would fail the request with an encoding error.
            raise LlmUnavailableError(
                f"La clé {self.label} contient un caractère invalide : vérifie sa copie."
            )
        return self._api_key

    def post(
        self, url: str, body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> Any:
        """The decoded JSON body of the answer; a refusal, a timeout or a network error is a reason."""
        try:
            with httpx2.Client(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = client.post(url, json=dict(body), headers=dict(headers))
        except httpx2.TimeoutException as error:
            raise LlmUnavailableError(
                f"{self.label} ne répond pas (délai dépassé)."
            ) from error
        except httpx2.HTTPError as error:
            logger.warning("%s request failed: %s", self.label, type(error).__name__)
            raise LlmUnavailableError(
                f"{self.label} est injoignable (erreur réseau)."
            ) from error
        if response.status_code >= 400:
            raise LlmUnavailableError(self.refusal(response))
        try:
            return response.json()
        except ValueError as error:
            raise LlmUnavailableError(self.unreadable()) from error

    def refusal(self, response: httpx2.Response) -> str:
        status = response.status_code
        if status in (401, 403) or self.key_refused(response):
            return f"La clé {self.label} est refusée (HTTP {status})."
        if status == 429:
            return f"Quota {self.label} atteint pour le moment (HTTP 429)."
        if status >= 500:
            return f"{self.label} est en panne (HTTP {status})."
        return f"{self.label} a refusé la demande (HTTP {status})."

    def key_refused(self, response: httpx2.Response) -> bool:
        """A provider that refuses a key with another status than 401 or 403 says so here."""
        return False

    def unreadable(self) -> str:
        return f"{self.label} a renvoyé une réponse illisible."

    def no_answer(self) -> str:
        return f"{self.label} n'a donné aucune réponse."

    def stopped(self, why: object) -> str:
        return f"{self.label} s'est arrêté avant la fin ({why})."

    def decoded(self, text: str) -> Any:
        try:
            return json.loads(text)
        except ValueError as error:
            raise LlmUnavailableError(self.unreadable()) from error


def count(value: object) -> int | None:
    """A token count read from an answer: a non-negative integer, else unknown."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
