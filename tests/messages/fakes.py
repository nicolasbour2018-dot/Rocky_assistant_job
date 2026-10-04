"""Shared test adapters of the module ``messages``: recorded Gmail answers, a fake Gmail, an account."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
from cryptography.fernet import Fernet
from sqlalchemy import Connection

from rocky.candidatures.model import Stage
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.usecases import change_stage, prepare_application
from rocky.candidatures.web_common import OffresDecisions
from rocky.messages.model import (
    CollectedMessage,
    GmailError,
    MailReader,
    MessageUnreadableError,
    Query,
    SyncCounts,
    SyncStatus,
    Trigger,
)
from rocky.messages.oauth import GoogleOAuth
from rocky.messages.sql import SqlStorage
from rocky.offres.decisions import application_decision
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore as OffresStore
from rocky.offres.usecases import record_offer
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import GmailSettings
from rocky.system.crypto import TokenCipher
from tests.offres.fakes import Seeker, posting

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


# The classification (E2): a stored message, a sent application, a model that answers in turn.


def store_mail(
    storage: SqlStorage,
    mailbox_id: int,
    *,
    sender: str,
    subject: str,
    body: str = "",
    thread: str | None = None,
    received_at: datetime = NOW,
) -> int:
    """A message written as a collection writes it, in a collection of its own."""
    with storage.transaction() as store:
        mailbox = store.mailbox(mailbox_id)
        assert mailbox is not None
        sync_id = store.start_sync(mailbox, Trigger.MANUAL, NOW, NOW)
        gmail_id = uuid4().hex
        address = parseaddr(sender)[1].lower()
        message_id = store.add_message(
            mailbox,
            CollectedMessage(
                gmail_id=gmail_id,
                thread_id=thread or gmail_id,
                received_at=received_at,
                sender=sender,
                sender_address=address or None,
                recipients="camille@example.com",
                subject=subject,
                snippet=body[:200],
                body_text=body,
                body_html="",
                truncated=False,
                labels=(),
                attachments=(),
                rfc822_id=None,
            ),
            found_by=[Query.REPLIES],
            sync_id=sync_id,
            now=NOW,
        )
        store.finish_sync(
            sync_id,
            status=SyncStatus.COMPLETED,
            reason=None,
            counts=SyncCounts(new=1),
            now=NOW,
        )
    assert message_id is not None
    return message_id


def sent_application(
    connection: Connection,
    seeker: Seeker,
    *,
    company: str,
    title: str,
    external_id: str | None = None,
) -> int:
    """An offer of ``company``, its application prepared then « Envoyée »."""
    offer_id = record_offer(
        OffresStore(connection),
        account_id=seeker.account_id,
        offer=posting(external_id or uuid4().hex, company=company, title=title),
        inputs=scoring_inputs(seeker.profile(connection)),
        origin=Origin.WATCH,
        track_ids=[seeker.tracks["Data"]],
        now=NOW,
        today=NOW.date(),
    ).offer_id
    store = SqlApplicationStore(connection)
    application_id = prepare_application(
        store,
        OffresDecisions(connection),
        account_id=seeker.account_id,
        offer_id=offer_id,
        interest=application_decision(["target_job"]),
        now=NOW,
        today=NOW.date(),
    )
    change_stage(
        store,
        account_id=seeker.account_id,
        application_id=application_id,
        stage=Stage.SENT,
        next_action=None,
        now=NOW,
    )
    return application_id


class ScriptedModel:
    """A language model answering with ``answers`` in turn (an exception is raised), and keeping the prompts."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer
