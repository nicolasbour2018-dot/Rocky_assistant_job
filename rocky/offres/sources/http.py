"""Public HTTP adapter of the sources: ordinary browser headers, a pause between requests, no retry.

Collection rule (``docs/decisions/C1-sources.md``, Q5): an anti-bot signal (HTTP 403 or 429, a DataDome or
Cloudflare challenge) raises ``SourceRefusedError`` and nothing else is tried. Error reasons never quote the URL nor its
parameters: API keys travel in some query strings.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx2

from rocky.offres.sources.model import (
    NotFoundError,
    SourceFailedError,
    SourceRefusedError,
)

logger = logging.getLogger(__name__)

# httpx2 logs every request URL at INFO level, query string included (Adzuna keys): keep it quiet.
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore2").setLevel(logging.WARNING)

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}
REFUSAL_STATUSES = {403, 429}
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PAUSE_SECONDS = 1.0

type Params = Mapping[str, str | int | float]


def is_challenge(response: httpx2.Response) -> bool:
    """A Cloudflare challenge, whatever its status.

    DataDome answers its challenges with HTTP 403; its ``x-datadome: protected`` header also marks the answers
    it lets through, so that header is not a refusal by itself.
    """
    return response.headers.get("cf-mitigated", "").lower() == "challenge"


class PublicHttp:
    """GET and POST to public endpoints, with at least ``pause_seconds`` between two requests to one host."""

    def __init__(
        self,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        pause_seconds: float = DEFAULT_PAUSE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx2.Client(
            transport=transport,
            headers=BROWSER_HEADERS,
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        self._pause = pause_seconds
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def get_text(
        self,
        label: str,
        url: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        return self._send(label, "GET", url, params=params, headers=headers).text

    def get_json(
        self,
        label: str,
        url: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._send(
            label, "GET", url, params=params, headers=_json_headers(headers)
        )
        return _json(label, response)

    def post_json(
        self,
        label: str,
        url: str,
        payload: object,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._send(
            label, "POST", url, json=payload, headers=_json_headers(headers)
        )
        return _json(label, response)

    def post_form(
        self,
        label: str,
        url: str,
        form: Mapping[str, str],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._send(
            label, "POST", url, data=dict(form), headers=_json_headers(headers)
        )
        return _json(label, response)

    def _send(
        self,
        label: str,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
        json: object = None,
        data: dict[str, str] | None = None,
    ) -> httpx2.Response:
        self._wait_for(urlsplit(url).hostname or "")
        try:
            response = self._client.request(
                method,
                url,
                params=dict(params) if params else None,
                headers=dict(headers) if headers else None,
                json=json,
                data=data,
            )
        except httpx2.TimeoutException as error:
            raise SourceFailedError(
                f"{label} ne répond pas (délai dépassé)."
            ) from error
        except httpx2.DecodingError as error:
            raise SourceFailedError(
                f"{label} a renvoyé une réponse illisible."
            ) from error
        except httpx2.HTTPError as error:
            # The class helps diagnose; the message may quote the URL (and its keys), so it is not logged.
            logger.warning("%s request failed: %s", label, type(error).__name__)
            raise SourceFailedError(
                f"{label} est injoignable (erreur réseau)."
            ) from error
        if response.status_code in REFUSAL_STATUSES or is_challenge(response):
            raise SourceRefusedError(
                f"Refusé par {label} : la plateforme bloque les requêtes automatiques "
                f"(HTTP {response.status_code})."
            )
        if response.status_code == 404:
            raise NotFoundError(f"{label} n'a pas de page à cette adresse (HTTP 404).")
        if response.status_code >= 400:
            raise SourceFailedError(
                f"{label} a répondu par une erreur (HTTP {response.status_code})."
            )
        return response

    def _wait_for(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            remaining = self._pause - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()


def _json_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {"Accept": "application/json", **(headers or {})}


def _json(label: str, response: httpx2.Response) -> Any:
    """The decoded body; ``None`` for an empty one (France Travail answers 204 when nothing matches)."""
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise SourceFailedError(f"{label} a renvoyé une réponse illisible.") from error
