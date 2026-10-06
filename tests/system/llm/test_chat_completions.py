"""OpenAI and Mistral adapters on a mocked transport: no network, the key never in a reason (decision G4)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx2
import pytest

from rocky.system.llm import LlmUnavailableError, MistralModel, OpenAiModel, Usage
from rocky.system.llm.chat_completions import ChatCompletionsModel

KEY = "sk-test-secret-123"
SCHEMA = {"type": "object", "properties": {"missions": {"type": "string"}}}

Handler = Callable[[httpx2.Request], httpx2.Response]


def openai(handler: Handler, key: str | None = KEY) -> OpenAiModel:
    return OpenAiModel("gpt-test", key, transport=httpx2.MockTransport(handler))


def mistral(handler: Handler, key: str | None = KEY) -> MistralModel:
    return MistralModel("mistral-test", key, transport=httpx2.MockTransport(handler))


def reply(payload: object, status: int = 200) -> Handler:
    return lambda request: httpx2.Response(status, json=payload)


def answer(
    content: object, finish: str = "stop", **message: object
) -> dict[str, object]:
    """A chat completion as both providers document it."""
    return {
        "id": "c-1",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, **message},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 90, "completion_tokens": 25, "total_tokens": 115},
    }


@pytest.mark.parametrize(
    ("build", "url", "temperature"),
    [
        (openai, "https://api.openai.com/v1/chat/completions", None),
        (mistral, "https://api.mistral.ai/v1/chat/completions", 0.2),
    ],
)
def test_the_request_asks_for_json_shaped_by_the_schema(
    build: Callable[[Handler], ChatCompletionsModel],
    url: str,
    temperature: float | None,
) -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=answer('{"missions": "Analyser"}'))

    completion = build(handler).complete("consigne", "annonce", SCHEMA)

    assert completion.value == {"missions": "Analyser"}
    assert completion.usage == Usage(input_tokens=90, output_tokens=25)
    request = sent[0]
    assert str(request.url) == url
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["messages"] == [
        {"role": "system", "content": "consigne"},
        {"role": "user", "content": "annonce"},
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "reponse", "schema": SCHEMA, "strict": False},
    }
    assert body.get("temperature") == temperature


def test_an_answer_in_chunks_reads_the_text_ones() -> None:
    content = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "Je pense"}]},
        {"type": "text", "text": '{"missions": '},
        {"type": "text", "text": '"A"}'},
    ]

    assert mistral(reply(answer(content))).complete_json("c", "a", SCHEMA) == {
        "missions": "A"
    }


def test_without_a_key_nothing_is_sent() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    with pytest.raises(LlmUnavailableError, match="clé Mistral absente"):
        mistral(handler, key=None).complete_json("c", "a", SCHEMA)

    assert sent == []


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "La clé OpenAI est refusée (HTTP 401)."),
        (429, "Quota OpenAI atteint pour le moment (HTTP 429)."),
        (500, "OpenAI est en panne (HTTP 500)."),
        (422, "OpenAI a refusé la demande (HTTP 422)."),
    ],
)
def test_a_refusal_gives_its_reason(status: int, reason: str) -> None:
    with pytest.raises(LlmUnavailableError) as error:
        openai(reply({"error": {"message": "x"}}, status)).complete_json(
            "c", "a", SCHEMA
        )

    assert error.value.reason == reason
    assert KEY not in error.value.reason


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            answer(None, refusal="Je ne peux pas."),
            "OpenAI a refusé de répondre (refus).",
        ),
        (
            answer('{"missions": "A', "length"),
            "OpenAI s'est arrêté avant la fin (length).",
        ),
        (answer("", "content_filter"), "OpenAI a bloqué la demande (filtre)."),
        (answer(""), "OpenAI n'a donné aucune réponse."),
        (answer("pas du JSON"), "OpenAI a renvoyé une réponse illisible."),
        ({"choices": []}, "OpenAI n'a donné aucune réponse."),
        ({"choices": [{"message": "texte"}]}, "OpenAI n'a donné aucune réponse."),
    ],
)
def test_an_unusable_answer_gives_its_reason(payload: object, reason: str) -> None:
    with pytest.raises(LlmUnavailableError) as error:
        openai(reply(payload)).complete_json("c", "a", SCHEMA)

    assert error.value.reason == reason
