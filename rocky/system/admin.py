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

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import JobSource
from rocky.offres.sources.registry import build_sources
from rocky.offres.sources.report import report_lines
from rocky.offres.sources.rules import queries_for_track
from rocky.offres.sources.usecases import collect, complete_descriptions
from rocky.profil.import_file import ImportFileError, read_import_file
from rocky.profil.model import TrackStatus
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


def check_sources(
    engine: Engine,
    *,
    email: str,
    track_name: str | None,
    detail: bool,
    sources: Sequence[JobSource],
    limit: int,
    out: TextIO,
) -> int:
    """Run a real collection for the active tracks of ``email`` and tell, source by source, what happened.

    Nothing is written: the profile is only read.
    """
    try:
        address = normalize_email(email)
    except InvalidEmailError as error:
        out.write(f"{error}\n")
        return 2
    with engine.connect() as connection:
        account = SqlAuthStore(connection).find_account(address)
        if account is None:
            out.write(f"Aucun compte pour {address}.\n")
            return 1
        store = SqlProfileStore(connection)
        profile_id = store.find_profile_id(account.id)
        profile = None if profile_id is None else store.load(profile_id)
    tracks = [
        track
        for track in (profile.tracks if profile else ())
        if track.status is TrackStatus.ACTIVE
        and (track_name is None or track.name.casefold() == track_name.casefold())
    ]
    if not tracks:
        wanted = f"nommée « {track_name} »" if track_name else "active"
        out.write(f"Aucune piste {wanted} pour {address}.\n")
        return 1
    queries = [
        query
        for track in tracks
        for query in queries_for_track(track.content.titles, track.content.locations)
    ]
    names = ", ".join(f"« {track.name} »" for track in tracks)
    out.write(
        f"Collecte réelle pour {names} : {len(queries)} requête(s) intitulé × lieu.\n\n"
    )
    report = collect(sources, queries, limit)
    details = complete_descriptions(sources, report.offers) if detail else None
    out.writelines(f"{line}\n" for line in report_lines(report, details))
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
    sources_parser = commands.add_parser(
        "sources",
        help="lance une vraie collecte pour les pistes actives d'un compte, "
        "et dit source par source ce qui s'est passé (rien n'est écrit)",
    )
    sources_parser.add_argument("email")
    sources_parser.add_argument("--piste", help="seulement la piste de ce nom")
    sources_parser.add_argument(
        "--detail",
        action="store_true",
        help="demande aussi le détail des offres incomplètes quand la source en a un",
    )
    arguments = parser.parse_args(argv)

    settings = load_settings()
    engine = create_db_engine(settings.database_url)
    try:
        if arguments.command == "sources":
            http = PublicHttp()
            try:
                return check_sources(
                    engine,
                    email=arguments.email,
                    track_name=arguments.piste,
                    detail=arguments.detail,
                    sources=build_sources(settings.sources, http),
                    limit=settings.sources.results_per_query,
                    out=sys.stdout,
                )
            finally:
                http.close()
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
