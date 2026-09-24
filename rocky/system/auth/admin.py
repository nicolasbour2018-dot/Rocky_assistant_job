"""``rocky-admin``: administration commands (accounts are created by invitation only).

Run in the application container: ``docker compose run --rm app rocky-admin invite <email>``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TextIO

from sqlalchemy import Engine

from rocky.system.auth.mail import (
    MailDeliveryError,
    Mailer,
    MailNotConfiguredError,
    SmtpMailer,
)
from rocky.system.auth.rules import InvalidEmailError
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import AlreadyActive, Argon2Hasher, Auth, Clock
from rocky.system.config import load_settings
from rocky.system.db import create_db_engine


def invite(
    engine: Engine,
    *,
    email: str,
    public_url: str,
    mailer: Mailer,
    print_link: bool,
    out: TextIO,
    clock: Clock,
) -> int:
    """Invite ``email``; the e-mail leaves only after the account and its link are committed."""
    try:
        with engine.begin() as connection:
            auth = Auth(
                SqlAuthStore(connection),
                hasher=Argon2Hasher(),
                clock=clock,
                public_url=public_url,
            )
            result = auth.invite(email)
    except InvalidEmailError as error:
        out.write(f"{error}\n")
        return 2
    if isinstance(result, AlreadyActive):
        out.write("Ce compte est déjà actif : rien n'a été envoyé.\n")
        return 1
    if print_link:
        out.write(
            f"Lien d'activation (valable 7 jours, non envoyé) :\n{result.mail.link}\n"
        )
        return 0
    try:
        mailer.send(result.mail)
    except (MailNotConfiguredError, MailDeliveryError) as error:
        out.write(
            f"Le compte est prêt, mais l'e-mail n'est pas parti ({error}).\n"
            "Relance la commande une fois le SMTP réparé, ou utilise --print-link.\n"
        )
        return 1
    out.write(f"Invitation envoyée à {result.mail.recipient}.\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rocky-admin", description="Administration de Rocky"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    invite_parser = commands.add_parser(
        "invite",
        help="crée le compte d'une personne et lui envoie son lien d'activation",
    )
    invite_parser.add_argument("email")
    invite_parser.add_argument(
        "--print-link",
        action="store_true",
        help="affiche le lien au lieu de l'envoyer par e-mail",
    )
    arguments = parser.parse_args(argv)

    settings = load_settings()
    engine = create_db_engine(settings.database_url)
    try:
        return invite(
            engine,
            email=arguments.email,
            public_url=settings.public_url,
            mailer=SmtpMailer(settings.smtp),
            print_link=arguments.print_link,
            out=sys.stdout,
            clock=lambda: datetime.now(UTC),
        )
    finally:
        engine.dispose()
