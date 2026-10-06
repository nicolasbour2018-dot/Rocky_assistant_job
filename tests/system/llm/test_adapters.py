"""The adapter of each call type, read from the settings (decision G4, Q24, Q25)."""

from __future__ import annotations

from rocky.system.config import CallType, LlmSettings, ModelChoice, Provider
from rocky.system.llm import (
    AnthropicModel,
    GeminiModel,
    MistralModel,
    OpenAiModel,
    adapter_for,
    adapter_of,
)


def test_each_provider_has_its_adapter() -> None:
    adapters = {
        provider: adapter_of(ModelChoice(provider, "m"), "k") for provider in Provider
    }

    assert isinstance(adapters[Provider.GEMINI], GeminiModel)
    assert isinstance(adapters[Provider.ANTHROPIC], AnthropicModel)
    assert isinstance(adapters[Provider.OPENAI], OpenAiModel)
    assert isinstance(adapters[Provider.MISTRAL], MistralModel)
    assert all(adapter.name == "m" for adapter in adapters.values())


def test_a_call_type_gets_its_own_model_with_its_provider_key() -> None:
    settings = LlmSettings(
        overrides={
            CallType.ASSISTANT: ModelChoice(Provider.ANTHROPIC, "claude-sonnet-5-5")
        },
        keys={Provider.GEMINI: "g", Provider.ANTHROPIC: "a"},
    )

    assistant = adapter_for(settings, CallType.ASSISTANT)
    letter = adapter_for(settings, CallType.LETTER)

    assert (assistant.provider, assistant.name) == (
        Provider.ANTHROPIC,
        "claude-sonnet-5-5",
    )
    assert (letter.provider, letter.name) == (Provider.GEMINI, "gemini-3.5-flash-lite")
