"""Anthropic Messages API: JSON constrained by the schema (``output_config.format``), decision G4 (Q23).

No SDK (Q23): one POST, like the other adapters. The current models reject sampling parameters and forced tool use:
the answer is shaped by structured outputs alone. Their schemas take ``additionalProperties: false`` on every object
and no numeric or length bound: ``structured`` adapts the caller's schema, whose shape the caller still checks.
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

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
# Non-streaming: enough for any answer Rocky asks for, below the HTTP timeouts.
MAX_TOKENS = 16000
# Bounds the structured outputs do not take (the caller checks the answer anyway).
UNSUPPORTED = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
    }
)


class AnthropicModel(HttpAdapter):
    provider = Provider.ANTHROPIC

    def complete(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Completion:
        key = self.key()
        body = {
            "model": self.name,
            "max_tokens": MAX_TOKENS,
            "system": instructions,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "format": {"type": "json_schema", "schema": structured(schema)}
            },
        }
        data = self.post(
            API_URL, body, {"x-api-key": key, "anthropic-version": API_VERSION}
        )
        return Completion(self._answer(data), _usage(data))

    def _answer(self, data: Any) -> Any:
        if not isinstance(data, dict):
            raise LlmUnavailableError(self.no_answer())
        stop = data.get("stop_reason")
        if stop == "refusal":
            raise LlmUnavailableError("Anthropic a refusé de répondre (refus).")
        if stop not in (None, "end_turn"):
            raise LlmUnavailableError(self.stopped(stop))
        content = data.get("content")
        if not isinstance(content, list):
            raise LlmUnavailableError(self.no_answer())
        # Thinking blocks come before the answer: only the text blocks are read.
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text:
            raise LlmUnavailableError(self.no_answer())
        return self.decoded(text)


def structured(schema: Mapping[str, Any]) -> dict[str, Any]:
    """``schema`` as the structured outputs take it: closed objects, no bounds, at most one required item."""
    adapted: dict[str, Any] = {}
    for key, value in schema.items():
        if key in UNSUPPORTED or (key == "minItems" and value not in (0, 1)):
            continue
        adapted[key] = _structured_value(value)
    if adapted.get("type") == "object":
        adapted["additionalProperties"] = False
    return adapted


def _structured_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return structured(value)
    if isinstance(value, list):
        return [_structured_value(item) for item in value]
    return value


def _usage(data: Any) -> Usage:
    """Tokens read from the prompt cache are input too."""
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return Usage()
    read = count(usage.get("input_tokens"))
    if read is not None:
        read += sum(
            count(usage.get(name)) or 0
            for name in ("cache_creation_input_tokens", "cache_read_input_tokens")
        )
    return Usage(read, count(usage.get("output_tokens")))
