"""Anthropic adapter on a mocked transport: no network, the key never in a reason nor in the logs (decision G4)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx2
import pytest

from rocky.system.llm import AnthropicModel, LlmUnavailableError, Usage
from rocky.system.llm.anthropic import structured

KEY = "sk-ant-test-secret-123"
SCHEMA = {
    "type": "object",
    "properties": {
        "missions": {"type": "string", "maxLength": 400},
        "points": {
            "type": "array",
            "items": {"type": "object", "properties": {"texte": {"type": "string"}}},
            "minItems": 2,
            "maxItems": 5,
        },
    },
    "required": ["missions"],
}


def model(
    handler: Callable[[httpx2.Request], httpx2.Response], key: str | None = KEY
) -> AnthropicModel:
    return AnthropicModel(
        "claude-sonnet-5-5", key, transport=httpx2.MockTransport(handler)
    )


def reply(
    payload: object, status: int = 200
) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda request: httpx2.Response(status, json=payload)


def answer(text: str, **message: object) -> dict[str, object]:
    """A Messages API answer as documented: content blocks, stop reason, usage."""
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 200, "output_tokens": 40},
        **message,
    }


def test_the_request_asks_for_json_shaped_by_the_schema() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=answer('{"missions": "Analyser"}'))

    completion = model(handler).complete("consigne", "annonce", SCHEMA)

    assert completion.value == {"missions": "Analyser"}
    assert completion.usage == Usage(input_tokens=200, output_tokens=40)
    request = sent[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == KEY
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == "consigne"
    assert body["messages"] == [{"role": "user", "content": "annonce"}]
    assert body["max_tokens"] == 16000
    assert body["output_config"]["format"]["type"] == "json_schema"
    # The current models refuse sampling parameters and forced tool use.
    assert "temperature" not in body
    assert "tool_choice" not in body


def test_the_schema_is_closed_and_loses_the_bounds_the_api_refuses() -> None:
    assert structured(SCHEMA) == {
        "type": "object",
        "properties": {
            "missions": {"type": "string"},
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"texte": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        },
        "required": ["missions"],
        "additionalProperties": False,
    }


def test_the_thinking_blocks_are_not_read_and_cached_tokens_are_input() -> None:
    payload = answer(
        '{"missions": "A"}',
        content=[
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": '{"missions": "A"}'},
        ],
        usage={
            "input_tokens": 10,
            "cache_creation_input_tokens": 5,
            "cache_read_input_tokens": 100,
            "output_tokens": 7,
        },
    )

    completion = model(reply(payload)).complete("c", "a", SCHEMA)

    assert completion.value == {"missions": "A"}
    assert completion.usage == Usage(input_tokens=115, output_tokens=7)


def test_without_a_key_nothing_is_sent() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    with pytest.raises(LlmUnavailableError) as error:
        model(handler, key=None).complete_json("c", "a", SCHEMA)

    assert (
        error.value.reason
        == "Le modèle de langage n'est pas configuré (clé Anthropic absente)."
    )
    assert sent == []


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "La clé Anthropic est refusée (HTTP 401)."),
        (429, "Quota Anthropic atteint pour le moment (HTTP 429)."),
        (529, "Anthropic est en panne (HTTP 529)."),
        (400, "Anthropic a refusé la demande (HTTP 400)."),
    ],
)
def test_a_refusal_gives_its_reason(status: int, reason: str) -> None:
    payload = {"type": "error", "error": {"type": "x", "message": "y"}}

    with pytest.raises(LlmUnavailableError) as error:
        model(reply(payload, status)).complete_json("c", "a", SCHEMA)

    assert error.value.reason == reason


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            answer("", stop_reason="refusal", content=[]),
            "Anthropic a refusé de répondre (refus).",
        ),
        (
            answer('{"missions": "A', stop_reason="max_tokens"),
            "Anthropic s'est arrêté avant la fin (max_tokens).",
        ),
        (answer("", content=[]), "Anthropic n'a donné aucune réponse."),
        (answer("pas du JSON"), "Anthropic a renvoyé une réponse illisible."),
        ({"content": "texte"}, "Anthropic n'a donné aucune réponse."),
        (["liste"], "Anthropic n'a donné aucune réponse."),
    ],
)
def test_an_unusable_answer_gives_its_reason(payload: object, reason: str) -> None:
    with pytest.raises(LlmUnavailableError) as error:
        model(reply(payload)).complete_json("c", "a", SCHEMA)

    assert error.value.reason == reason


def test_a_network_error_never_logs_the_key(caplog: pytest.LogCaptureFixture) -> None:
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(
            f"cannot reach {request.url} with {request.headers}", request=request
        )

    with caplog.at_level(logging.DEBUG), pytest.raises(LlmUnavailableError) as error:
        model(unreachable).complete_json("c", "a", SCHEMA)

    assert error.value.reason == "Anthropic est injoignable (erreur réseau)."
    assert KEY not in caplog.text
