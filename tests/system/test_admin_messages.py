"""``rocky-admin messages``: a real collection of an account's Gmail mailboxes, written, then told."""

from __future__ import annotations

import io

from sqlalchemy import Engine

from rocky.messages.service import MessagesService
from rocky.messages.usecases import connect_mailbox
from rocky.system.admin import collect_messages
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import GmailSettings
from tests.messages.fakes import GMAIL, NOW, FakeGmail, cipher, new_account


def run(engine: Engine, email: str, settings: GmailSettings = GMAIL) -> tuple[int, str]:
    out = io.StringIO()
    service = MessagesService(
        engine, settings=settings, clock=lambda: NOW, gmail=FakeGmail()
    )
    code = collect_messages(engine, email=email, service=service, out=out)
    return code, out.getvalue()


def account_with_mailbox(engine: Engine) -> str:
    with engine.begin() as connection:
        account_id = new_account(connection)
        account = SqlAuthStore(connection).get_account(account_id)
    assert account is not None
    connect_mailbox(
        MessagesService(engine, settings=GMAIL, clock=lambda: NOW).storage,
        cipher(),
        account_id=account_id,
        address="camille.dupont@example.com",
        refresh_token="1//r",
        now=NOW,
    )
    return account.email


def test_each_mailbox_is_collected_and_told(migrated_engine: Engine) -> None:
    email = account_with_mailbox(migrated_engine)

    code, output = run(migrated_engine, email)
    again, second = run(migrated_engine, email)

    assert (code, again) == (0, 0)
    assert output == (
        "camille.dupont@example.com : collecte terminée, 3 message(s) trouvé(s), "
        "0 déjà relevé(s), 3 nouveau(x), 0 non écrit(s).\n"
    )
    assert "3 déjà relevé(s), 0 nouveau(x)" in second


def test_an_account_without_mailbox_or_settings_says_so(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        account_id = new_account(connection)
        account = SqlAuthStore(connection).get_account(account_id)
    assert account is not None

    assert run(migrated_engine, account.email) == (
        1,
        f"Aucune boîte Gmail connectée ou libre pour {account.email}.\n",
    )
    code, output = run(migrated_engine, account.email, GmailSettings())
    assert code == 1
    assert output.startswith("Gmail n'est pas configuré")
    assert run(migrated_engine, "personne@example.fr") == (
        1,
        "Aucun compte pour personne@example.fr.\n",
    )
