"""``rocky-admin invite``: accounts are created by invitation only (the command line is in ``rocky.system.admin``)."""

from __future__ import annotations

from typing import TextIO

from sqlalchemy import Engine

from rocky.system.auth.mail import (
    MailDeliveryError,
    Mailer,
    MailNotConfiguredError,
)
from rocky.system.auth.rules import InvalidEmailError
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import AlreadyActive, Argon2Hasher, Auth, Clock


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
