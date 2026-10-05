"""Replay of recorded platform answers (``data/``): no network in the tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx2

from rocky.offres.sources.http import PublicHttp, Resolver

DATA = Path(__file__).parent / "data"
# A global address (not a documentation range, which is not global): no name is ever resolved in the tests.
PUBLIC_ADDRESS = "93.184.215.14"


def public_address(host: str) -> list[str]:
    return [PUBLIC_ADDRESS]


type Route = tuple[str, str]  # (method, path)
# A fresh response per request: the client takes over the response it receives.
type Answer = Callable[[httpx2.Request], httpx2.Response]


def recorded(name: str) -> str:
    """Text of a recorded answer, ``<source>/<file>``."""
    return (DATA / name).read_text()


def recorded_json(name: str) -> object:
    return json.loads(recorded(name))


def answer(
    content: str = "",
    status: int = 200,
    *,
    content_type: str = "application/json",
    headers: Mapping[str, str] | None = None,
) -> Answer:
    return lambda request: httpx2.Response(
        status,
        content=content.encode(),
        headers={"content-type": content_type, **(headers or {})},
    )


def json_answer(
    name: str, status: int = 200, headers: Mapping[str, str] | None = None
) -> Answer:
    return answer(recorded(name), status, headers=headers)


def html_answer(name: str, status: int = 200) -> Answer:
    return answer(recorded(name), status, content_type="text/html")


@dataclass
class Replay:
    """Answers by (method, path); every request is kept for the assertions. An unknown route is a test error."""

    routes: dict[Route, Answer]
    requests: list[httpx2.Request] = field(default_factory=list)

    def http(self, resolver: Resolver | None = None) -> PublicHttp:
        """A client on the recorded answers; host names resolve to a public address unless ``resolver`` says."""
        return PublicHttp(
            transport=httpx2.MockTransport(self._handle),
            pause_seconds=0,
            resolver=resolver or public_address,
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.routes.get((request.method, request.url.path))
        if answer is None:
            raise AssertionError(
                f"unexpected request {request.method} {request.url.path}"
            )
        return answer(request)

    def params(self, index: int = -1) -> dict[str, str]:
        return dict(self.requests[index].url.params)

    def body(self, index: int = -1) -> object:
        return json.loads(self.requests[index].content)
