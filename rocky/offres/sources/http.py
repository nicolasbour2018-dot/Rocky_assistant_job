"""Public HTTP adapter of the sources: ordinary browser headers, a pause between requests, no retry.

Collection rule (``docs/decisions/C1-sources.md``, Q5): an anti-bot signal (HTTP 403 or 429, a DataDome or
Cloudflare challenge) raises ``SourceRefusedError`` and nothing else is tried. Error reasons never quote the URL nor its
parameters: API keys travel in some query strings.

A posting page given by the user (``get_page``, step C2) is read under the same rule, from public hosts only.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx2

from rocky.offres.sources.model import (
    InvalidLinkError,
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
# 999: the status LinkedIn gives to the automated clients it refuses.
REFUSAL_STATUSES = {403, 429, 999}
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PAUSE_SECONDS = 1.0
# A posting page: at most this size, after at most this many redirections.
MAX_PAGE_BYTES = 3_000_000
MAX_REDIRECTS = 5
HTML_TYPES = ("text/html", "application/xhtml+xml")

type Params = Mapping[str, str | int | float]
# Host name → its IP addresses (``socket.getaddrinfo`` by default, replaced by the tests).
type Resolver = Callable[[str], list[str]]


@dataclass(frozen=True)
class Page:
    """A posting page: its address after redirections, and its HTML."""

    url: str
    html: str


def resolve(host: str) -> list[str]:
    """Addresses of ``host``; an unknown name is a wrong link (to correct), not a site out of order."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as error:
        raise InvalidLinkError(
            f"Le site {host} est introuvable (nom de domaine inconnu)."
        ) from error
    return [str(info[4][0]) for info in infos]


def is_public_address(address: str) -> bool:
    """A global unicast address: not loopback, private, link-local, shared, reserved nor multicast."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


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
        resolver: Resolver = resolve,
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
        self._resolver = resolver
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

    def get_page(self, url: str, *, max_bytes: int = MAX_PAGE_BYTES) -> Page:
        """The HTML page of a link given by the user; reasons name the site by its host.

        Redirections are followed one by one, and every host (the first one included) must resolve to public
        addresses only: a link cannot reach the network of the server. Raises ``InvalidLinkError`` for an
        unknown or non-public host, ``SourceRefusedError``, or ``SourceFailedError`` (not a web page, too large,
        too many redirections).
        """
        label = ""
        for _ in range(MAX_REDIRECTS + 1):
            host = urlsplit(url).hostname or ""
            label = host.removeprefix("www.")
            self._check_public(host)
            response = self._send(label, "GET", url, stream=True)
            try:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                return Page(str(response.url), _page_text(label, response, max_bytes))
            finally:
                response.close()
        raise SourceFailedError(
            f"{label} redirige sans fin (plus de {MAX_REDIRECTS} redirections)."
        )

    def _check_public(self, host: str) -> None:
        # An address written in the link is checked as it is, a name through what it resolves to.
        addresses = [host] if _is_ip(host) else self._resolver(host)
        if not addresses or not all(
            is_public_address(address) for address in addresses
        ):
            raise InvalidLinkError(
                f"Le lien vise une adresse privée ou locale ({host}) : Rocky ne lit que des sites publics."
            )

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
        stream: bool = False,
    ) -> httpx2.Response:
        """One request. With ``stream``, redirections are not followed and the body of a success is left unread."""
        self._wait_for(urlsplit(url).hostname or "")
        try:
            request = self._client.build_request(
                method,
                url,
                params=dict(params) if params else None,
                headers=dict(headers) if headers else None,
                json=json,
                data=data,
            )
            response = self._client.send(
                request, stream=stream, follow_redirects=not stream
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
        refused = response.status_code in REFUSAL_STATUSES or is_challenge(response)
        if refused or response.status_code >= 400:
            response.close()
        if refused:
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


def _page_text(label: str, response: httpx2.Response, max_bytes: int) -> str:
    """The HTML of a page answer, read in chunks up to ``max_bytes``."""
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind == "application/pdf":
        raise SourceFailedError(
            f"{label} renvoie un PDF, pas une page web : colle le texte de l'annonce."
        )
    if kind not in HTML_TYPES:
        raise SourceFailedError(
            f"{label} ne renvoie pas une page web ({kind or 'type inconnu'})."
        )
    body = bytearray()
    try:
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise SourceFailedError(
                    f"La page de {label} est trop volumineuse "
                    f"(plus de {max_bytes // 1_000_000} Mo)."
                )
    except httpx2.TimeoutException as error:
        raise SourceFailedError(f"{label} ne répond pas (délai dépassé).") from error
    except httpx2.HTTPError as error:
        logger.warning("%s page read failed: %s", label, type(error).__name__)
        raise SourceFailedError(f"{label} a interrompu l'envoi de la page.") from error
    return bytes(body).decode(response.charset_encoding or "utf-8", errors="replace")


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
