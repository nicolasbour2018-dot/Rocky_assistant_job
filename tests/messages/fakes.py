"""Shared test adapters of the module ``messages``: recorded Gmail answers, a fake Gmail, an account."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
from cryptography.fernet import Fernet
from sqlalchemy import Connection

from rocky.messages.model import GmailError, MailReader, MessageUnreadableError
from rocky.messages.oauth import GoogleOAuth
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import GmailSettings
from rocky.system.crypto import TokenCipher

DATA = Path(__file__).parent / "data"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
REPLY_ID, ALERT_ID, LATIN_ID = (
    "18f0a1b2c3d4e5f6",
    "18f0b2c3d4e5f607",
    "18f0c3d4e5f60718",
)
# A key made for the tests: the sealed tokens of one run open with it.
KEY = Fernet.generate_key().decode()
GMAIL = GmailSettings(
    client_id="client.apps", client_secret="secret-client", secret_key=KEY
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def recorded(name: str) -> Any:
    return json.loads((DATA / name).read_text())


def raw_message(name: str) -> dict[str, Any]:
    """A recorded message, a fresh copy each time (tests change it)."""
    data = recorded(name)
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def all_messages() -> dict[str, dict[str, Any]]:
    return {
        REPLY_ID: raw_message("message_reply.json"),
        ALERT_ID: raw_message("message_alert_html_only.json"),
        LATIN_ID: raw_message("message_latin1_attachment.json"),
    }


def cipher() -> TokenCipher:
    return TokenCipher(KEY)


@dataclass
class FakeReader:
    """``MailReader``: the identifiers each query gives, the messages it serves, and what was asked."""

    replies: list[str] = field(default_factory=lambda: [REPLY_ID, LATIN_ID])
    alerts: list[str] = field(default_factory=lambda: [ALERT_ID, REPLY_ID])
    messages: dict[str, dict[str, Any]] = field(default_factory=all_messages)
    # A query kind ("replies", "alerts") or a message id that fails, with its error.
    failures: dict[str, BaseException] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    gets: list[str] = field(default_factory=list)

    def list_ids(self, query: str) -> list[str]:
        self.queries.append(query)
        kind = "alerts" if query.startswith("from:(") else "replies"
        if kind in self.failures:
            raise self.failures[kind]
        return list(self.alerts if kind == "alerts" else self.replies)

    def get(self, gmail_id: str) -> dict[str, object]:
        self.gets.append(gmail_id)
        if gmail_id in self.failures:
            raise self.failures[gmail_id]
        return copy.deepcopy(self.messages[gmail_id])


@dataclass
class FakeGmail:
    """``Gmail`` serving one reader; ``refusal`` is raised when a reader is opened (a refused refresh token)."""

    reader_: FakeReader = field(default_factory=FakeReader)
    refusal: GmailError | None = None
    tokens: list[str] = field(default_factory=list)

    @contextmanager
    def reader(self, refresh_token: str) -> Iterator[MailReader]:
        self.tokens.append(refresh_token)
        if self.refusal is not None:
            raise self.refusal
        yield self.reader_


def unreadable(reason: str = "message 18f incomplet") -> MessageUnreadableError:
    return MessageUnreadableError(reason)


def new_account(connection: Connection) -> int:
    auth = SqlAuthStore(connection)
    account_id = auth.create_account(f"{uuid4().hex}@example.fr", NOW)
    auth.activate_account(account_id, "hash", NOW)
    return account_id


type Handler = Callable[[httpx2.Request], httpx2.Response]


def json_answer(data: object, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, json=data)


class Google:
    """A fake Google: answers by (method, address without query), and keeps every request."""

    def __init__(self, routes: dict[tuple[str, str], Handler]) -> None:
        self.routes = routes
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        url = str(request.url).split("?")[0]
        return self.routes[(request.method, url)](request)

    def oauth(self) -> GoogleOAuth:
        return GoogleOAuth(GMAIL, transport=httpx2.MockTransport(self))

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)
