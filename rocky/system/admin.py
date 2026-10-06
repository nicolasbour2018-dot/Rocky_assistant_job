"""``rocky-admin``: administration commands, assembled from the modules that own them.

Run in the application container: ``docker compose run --rm app rocky-admin <command>``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from sqlalchemy import Engine

from rocky.messages.alerts.model import AlertsBusyError
from rocky.messages.classification.model import (
    CATEGORY_LABELS,
    CLASSIFY_VERSION,
    LEVEL_LABELS,
    View,
)
from rocky.messages.classification.usecases import ClassifyBusyError
from rocky.messages.model import SYNC_STATUS_LABELS, SyncStatus
from rocky.messages.model import Trigger as MailTrigger
from rocky.messages.service import MessagesService, messages_service
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import JobSource
from rocky.offres.sources.registry import build_sources
from rocky.offres.sources.report import report_lines
from rocky.offres.sources.rules import queries_for_track
from rocky.offres.sources.usecases import collect, complete_descriptions
from rocky.offres.sql import SqlStore
from rocky.offres.watch.model import (
    RUN_STATUS_LABELS,
    SUCCESSFUL,
    Trigger,
    WatchBusyError,
)
from rocky.offres.watch.service import WatchService, public_sources
from rocky.offres.watch.usecases import active_tracks
from rocky.profil.api import stored_profile
from rocky.profil.import_file import ImportFileError, read_import_file
from rocky.profil.import_file import export_profile as export_file
from rocky.profil.rules import ProfileInputError
from rocky.profil.sql import SqlProfileStore
from rocky.profil.usecases import AlreadyFilled, ProfileEditor
from rocky.system.auth.admin import invite
from rocky.system.auth.mail import SmtpMailer
from rocky.system.auth.model import Account
from rocky.system.auth.rules import InvalidEmailError, normalize_email
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import Clock
from rocky.system.clock import utc_now
from rocky.system.config import load_settings
from rocky.system.db import create_db_engine

COUNT_LABELS = {
    "skills": "compétences",
    "languages": "langues",
    "experiences": "expériences et formations",
    "projects": "projets",
    "tracks": "pistes",
}


def _account(engine: Engine, email: str, out: TextIO) -> Account | int:
    """The account of ``email``; otherwise the exit code, its reason written (2: not an address, 1: no account)."""
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
    return account


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
                clock=clock,
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


def export_profile(engine: Engine, *, email: str, out: TextIO, err: TextIO) -> int:
    """Write the profile of ``email`` as a profile file (JSON) on ``out``; read only (decision D2, Q18)."""
    try:
        address = normalize_email(email)
    except InvalidEmailError as error:
        err.write(f"{error}\n")
        return 2
    with engine.connect() as connection:
        account = SqlAuthStore(connection).find_account(address)
        store = SqlProfileStore(connection)
        profile_id = None if account is None else store.find_profile_id(account.id)
        if profile_id is None:
            err.write(f"Aucun profil pour {address}.\n")
            return 1
        profile = store.load(profile_id)
        connection.rollback()
    json.dump(export_file(profile), out, ensure_ascii=False, indent=2)
    out.write("\n")
    err.write(
        f"Profil de {address} exporté (la photo et les gabarits de CV n'y sont pas).\n"
    )
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
    account = _account(engine, email, out)
    if isinstance(account, int):
        return account
    with engine.connect() as connection:
        profile = stored_profile(connection, account.id)
    tracks = active_tracks(profile, track_name)
    if not tracks:
        wanted = f"nommée « {track_name} »" if track_name else "active"
        out.write(f"Aucune piste {wanted} pour {account.email}.\n")
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


def watch_account(
    engine: Engine,
    *,
    email: str,
    track_name: str | None,
    service: WatchService,
    out: TextIO,
) -> int:
    """Run a real watch for ``email`` (its offers are written), then tell its status and, source by source, why."""
    account = _account(engine, email, out)
    if isinstance(account, int):
        return account
    if not active_tracks(service.profiles.profile(account.id), track_name):
        wanted = f"nommée « {track_name} »" if track_name else "active"
        out.write(f"Aucune piste {wanted} pour {account.email}.\n")
        return 1
    try:
        result = service.run(account.id, Trigger.MANUAL, track_name=track_name)
    except WatchBusyError:
        out.write(
            f"Une veille de {account.email} est déjà en cours : rien n'a été lancé.\n"
        )
        return 1
    counts = result.counts
    out.write(
        f"Veille {RUN_STATUS_LABELS[result.status].lower()} : {counts.found} offre(s) "
        f"trouvée(s), {counts.new} nouvelle(s), {counts.completed} complétée(s), "
        f"{counts.below_threshold} sous le seuil, {counts.incomplete} incomplète(s), "
        f"{counts.not_written} non écrite(s).\n"
    )
    if result.reason:
        out.write(f"raison : {result.reason}\n")
    if result.report is not None:
        out.write("\n")
        stored = {run.source: run.incomplete for run in result.sources}
        out.writelines(
            f"{line}\n"
            for line in report_lines(result.report, result.detail, stored or None)
        )
    with engine.connect() as connection:
        broken = SqlStore(connection).unscored_or_orphan_offers(account.id)
    out.write(f"\nOffres sans score ou sans piste : {len(broken)}.\n")
    return 0 if result.status in SUCCESSFUL else 1


def collect_messages(
    engine: Engine, *, email: str, service: MessagesService, out: TextIO
) -> int:
    """Collect every connected Gmail mailbox of ``email`` for real (decision E1), then tell each collection."""
    if not service.configured:
        out.write(
            "Gmail n'est pas configuré : il manque le client Google ou ROCKY_SECRET_KEY "
            "(docs/procedures/e1-gmail/).\n"
        )
        return 1
    account = _account(engine, email, out)
    if isinstance(account, int):
        return account
    results = service.collect_account(account.id, MailTrigger.MANUAL)
    if not results:
        out.write(f"Aucune boîte Gmail connectée ou libre pour {account.email}.\n")
        return 1
    with service.storage.transaction() as store:
        addresses = {
            mailbox.id: mailbox.address for mailbox in store.mailboxes(account.id)
        }
    for result in results:
        counts = result.counts
        out.write(
            f"{addresses[result.mailbox_id]} : collecte "
            f"{SYNC_STATUS_LABELS[result.status].lower()}, {counts.listed} message(s) "
            f"trouvé(s), {counts.known} déjà relevé(s), {counts.new} nouveau(x), "
            f"{counts.not_written} non écrit(s).\n"
        )
        if result.reason:
            out.write(f"raison : {result.reason}\n")
    succeeded = all(
        r.status in (SyncStatus.COMPLETED, SyncStatus.PARTIAL) for r in results
    )
    return 0 if succeeded else 1


def classify_account_messages(
    engine: Engine,
    *,
    email: str,
    service: MessagesService,
    use_model: bool,
    max_calls: int | None,
    again: bool,
    out: TextIO,
) -> int:
    """Classify the messages of ``email`` (decision E2): those without a decision, or all of them again; the language
    model is called within the account's limits and ``max_calls`` (network: with Nicolas's agreement)."""
    account = _account(engine, email, out)
    if isinstance(account, int):
        return account
    try:
        report = service.classify(
            account.id, use_model=use_model, max_calls=max_calls, again=again
        )
    except ClassifyBusyError:
        out.write("Un classement de ce compte est déjà en cours.\n")
        return 1
    out.write(
        f"Classement {CLASSIFY_VERSION} : {report.by_rules} décision(s) par les règles, "
        f"{report.by_model} par le modèle ({report.refused} réponse(s) refusée(s)), "
        f"{report.calls} appel(s) au modèle, {report.waiting} message(s) en attente.\n"
    )
    if report.reason:
        out.write(f"raison de l'attente : {report.reason}\n")
    with service.storage.transaction() as store:
        shown = store.sorted_messages(account.id, View.ALL, 10_000)
    counts = Counter(
        (
            CATEGORY_LABELS[m.decision.category]
            if m.decision.category
            else "À vérifier",
            LEVEL_LABELS[m.decision.level],
        )
        for m in shown
        if m.decision is not None
    )
    out.writelines(
        f"  {category} · {level} : {count}\n"
        for (category, level), count in sorted(counts.items())
    )
    return 0


def read_account_alerts(
    engine: Engine,
    *,
    email: str,
    service: MessagesService,
    links: bool,
    out: TextIO,
) -> int:
    """Turn the job alerts of ``email`` never read into offers (decision E3); the postings of their links are read for
    real unless ``links`` is False (network: with Nicolas's agreement)."""
    account = _account(engine, email, out)
    if isinstance(account, int):
        return account
    try:
        report = service.read_alerts(account.id, links=links)
    except AlertsBusyError:
        out.write("Une lecture des alertes de ce compte est déjà en cours.\n")
        return 1
    out.write(
        f"{report.alerts} alerte(s) lue(s), dont {report.too_old} trop ancienne(s) : "
        f"{report.offers} offre(s), dont {report.created} nouvelle(s) ; "
        f"{report.pages_read} fiche(s) lue(s), {report.pages_unread} non lue(s) ; "
        f"{report.unknown_formats} format(s) inconnu(s), {report.failed} en échec.\n"
    )
    out.writelines(
        f"  {platform} : {count} offre(s)\n"
        for platform, count in sorted(report.by_platform.items())
    )
    if report.postponed:
        out.write(
            f"{report.postponed} alerte(s) en attente"
            + (f" : {report.reason}" if report.reason else " (veille en cours)")
            + "\n"
        )
    return 0


LABEL_COLUMNS = (
    "message_id",
    "received_at",
    "sender_address",
    "subject",
    "gesture",
    "category",
    "application_id",
    "decided_at",
    "reviewed_category",
    "reviewed_application_id",
    "reviewed_level",
    "reviewed_author",
    "reviewed_rule",
    "reviewed_version",
)


def export_mail_labels(
    engine: Engine, *, email: str, service: MessagesService, out: TextIO
) -> int:
    """The labels of ``email`` (decision E4, Q6, D14): each decision of the user about a message with the decision of
    Rocky it reviewed, as CSV. Personal data: never kept in the repository."""
    account = _account(engine, email, out)
    if isinstance(account, int):
        return account
    writer = csv.writer(out)
    writer.writerow(LABEL_COLUMNS)
    for label in service.labels(account.id):
        writer.writerow(
            [
                "" if (value := getattr(label, column)) is None else _csv_value(value)
                for column in LABEL_COLUMNS
            ]
        )
    return 0


def _csv_value(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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
    export_parser = commands.add_parser(
        "export-profil",
        help="écrit le profil d'un compte au format des fichiers de profil "
        "(sortie standard : rediriger vers un fichier)",
    )
    export_parser.add_argument("email")
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
    watch_parser = commands.add_parser(
        "veille",
        help="lance une vraie veille pour les pistes actives d'un compte : ses offres "
        "sont enregistrées, puis son statut est affiché source par source",
    )
    watch_parser.add_argument("email")
    watch_parser.add_argument("--piste", help="seulement la piste de ce nom")
    messages_parser = commands.add_parser(
        "messages",
        help="relève pour de vrai les boîtes Gmail connectées d'un compte : les nouveaux "
        "messages sont enregistrés, puis chaque collecte est résumée",
    )
    messages_parser.add_argument("email")
    classify_parser = commands.add_parser(
        "messages-classer",
        help="classe les messages d'un compte qui n'ont pas de décision (règles, puis modèle de "
        "langage dans les plafonds du compte), puis résume les décisions",
    )
    classify_parser.add_argument("email")
    classify_parser.add_argument(
        "--sans-llm",
        action="store_true",
        help="règles seules : aucun appel au modèle, les messages qu'elles ne tranchent pas restent en attente",
    )
    classify_parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="nombre maximal d'appels au modèle pendant ce classement",
    )
    classify_parser.add_argument(
        "--reclasser",
        action="store_true",
        help="classe à nouveau tous les messages (jamais par-dessus une décision de l'utilisateur)",
    )
    alerts_parser = commands.add_parser(
        "alertes",
        help="tire les offres des alertes emploi d'un compte qui n'ont jamais été lues, puis lit leurs fiches "
        "(réseau réel), et résume ce qu'elles ont donné",
    )
    alerts_parser.add_argument("email")
    alerts_parser.add_argument(
        "--sans-liens",
        action="store_true",
        help="cartes seules : aucune fiche n'est lue (aucun appel réseau)",
    )
    labels_parser = commands.add_parser(
        "messages-etiquettes",
        help="exporte en CSV (sortie standard) les corrections et confirmations de l'utilisateur sur ses messages, "
        "avec la décision de Rocky qu'elles revoient (jeu étiqueté, D14)",
    )
    labels_parser.add_argument("email")
    arguments = parser.parse_args(argv)

    settings = load_settings()
    engine = create_db_engine(settings.database_url)
    try:
        if arguments.command == "veille":
            return watch_account(
                engine,
                email=arguments.email,
                track_name=arguments.piste,
                service=WatchService(
                    engine,
                    sources=public_sources(settings.sources),
                    limit=settings.sources.results_per_query,
                    clock=utc_now,
                ),
                out=sys.stdout,
            )
        if arguments.command == "messages":
            return collect_messages(
                engine,
                email=arguments.email,
                service=messages_service(
                    engine, settings, clock=utc_now, classify=False, new_http=None
                ),
                out=sys.stdout,
            )
        if arguments.command == "alertes":
            return read_account_alerts(
                engine,
                email=arguments.email,
                service=messages_service(
                    engine, settings, clock=utc_now, classify=False, new_http=PublicHttp
                ),
                links=not arguments.sans_liens,
                out=sys.stdout,
            )
        if arguments.command == "messages-etiquettes":
            return export_mail_labels(
                engine,
                email=arguments.email,
                service=messages_service(
                    engine, settings, clock=utc_now, classify=False, new_http=None
                ),
                out=sys.stdout,
            )
        if arguments.command == "messages-classer":
            return classify_account_messages(
                engine,
                email=arguments.email,
                service=messages_service(
                    engine, settings, clock=utc_now, classify=True, new_http=None
                ),
                use_model=not arguments.sans_llm,
                max_calls=arguments.limite,
                again=arguments.reclasser,
                out=sys.stdout,
            )
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
        if arguments.command == "export-profil":
            return export_profile(
                engine, email=arguments.email, out=sys.stdout, err=sys.stderr
            )
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
