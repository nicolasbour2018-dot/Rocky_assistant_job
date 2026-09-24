from __future__ import annotations

import io
from uuid import uuid4

from sqlalchemy import Engine, func, select

from rocky.system.auth.admin import invite
from rocky.system.auth.sql import accounts
from rocky.system.auth.usecases import MailKind
from tests.system.auth.fakes import FakeClock, RecordingMailer


def run(
    engine: Engine, mailer: RecordingMailer, email: str, *, print_link: bool = False
) -> tuple[int, str]:
    out = io.StringIO()
    code = invite(
        engine,
        email=email,
        public_url="http://127.0.0.1:8000",
        mailer=mailer,
        print_link=print_link,
        out=out,
        clock=FakeClock(),
    )
    return code, out.getvalue()


def count_accounts(engine: Engine, email: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).where(accounts.c.email == email)
            ).scalar_one()
        )


def test_invite_sends_the_activation_e_mail(migrated_engine: Engine) -> None:
    mailer, email = RecordingMailer(), f"{uuid4().hex}@example.fr"

    code, output = run(migrated_engine, mailer, email)

    assert code == 0
    assert f"Invitation envoyée à {email}" in output
    [mail] = mailer.sent
    assert (mail.recipient, mail.kind) == (email, MailKind.INVITATION)
    assert mail.link.startswith("http://127.0.0.1:8000/activation?jeton=")
    assert count_accounts(migrated_engine, email) == 1


def test_print_link_shows_the_link_without_sending(migrated_engine: Engine) -> None:
    mailer = RecordingMailer()

    code, output = run(
        migrated_engine, mailer, f"{uuid4().hex}@example.fr", print_link=True
    )

    assert code == 0
    assert "http://127.0.0.1:8000/activation?jeton=" in output
    assert mailer.sent == []


def test_a_mail_outage_keeps_the_account_and_says_so(migrated_engine: Engine) -> None:
    mailer, email = RecordingMailer(), f"{uuid4().hex}@example.fr"
    mailer.fail = True

    code, output = run(migrated_engine, mailer, email)

    assert code == 1
    assert "l'e-mail n'est pas parti" in output
    assert count_accounts(migrated_engine, email) == 1


def test_invalid_address_is_reported(migrated_engine: Engine) -> None:
    code, output = run(migrated_engine, RecordingMailer(), "nicolas")

    assert code == 2
    assert "adresse e-mail valide" in output
