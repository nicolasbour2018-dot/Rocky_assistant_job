"""The Rocky workstation: the program run on the user's computer that opens a visible browser (decisions D5, E5).

The application runs in Docker and cannot open a window on the computer: it hands the workstation a request over HTTP
on the loopback, with everything it needs (no ticket, no route of Rocky open to the workstation). Here: what they
exchange, and the application's client. The workstation itself is ``workstation_host.py`` (command ``rocky-poste``).

Two uses:
- the **lecture assistée** (decision E5): open a posting in a tab (``/ouvrir``), the user passes any challenge
  themselves, then hand back the page as it is shown (``/lire``);
- the **prefilling** of a form (decision D5, Q1). DORMANT since the acceptance of 04/10 (it failed on 2 real postings
  out of 2): kept and tested, called only when ``candidatures.web.PREFILL_ENABLED`` is True.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx2

TIMEOUT_SECONDS = 90.0  # opening the page (60 s at most) and filling or reading it
PREFILL_PATH = "/preremplir"
OPEN_PATH = "/ouvrir"
READ_PATH = "/lire"
# A page shown is read whole, as large as a page read by Rocky itself (``offres.sources.http.MAX_PAGE_BYTES``).
MAX_PAGE_BYTES = 3_000_000
MAX_TAB_LENGTH = 64

# What the workstation can fill (Q4), with the label shown to the user and in its report.
FIELDS: Mapping[str, str] = {
    "full_name": "Nom complet",
    "email": "E-mail",
    "phone": "Téléphone",
    "city": "Ville",
    "postal_code": "Code postal",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "portfolio": "Portfolio",
    "message": "Message d'accompagnement",
}
FILE_KINDS: Mapping[str, str] = {"cv": "CV", "letter": "Lettre"}

NOT_RUNNING = "Le poste Rocky ne répond pas : lance « uv run rocky-poste » sur ton ordinateur, puis réessaie."


class WorkstationUnavailableError(Exception):
    """The workstation did not do what it was asked; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class JobFile:
    kind: str  # a key of FILE_KINDS
    name: str  # the file name the recruiter sees
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class PrefillJob:
    """A form to prefill: its address, the values (keys of FIELDS) and the files to drop in it."""

    target_url: str
    fields: tuple[tuple[str, str], ...]
    files: tuple[JobFile, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "target_url": self.target_url,
            "fields": [[key, value] for key, value in self.fields],
            "files": [
                {
                    "kind": f.kind,
                    "name": f.name,
                    "sha256": f.sha256,
                    "content": base64.b64encode(f.content).decode(),
                }
                for f in self.files
            ],
        }

    @classmethod
    def from_json(cls, data: Any) -> PrefillJob:
        """The job as sent; raises ``ValueError`` (with its reason) for anything malformed or altered."""
        if not isinstance(data, dict):
            raise ValueError("a job is an object")
        target = data.get("target_url")
        if not isinstance(target, str) or not target_is_valid(target):
            raise ValueError("the address of the form is not http(s)")
        fields = []
        for item in data.get("fields", []):
            if (
                not isinstance(item, list)
                or len(item) != 2
                or item[0] not in FIELDS
                or not isinstance(item[1], str)
            ):
                raise ValueError(f"unknown field {item!r}")
            fields.append((item[0], item[1]))
        files = []
        for item in data.get("files", []):
            if not isinstance(item, dict) or item.get("kind") not in FILE_KINDS:
                raise ValueError("unknown file kind")
            name = item.get("name")
            if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                raise ValueError("invalid file name")
            try:
                content = base64.b64decode(str(item.get("content")), validate=True)
            except binascii.Error as error:
                raise ValueError("file content is not base64") from error
            found = JobFile(item["kind"], name, content)
            if found.sha256 != item.get("sha256"):
                raise ValueError(f"file {name} does not match its hash")
            files.append(found)
        return cls(target, tuple(fields), tuple(files))


