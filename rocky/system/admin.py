"""``rocky-admin``: administration commands, assembled from the modules that own them.

Run in the application container: ``docker compose run --rm app rocky-admin <command>``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from sqlalchemy import Engine

from rocky.profil.import_file import ImportFileError, read_import_file
from rocky.profil.rules import ProfileInputError
from rocky.profil.sql import SqlProfileStore
from rocky.profil.usecases import AlreadyFilled, ProfileEditor
from rocky.system.auth.admin import invite
from rocky.system.auth.mail import SmtpMailer
from rocky.system.auth.rules import InvalidEmailError, normalize_email
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import Clock
from rocky.system.config import load_settings
from rocky.system.db import create_db_engine

COUNT_LABELS = {
    "skills": "compétences",
    "languages": "langues",
    "experiences": "expériences et formations",
    "projects": "projets",
    "tracks": "pistes",
}


def import_profile(
    engine: Engine, *, path: Path, email: str, out: TextIO, clock: Clock
) -> int:
    """Import a reviewed profile file into the empty profile of ``email``, in one transaction."""
    try:
        imported = read_import_file(path)
        address = normalize_email(email)
    except ImportFileError as error:
        out.write("Le fichier n'est pas importable :\n")
        out.writelines(f"- {problem}\n" for problem in error.problems)
        return 2
    except InvalidEmailError as error:
        out.write(f"{error}\n")
        return 2
    try:
        with engine.begin() as connection:
            account = SqlAuthStore(connection).find_account(address)
            if account is None:
                out.write(f"Aucun compte pour {address} : invite-le d'abord.\n")
                return 1
            editor = ProfileEditor(
                SqlProfileStore(connection),
                clock=utc_now,
                account_id=account.id,
                email=account.email,
            )
            result = editor.import_profile(imported)
    except ProfileInputError as error:
        out.write(f"Import refusé, rien n'a été écrit : {error}\n")
        return 2
    if isinstance(result, AlreadyFilled):
        out.write(f"Le profil de {address} a déjà un contenu : rien n'a été importé.\n")
        return 1
    summary = ", ".join(
        f"{count} {COUNT_LABELS[key]}" for key, count in result.counts.items()
    )
    out.write(f"Profil importé pour {address} : {summary}.\n")
    return 0


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    import_parser = commands.add_parser(
        "import-profil",
        help="importe un fichier de profil relu dans le profil vide d'un compte",
    )
    import_parser.add_argument("fichier", type=Path)
    import_parser.add_argument("email")
    arguments = parser.parse_args(argv)

    settings = load_settings()
    engine = create_db_engine(settings.database_url)
    try:
        if arguments.command == "import-profil":
            return import_profile(
                engine,
                path=arguments.fichier,
                email=arguments.email,
                out=sys.stdout,
                clock=utc_now,
            )
        return invite(
            engine,
            email=arguments.email,
            public_url=settings.public_url,
            mailer=SmtpMailer(settings.smtp),
            print_link=arguments.print_link,
            out=sys.stdout,
            clock=utc_now,
        )
    finally:
        engine.dispose()
