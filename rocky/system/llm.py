"""Language model adapter: Gemini ``generateContent`` over HTTP, a bounded wait, no retry, JSON output.

Decision ``docs/decisions/C3-analyse.md`` (Q1, Q7): the model summarises; it never gives a fact nor a score. The
caller checks the shape of the answer. The key never appears in a reason nor in the logs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

import httpx2

from rocky.system.config import LlmSettings

logger = logging.getLogger(__name__)

API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
TIMEOUT_SECONDS = 30.0


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


class GeminiModel:
    """One request per call. Without a key, every call says the model is not configured."""

    def __init__(
        self,
        settings: LlmSettings,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = timeout_seconds

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        if not self._settings.api_key:
            raise LlmUnavailableError(
                "Le modèle de langage n'est pas configuré (clé Gemini absente)."
            )
        if not self._settings.api_key.isascii():
            # An HTTP header takes ASCII only: a pasted character would fail the request with an encoding error.
            raise LlmUnavailableError(
                "La clé Gemini contient un caractère invalide : vérifie sa copie."
            )
        body = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": dict(schema),
                "temperature": 0.2,
            },
        }
        try:
            with httpx2.Client(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = client.post(
                    API_URL.format(model=self._settings.model),
                    json=body,
                    headers={"x-goog-api-key": self._settings.api_key},
                )
        except httpx2.TimeoutException as error:
            raise LlmUnavailableError(
                "Gemini ne répond pas (délai dépassé)."
            ) from error
        except httpx2.HTTPError as error:
            logger.warning("Gemini request failed: %s", type(error).__name__)
            raise LlmUnavailableError(
                "Gemini est injoignable (erreur réseau)."
            ) from error
        if response.status_code >= 400:
            raise LlmUnavailableError(_refusal(response))
        return _answer(response)


def _refusal(response: httpx2.Response) -> str:
    status = response.status_code
    try:
        details = json.dumps(response.json())
    except ValueError:
        details = ""
    if status in (401, 403) or "API_KEY_INVALID" in details:
        return f"La clé Gemini est refusée (HTTP {status})."
    if status == 429:
        return "Quota Gemini atteint pour le moment (HTTP 429)."
    if status >= 500:
        return f"Gemini est en panne (HTTP {status})."
    return f"Gemini a refusé la demande (HTTP {status})."


def _answer(response: httpx2.Response) -> Any:
    try:
        data = response.json()
    except ValueError as error:
        raise LlmUnavailableError("Gemini a renvoyé une réponse illisible.") from error
    blocked = (
        (data.get("promptFeedback") or {}).get("blockReason")
        if isinstance(data, dict)
        else None
    )
    if blocked:
        raise LlmUnavailableError(f"Gemini a bloqué la demande ({blocked}).")
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if (
        not isinstance(candidates, list)
        or not candidates
        or not isinstance(candidates[0], dict)
    ):
        raise LlmUnavailableError("Gemini n'a donné aucune réponse.")
    candidate = candidates[0]
    finish = candidate.get("finishReason")
    if finish not in (None, "STOP"):
        raise LlmUnavailableError(f"Gemini s'est arrêté avant la fin ({finish}).")
    parts = (candidate.get("content") or {}).get("parts") or []
    # Thinking models may add their reasoning as parts marked "thought": only the answer is read.
    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and not part.get("thought")
    )
    try:
        return json.loads(text)
    except ValueError as error:
        raise LlmUnavailableError("Gemini a renvoyé une réponse illisible.") from error
