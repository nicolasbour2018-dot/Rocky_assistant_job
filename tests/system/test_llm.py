"""Gemini adapter on a mocked transport: no network, the key never in a reason nor in the logs."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx2
import pytest

from rocky.system.config import LlmSettings
from rocky.system.llm import GeminiModel, LlmUnavailableError

KEY = "AIza-test-secret-123"
SCHEMA = {"type": "object", "properties": {"missions": {"type": "string"}}}


def model(
    handler: Callable[[httpx2.Request], httpx2.Response], key: str | None = KEY
) -> GeminiModel:
    return GeminiModel(
        LlmSettings(api_key=key, model="gemini-3.5-flash-lite"),
        transport=httpx2.MockTransport(handler),
    )


def reply(
    payload: object, status: int = 200
) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda request: httpx2.Response(status, json=payload)


def answer(text: str, **candidate: object) -> dict[str, object]:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": "STOP",
                **candidate,
            }
        ]
    }


def test_without_a_key_nothing_is_sent() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    with pytest.raises(LlmUnavailableError, match="n'est pas configuré"):
        model(handler, key=None).complete_json("consigne", "annonce", SCHEMA)

    assert sent == []


def test_a_key_with_a_pasted_character_is_a_reason_not_a_crash() -> None:
    with pytest.raises(LlmUnavailableError, match="caractère invalide"):
        model(reply({}), key="AIza-clé").complete_json("consigne", "annonce", SCHEMA)


def test_the_request_asks_for_json_with_the_schema() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=answer('{"missions": "Analyser"}'))

    result = model(handler).complete_json("consigne", "annonce", SCHEMA)

    assert result == {"missions": "Analyser"}
    request = sent[0]
    assert request.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url)
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": "consigne"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "annonce"}]}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA


def test_the_reasoning_parts_of_a_thinking_model_are_not_read() -> None:
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Je réfléchis…", "thought": True},
                        {"text": '{"missions": "A"}'},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    assert model(reply(payload)).complete_json("c", "a", SCHEMA) == {"missions": "A"}


@pytest.mark.parametrize(
    ("status", "payload", "reason"),
    [
        (
            400,
            {"error": {"details": [{"reason": "API_KEY_INVALID"}]}},
            "La clé Gemini est refusée (HTTP 400).",
        ),
        (403, {"error": {}}, "La clé Gemini est refusée (HTTP 403)."),
        (429, {"error": {}}, "Quota Gemini atteint pour le moment (HTTP 429)."),
        (503, {"error": {}}, "Gemini est en panne (HTTP 503)."),
        (
            400,
            {"error": {"message": "Invalid JSON payload"}},
            "Gemini a refusé la demande (HTTP 400).",
        ),
    ],
)
def test_a_refusal_gives_its_reason(status: int, payload: object, reason: str) -> None:
    with pytest.raises(LlmUnavailableError) as error:
        model(reply(payload, status)).complete_json("c", "a", SCHEMA)

    assert error.value.reason == reason


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {"promptFeedback": {"blockReason": "SAFETY"}},
            "Gemini a bloqué la demande (SAFETY).",
        ),
        ({"candidates": []}, "Gemini n'a donné aucune réponse."),
        (
            answer('{"missions": "A', finishReason="MAX_TOKENS"),
            "Gemini s'est arrêté avant la fin (MAX_TOKENS).",
        ),
        (answer("pas du JSON"), "Gemini a renvoyé une réponse illisible."),
    ],
)
def test_an_unusable_answer_gives_its_reason(payload: object, reason: str) -> None:
    with pytest.raises(LlmUnavailableError) as error:
        model(reply(payload)).complete_json("c", "a", SCHEMA)

    assert error.value.reason == reason


def test_a_timeout_or_a_network_error_is_a_reason_and_never_logs_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(
            f"cannot reach {request.url} with {request.headers}", request=request
        )

    with pytest.raises(LlmUnavailableError, match="délai dépassé"):
        model(timeout).complete_json("c", "a", SCHEMA)
    with caplog.at_level(logging.DEBUG), pytest.raises(LlmUnavailableError) as error:
        model(unreachable).complete_json("c", "a", SCHEMA)

    assert error.value.reason == "Gemini est injoignable (erreur réseau)."
    assert "ConnectError" in caplog.text
    assert KEY not in caplog.text
