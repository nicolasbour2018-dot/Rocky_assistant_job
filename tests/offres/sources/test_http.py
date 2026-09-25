from __future__ import annotations

import logging

import httpx2
import pytest

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    NotFoundError,
    SourceFailedError,
    SourceRefusedError,
)
from tests.offres.sources.replay import Replay, answer

URL = "https://jobs.example/search"
ROUTE = ("GET", "/search")
KEY = "k-123-secret"


def get(replay: Replay) -> object:
    return replay.http().get_json("Exemple", URL, params={"app_key": KEY})


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_status_is_a_refusal_and_is_never_retried(status: int) -> None:
    replay = Replay({ROUTE: answer(status=status)})

    with pytest.raises(SourceRefusedError) as error:
        get(replay)

    assert error.value.reason == (
        "Refusé par Exemple : la plateforme bloque les requêtes automatiques "
        f"(HTTP {status})."
    )
    assert len(replay.requests) == 1


def test_a_cloudflare_challenge_is_a_refusal_whatever_its_status() -> None:
    replay = Replay({ROUTE: answer(status=503, headers={"cf-mitigated": "challenge"})})

    with pytest.raises(SourceRefusedError):
        get(replay)


def test_the_datadome_marker_alone_is_not_a_refusal() -> None:
    # Apec marks every answer DataDome lets through with this header (recorded on 25/09/2026).
    replay = Replay({ROUTE: answer("[]", headers={"x-datadome": "protected"})})

    assert get(replay) == []


def test_a_missing_page_is_a_readable_failure() -> None:
    replay = Replay({ROUTE: answer(status=404)})

    with pytest.raises(NotFoundError, match=r"HTTP 404"):
        get(replay)


def test_a_server_error_is_a_failure_that_never_quotes_the_address() -> None:
    replay = Replay({ROUTE: answer(status=500)})

    with pytest.raises(SourceFailedError) as error:
        get(replay)

    assert error.value.reason == "Exemple a répondu par une erreur (HTTP 500)."
    assert KEY not in error.value.reason


def test_an_unreadable_body_is_a_failure() -> None:
    replay = Replay({ROUTE: answer("<html>")})

    with pytest.raises(SourceFailedError, match="réponse illisible"):
        get(replay)


def test_an_empty_body_is_no_data() -> None:
    replay = Replay({ROUTE: answer(status=204)})

    assert get(replay) is None


def raise_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out", request=request)


def raise_network_error(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)


def test_a_timeout_is_a_failure() -> None:
    replay = Replay({ROUTE: raise_timeout})

    with pytest.raises(SourceFailedError, match="délai dépassé"):
        get(replay)


def test_a_network_error_is_logged_by_class_without_the_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    replay = Replay({ROUTE: raise_network_error})

    with caplog.at_level(logging.DEBUG), pytest.raises(SourceFailedError) as error:
        get(replay)

    assert error.value.reason == "Exemple est injoignable (erreur réseau)."
    assert "ConnectError" in caplog.text
    assert KEY not in caplog.text
    assert KEY not in error.value.reason


def test_requests_to_one_host_are_paused() -> None:
    now = [100.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    replay = Replay({ROUTE: answer("[]"), ("GET", "/other"): answer("[]")})
    http = PublicHttp(
        transport=httpx2.MockTransport(replay._handle),
        pause_seconds=2.0,
        clock=lambda: now[0],
        sleep=sleep,
    )

    http.get_json("Exemple", URL)
    now[0] += 0.5
    http.get_json("Exemple", URL)
    http.get_json("Autre", "https://other.example/other")

    assert waits == [1.5]
