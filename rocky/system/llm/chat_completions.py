"""OpenAI and Mistral ``chat/completions``: JSON constrained by the schema (``response_format``), decision G4 (Q23).

Both providers take the same request and give the same answer. The schema is sent in non-strict mode: Rocky's
schemas are not all written for the strict mode (every property required, closed objects), and the caller checks the
shape of the answer anyway.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rocky.system.config import Provider
from rocky.system.llm.port import (
    Completion,
    HttpAdapter,
    LlmUnavailableError,
    Usage,
    count,
)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


class ChatCompletionsModel(HttpAdapter):
    url: str
    # OpenAI's reasoning models refuse any temperature but the default: only Mistral sets one.
    temperature: float | None = None

    def complete(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Completion:
        key = self.key()
        body: dict[str, Any] = {
            "model": self.name,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reponse",
                    "schema": dict(schema),
                    "strict": False,
                },
            },
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        data = self.post(self.url, body, {"Authorization": f"Bearer {key}"})
        return Completion(self._answer(data), _usage(data))

    def _answer(self, data: Any) -> Any:
        choices = data.get("choices") if isinstance(data, dict) else None
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise LlmUnavailableError(self.no_answer())
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            raise LlmUnavailableError(f"{self.label} a bloqué la demande (filtre).")
        if finish not in (None, "stop"):
            raise LlmUnavailableError(self.stopped(finish))
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LlmUnavailableError(self.no_answer())
        if message.get("refusal"):
            raise LlmUnavailableError(f"{self.label} a refusé de répondre (refus).")
        text = _text(message.get("content"))
        if not text:
            raise LlmUnavailableError(self.no_answer())
        return self.decoded(text)


class OpenAiModel(ChatCompletionsModel):
    provider = Provider.OPENAI
    url = OPENAI_URL


class MistralModel(ChatCompletionsModel):
    provider = Provider.MISTRAL
    url = MISTRAL_URL
    temperature = 0.2


def _text(content: object) -> str:
    """The answer's text: a string, or a list of chunks of which only the text ones are read."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            chunk.get("text", "")
            for chunk in content
            if isinstance(chunk, dict) and chunk.get("type") == "text"
        )
    return ""


def _usage(data: Any) -> Usage:
    """The reasoning tokens are counted in the completion tokens."""
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return Usage()
    return Usage(
        count(usage.get("prompt_tokens")), count(usage.get("completion_tokens"))
    )
