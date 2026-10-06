"""The language models (decisions C3 and G4): one port, one adapter per provider, the model of each call type."""

from __future__ import annotations

import httpx2

from rocky.system.config import CallType, LlmSettings, ModelChoice, Provider
from rocky.system.llm.anthropic import AnthropicModel
from rocky.system.llm.chat_completions import MistralModel, OpenAiModel
from rocky.system.llm.gemini import GeminiModel
from rocky.system.llm.port import (
    TIMEOUT_SECONDS,
    Adapter,
    Completion,
    HttpAdapter,
    JsonModel,
    LlmUnavailableError,
    Usage,
)

__all__ = [
    "Adapter",
    "AnthropicModel",
    "Completion",
    "GeminiModel",
    "JsonModel",
    "LlmUnavailableError",
    "MistralModel",
    "OpenAiModel",
    "Usage",
    "adapter_for",
    "adapter_of",
]

ADAPTERS: dict[Provider, type[HttpAdapter]] = {
    Provider.GEMINI: GeminiModel,
    Provider.ANTHROPIC: AnthropicModel,
    Provider.OPENAI: OpenAiModel,
    Provider.MISTRAL: MistralModel,
}


def adapter_of(
    choice: ModelChoice,
    api_key: str | None,
    *,
    transport: httpx2.BaseTransport | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> Adapter:
    """The adapter of ``choice``; without a key it says, at each call, that the model is not configured."""
    return ADAPTERS[choice.provider](
        choice.name, api_key, transport=transport, timeout_seconds=timeout_seconds
    )


def adapter_for(settings: LlmSettings, call_type: CallType) -> Adapter:
    """The model the settings give to ``call_type``, with its provider's key."""
    choice = settings.choice(call_type)
    return adapter_of(choice, settings.key(choice.provider))
