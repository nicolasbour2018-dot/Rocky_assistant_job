"""The Rocky workstation: the program run on the user's computer that opens a visible browser (decision D5, Q1).

The application runs in Docker and cannot open a window on the computer: it hands the workstation a form to prefill,
over HTTP on the loopback, with every value and file it needs (no ticket, no route of Rocky open to the
workstation). Here: what they exchange, and the application's client. The workstation itself is
``workstation_host.py`` (command ``rocky-poste``); the lecture assistée (E5) will use it too.
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

TIMEOUT_SECONDS = 90.0  # opening the page (60 s at most) and filling it
PREFILL_PATH = "/preremplir"

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
    """The workstation did not take the form; ``reason`` is shown as is (French)."""

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


def target_is_valid(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


class Workstation(Protocol):
    def prefill(self, job: PrefillJob) -> PrefillReport:
        """The form opened and prefilled in a visible browser; raises ``WorkstationUnavailableError``."""
        ...


class WorkstationClient:
    """The application's side: one request per form, answered once the form is filled."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._url = base_url.rstrip("/") + PREFILL_PATH
        self._transport = transport
        self._timeout = timeout_seconds

    def prefill(self, job: PrefillJob) -> PrefillReport:
        try:
            with httpx2.Client(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = client.post(self._url, json=job.to_json())
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
                f"Le poste Rocky a refusé le formulaire : {reason or f'HTTP {response.status_code}'}."
            )
        try:
            return PrefillReport.from_json(body)
        except ValueError as error:
            raise WorkstationUnavailableError(
                "Réponse illisible du poste Rocky."
            ) from error
