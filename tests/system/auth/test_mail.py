"""SMTP delivery against a fake smtplib: no network in the tests."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from types import TracebackType
from typing import Any, Self

import pytest

from rocky.system.auth.mail import (
    MailDeliveryError,
    MailNotConfiguredError,
    SmtpMailer,
    compose,
)
from rocky.system.auth.usecases import MailKind, OutgoingMail
from rocky.system.config import SmtpSettings

MAIL = OutgoingMail(
    "nicolas@example.fr", MailKind.INVITATION, "http://x/activation?jeton=t"
)


class FakeSMTP:
    instances: list[FakeSMTP] = []  # noqa: RUF012  (test recorder)
    refuse = False

    def __init__(self, host: str, port: int, **_: Any) -> None:
        self.address = (host, port)
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)
        if FakeSMTP.refuse:
            raise ConnectionRefusedError("refused")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.calls.append("quit")

    def starttls(self, context: ssl.SSLContext) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances, FakeSMTP.refuse = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)


def settings(port: int = 587) -> SmtpSettings:
    return SmtpSettings(
        host="smtp.example",
        port=port,
        sender="Rocky <rocky@example.fr>",
        username="rocky",
        password="secret",
    )


def test_compose_writes_a_french_message_with_the_link() -> None:
    message = compose(MAIL, "Rocky <rocky@example.fr>")

    assert message["To"] == "nicolas@example.fr"
    assert message["Subject"] == "Ton invitation à Rocky"
    assert "http://x/activation?jeton=t" in message.get_content()


def test_starttls_then_login_then_send() -> None:
    SmtpMailer(settings()).send(MAIL)

    [smtp] = FakeSMTP.instances
    assert smtp.address == ("smtp.example", 587)
    assert smtp.calls == ["starttls", "login:rocky", "quit"]
    assert smtp.sent[0]["From"] == "Rocky <rocky@example.fr>"


def test_port_465_uses_implicit_tls() -> None:
    SmtpMailer(settings(port=465)).send(MAIL)

    [smtp] = FakeSMTP.instances
    assert "starttls" not in smtp.calls


def test_unconfigured_smtp_is_an_explicit_error() -> None:
    with pytest.raises(MailNotConfiguredError):
        SmtpMailer(None).send(MAIL)


def test_a_refused_connection_is_reported() -> None:
    FakeSMTP.refuse = True

    with pytest.raises(MailDeliveryError, match=r"smtp\.example:587"):
        SmtpMailer(settings()).send(MAIL)
