"""What the assistant 🐾 knows of the applications (decision G4, Q11): the facts of one dossier, and the open
applications of the account with their next actions (the follow-ups due among them).

Read only: the application is read without its lock (``SqlApplicationStore.application``); its chronology is the one
the dossier shows (``timeline``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from fastapi import FastAPI, Request
from sqlalchemy import Engine

from rocky.candidatures.model import (
    BEFORE_SENDING,
    CHANNEL_LABELS,
    LANGUAGE_LABELS,
    REVISION_LABELS,
    STAGE_LABELS,
    NextAction,
)
from rocky.candidatures.rules import dossier, is_overdue, notes_in_force
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.timeline import timeline
from rocky.candidatures.web import Row, rows_of
from rocky.offres import api as offres_api
from rocky.system.assistant.model import Fact, FactSheet, SubjectKind
from rocky.system.assistant.registry import add_facts, add_summary
from rocky.system.auth.model import Account
from rocky.system.clock import today_of
from rocky.system.events import events_about

SUGGESTIONS = (
    "Où j'en suis ?",
    "Quelle est ma prochaine étape ?",
    "Quand relancer ?",
)
# The chronology given: the latest lines.
TIMELINE_LINES = 20
# The open applications given in the account summary.
SUMMARY_APPLICATIONS = 25


def install(app: FastAPI) -> None:
    add_facts(app, SubjectKind.APPLICATION, _sheet)
    add_summary(app, "candidatures", _summary)


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def action_text(action: NextAction | None, today: date) -> str | None:
    if action is None:
        return None
    late = " (en retard)" if is_overdue(action, today) else ""
    return f"{action.label} le {action.due:%d/%m/%Y}{late}"


def _sheet(request: Request, account: Account, application_id: int) -> FactSheet | None:
    today = today_of(request)
    with _engine(request).connect() as connection:
        store = SqlApplicationStore(connection)
        application = store.application(account.id, application_id)
        if application is None:
            return None
        state = dossier(store.changes(application.id))
        heading = offres_api.offer_headings(
            connection, account.id, [application.offer_id]
        ).get(application.offer_id)
        deadline = offres_api.offer_deadlines(
            connection, account.id, [application.offer_id], today
        ).get(application.offer_id)
        sendings = store.sendings(application.id)
        revisions = store.revisions(application.id)
        note_rows = store.notes(application.id)
        events = events_about(
            connection, account.id, "application", str(application.id)
        )
    link = f"/candidatures/{application.id}"
    title = "Candidature"
    facts: list[Fact] = []
    if heading is not None:
        title = (
            heading.title
            if not heading.company
            else f"{heading.title} chez {heading.company}"
        )
        where = f", {heading.location}" if heading.location else ""
        facts.append(Fact("candidature.offre", "Offre", f"{title}{where}", link))
    stage = (
        "fermée (ouverture annulée)"
        if state.stage is None
        else STAGE_LABELS[state.stage]
    )
    facts.append(Fact("candidature.etape", "Étape", stage, link))
    action = action_text(state.next_action, today)
    facts.append(
        Fact(
            "candidature.prochaine_action", "Prochaine action", action or "aucune", link
        )
    )
    if deadline is not None and state.stage in BEFORE_SENDING:
        facts.append(
            Fact(
                "candidature.date_limite",
                "Date limite de l'offre",
                f"{deadline:%d/%m/%Y}",
                link,
            )
        )
    if sendings:
        last = sendings[-1]
        facts.append(
            Fact(
                "candidature.envoi",
                "Envoi",
                f"le {last.sent_on:%d/%m/%Y} par {CHANNEL_LABELS[last.channel]}",
                link,
            )
        )
    if revisions:
        facts.append(
            Fact(
                "candidature.documents",
                "Documents produits",
                " ; ".join(
                    f"{REVISION_LABELS[revision.kind]} en "
                    f"{LANGUAGE_LABELS.get(revision.language, revision.language).lower()} "
                    f"du {revision.created_at:%d/%m/%Y}"
                    for revision in revisions
                ),
                link,
            )
        )
    notes = notes_in_force(note_rows)
    if notes:
        facts.append(
            Fact(
                "candidature.notes",
                "Tes notes",
                " ; ".join(note.text for note in notes),
                link,
            )
        )
    texts = {row.id: row.text for row in note_rows if row.text is not None}
    lines = timeline(events, texts)[-TIMELINE_LINES:]
    if lines:
        facts.append(
            Fact(
                "candidature.historique",
                "Chronologie",
                " ; ".join(f"{line.at:%d/%m/%Y} : {line.text}" for line in lines),
                link,
                cut_first=True,
            )
        )
    return FactSheet(title, tuple(facts), link, SUGGESTIONS)


def _summary(request: Request, account: Account) -> Sequence[Fact]:
    today = today_of(request)
    with _engine(request).connect() as connection:
        rows = rows_of(connection, account.id, today)
    return summary_facts(rows, today)


def summary_facts(rows: Sequence[Row], today: date) -> list[Fact]:
    """The open applications, the overdue follow-ups first (Q11)."""
    ordered = sorted(rows, key=lambda row: (not row.overdue, row.id))
    facts = []
    for row in ordered[:SUMMARY_APPLICATIONS]:
        name = (
            row.offer.title
            if not row.offer.company
            else f"{row.offer.title} chez {row.offer.company}"
        )
        text = f"{name} : {STAGE_LABELS[row.stage]}"
        action = action_text(row.next_action, today)
        if action:
            text += f" ; prochaine action : {action}"
        facts.append(
            Fact(
                f"compte.candidature_{row.id}",
                "Candidature",
                text,
                f"/candidatures/{row.id}",
            )
        )
    if not facts:
        facts.append(
            Fact(
                "compte.candidatures",
                "Candidatures",
                "aucune candidature ouverte",
                "/candidatures",
            )
        )
    return facts
