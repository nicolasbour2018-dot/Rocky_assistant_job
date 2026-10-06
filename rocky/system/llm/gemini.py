"""Gemini ``generateContent``: JSON constrained by the schema (decision C3; G4: the tokens it used)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx2

from rocky.system.config import Provider
from rocky.system.llm.port import (
    Completion,
    HttpAdapter,
    LlmUnavailableError,
    Usage,
    count,
)

API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiModel(HttpAdapter):
    """One request per call. Without a key, every call says the model is not configured."""

    provider = Provider.GEMINI

    def complete(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Completion:
        key = self.key()
        body = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": dict(schema),
                "temperature": 0.2,
            },
        }
        data = self.post(API_URL.format(model=self.name), body, {"x-goog-api-key": key})
        return Completion(self._answer(data), _usage(data))

    def key_refused(self, response: httpx2.Response) -> bool:
        try:
            return "API_KEY_INVALID" in json.dumps(response.json())
        except ValueError:
            return False

    def _answer(self, data: Any) -> Any:
        feedback = data.get("promptFeedback") if isinstance(data, dict) else None
        blocked = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if blocked:
            raise LlmUnavailableError(f"Gemini a bloqué la demande ({blocked}).")
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if (
            not isinstance(candidates, list)
            or not candidates
            or not isinstance(candidates[0], dict)
        ):
            raise LlmUnavailableError(self.no_answer())
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish not in (None, "STOP"):
            raise LlmUnavailableError(self.stopped(finish))
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise LlmUnavailableError(self.no_answer())
        # Thinking models may add their reasoning as parts marked "thought": only the answer is read.
        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and not part.get("thought")
        )
        return self.decoded(text)


def _usage(data: Any) -> Usage:
    """The thinking tokens are billed as output: they are counted with it."""
    metadata = data.get("usageMetadata") if isinstance(data, dict) else None
    if not isinstance(metadata, dict):
        return Usage()
    output = count(metadata.get("candidatesTokenCount"))
    thoughts = count(metadata.get("thoughtsTokenCount"))
    if output is not None and thoughts is not None:
        output += thoughts
    return Usage(count(metadata.get("promptTokenCount")), output)