@dataclass(frozen=True)
class PrefillReport:
    """What the workstation did: the labels filled, and what is left to the user with its reason."""

    filled: tuple[str, ...]
    missing: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"filled": list(self.filled), "missing": list(self.missing)}

    @classmethod
    def from_json(cls, data: Any) -> PrefillReport:
        if not isinstance(data, dict):
            raise ValueError("a report is an object")
        return cls(_strings(data.get("filled")), _strings(data.get("missing")))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("a report lists strings")
    return tuple(value)


@dataclass(frozen=True)
class ShownPage:
    """A page as the workstation's browser shows it: its address now (the user may have moved) and its HTML."""

    url: str
    html: str

    def to_json(self) -> dict[str, Any]:
        return {"url": self.url, "html": self.html}

    @classmethod
    def from_json(cls, data: Any) -> ShownPage:
        if not isinstance(data, dict):
            raise ValueError("a page is an object")
        url, page_html = data.get("url"), data.get("html")
        if not isinstance(url, str) or not isinstance(page_html, str):
            raise ValueError("a page has an address and its HTML")
        return cls(url, page_html)


def url_to_open(data: Any) -> str:
    """The address of ``{"url": …}``; raises ``ValueError`` unless it is http(s)."""
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not target_is_valid(url):
        raise ValueError("the address of the page is not http(s)")
    return url


def tab_to_read(data: Any) -> str:
    """The tab of ``{"tab": …}``; raises ``ValueError`` for anything else."""
    tab = data.get("tab") if isinstance(data, dict) else None
    if not isinstance(tab, str) or not 0 < len(tab) <= MAX_TAB_LENGTH:
        raise ValueError("unknown tab")
    return tab


def target_is_valid(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


class Workstation(Protocol):
    def open_page(self, url: str) -> str:
        """``url`` opened in a tab of the visible browser; the tab is named by the token returned. Raises
        ``WorkstationUnavailableError``."""
        ...

    def read_page(self, tab: str) -> ShownPage:
        """The page shown in ``tab`` now. Raises ``WorkstationUnavailableError``."""
        ...

    def prefill(self, job: PrefillJob) -> PrefillReport:
        """DORMANT. The form opened and prefilled in a visible browser; raises ``WorkstationUnavailableError``."""
        ...


class WorkstationClient:
    """The application's side: one request per gesture, answered once the workstation is done."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout_seconds

    def open_page(self, url: str) -> str:
        body = self._post(OPEN_PATH, {"url": url}, "n'a pas pu ouvrir la page")
        tab = body.get("tab") if isinstance(body, dict) else None
        if not isinstance(tab, str) or not tab:
            raise WorkstationUnavailableError("Réponse illisible du poste Rocky.")
        return tab

    def read_page(self, tab: str) -> ShownPage:
        body = self._post(READ_PATH, {"tab": tab}, "n'a pas pu lire la page")
        try:
            return ShownPage.from_json(body)
        except ValueError as error:
            raise WorkstationUnavailableError(
                "Réponse illisible du poste Rocky."
            ) from error

    def prefill(self, job: PrefillJob) -> PrefillReport:
        body = self._post(PREFILL_PATH, job.to_json(), "a refusé le formulaire")
        try:
            return PrefillReport.from_json(body)
        except ValueError as error:
            raise WorkstationUnavailableError(
                "Réponse illisible du poste Rocky."
            ) from error

    def _post(self, path: str, payload: dict[str, Any], failed: str) -> Any:
        """The JSON answer of the workstation; ``failed`` says what it could not do (« Le poste Rocky … »)."""
        try:
            with httpx2.Client(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = client.post(self._base_url + path, json=payload)
        except httpx2.TimeoutException as error:
            raise WorkstationUnavailableError(
                "Le poste Rocky n'a pas répondu à temps : regarde sa fenêtre et son terminal."
            ) from error
        except httpx2.TransportError as error:
            raise WorkstationUnavailableError(NOT_RUNNING) from error
        try:
            body = response.json()
        except ValueError as error:
            raise WorkstationUnavailableError(
                f"Réponse illisible du poste Rocky (HTTP {response.status_code})."
            ) from error
        if response.status_code != 200:
            reason = body.get("error") if isinstance(body, dict) else None
            raise WorkstationUnavailableError(
                f"Le poste Rocky {failed} : {reason or f'HTTP {response.status_code}'}."
            )
        return body
