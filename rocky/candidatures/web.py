"""Applications: the screen 📝 Candidatures (the list and its gestures) and the box « Préparer la candidature » of an
offer's sheet; the application's own page is ``dossier_web``.

Each route runs one use case in one transaction; the server renders every state as HTML, HTMX swaps the fragments,
and requests without HTMX get a redirection or a whole page. Decisions ``docs/decisions/D1-dossier-statuts.md`` and
``docs/decisions/D6-ecran-candidatures.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection

from rocky.candidatures import dossier_web
from rocky.candidatures.model import (
    DEFER_DAYS,
    ISSUES,
    STAGE_LABELS,
    InvalidChangeError,
    NextAction,
    Stage,
)
from rocky.candidatures.rules import dossier, is_overdue, make_next_action, proposal
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.usecases import (
    cancel_last_change,
    change_stage,
    defer_next_action,
    needs_reasons,
    prepare_application,
    set_next_action,
)
from rocky.candidatures.web_common import (
    OffresDecisions,
    engine_of,
    now_of,
    owns,
    render_fragment,
    today_of,
)
from rocky.offres import web as offres_web
from rocky.offres.decisions import (
    REASONS,
    DecisionValue,
    InvalidDecisionError,
    application_decision,
)
from rocky.offres.model import OfferHeading
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.shell import page, wants_fragment
from rocky.system.workstation import WorkstationClient

TEMPLATES = Path(__file__).parent / "templates"
# Refreshes the offers list when « Préparer » records a decision (``offres.web.OFFERS_CHANGED``).
OFFERS_CHANGED = offres_web.OFFERS_CHANGED

router = APIRouter(prefix="/candidatures")

# DORMANT (decision D5, acceptance of 04/10): the prefilling by the Rocky workstation failed on 2 real postings out of
# 2 (the recruiters' sites show no form at once, they go through their own logins). Its code is kept but not run:
# no button leads to it and its routes answer 404 while this is False. To re-enable it: set True and put back the
# link « Préremplir avec le poste Rocky » in ``send_step.html``.
PREFILL_ENABLED = False


def install(app: FastAPI) -> None:
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(stage_labels=STAGE_LABELS)
    # DORMANT: the Rocky workstation that prefills forms (decision D5, Q1), and its switch (``PREFILL_ENABLED``);
    # both replaced by the tests of the dormant code. Building the client contacts nothing.
    app.state.workstation = WorkstationClient(app.state.settings.workstation_url)
    app.state.prefill_enabled = PREFILL_ENABLED
    app.include_router(router)
    app.include_router(dossier_web.router)


@dataclass(frozen=True)
class Row:
    """One open application of the list."""

    id: int
    offer: OfferHeading
    stage: Stage
    next_action: NextAction | None
    overdue: bool


def rows_of(connection: Connection, account_id: int, today: date) -> list[Row]:
    """The open applications of the account: the ones to act on first, the outcomes last."""
    found = SqlApplicationStore(connection).applications_of(account_id)
    headings = offres_web.offer_headings(
        connection, account_id, [application.offer_id for application, _ in found]
    )
    rows = [
        Row(
            application.id,
            headings[application.offer_id],
            state.stage,
            state.next_action,
            is_overdue(state.next_action, today),
        )
        for application, changes in found
        if (state := dossier(changes)).stage is not None
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.stage in ISSUES,
            row.next_action.due if row.next_action else date.max,
            row.id,
        ),
    )


def to_prepare_of(
    connection: Connection, account_id: int, rows: Iterable[Row]
) -> list[OfferHeading]:
    """The offers « Intéressé » without an open application (decision D3, Q26), the latest decided first."""
    opened = {row.offer.id for row in rows}
    ids = [
        offer_id
        for offer_id in offres_web.interested_offers(connection, account_id)
        if offer_id not in opened
    ]
    headings = offres_web.offer_headings(connection, account_id, ids)
    return [headings[offer_id] for offer_id in ids if offer_id in headings]


def _list(
    request: Request,
    account: Account,
    *,
    error: str | None = None,
    editing: int | None = None,
    stage_form: Mapping[str, object] | None = None,
) -> HTMLResponse:
    """The list: a whole page, or its section for HTMX."""
    today = today_of(request)
    with engine_of(request).begin() as connection:
        rows = rows_of(connection, account.id, today)
        to_prepare = to_prepare_of(connection, account.id, rows)
    context = {
        "rows": rows,
        "to_prepare": to_prepare,
        "today": today,
        "stages": list(Stage),
        "defer_days": DEFER_DAYS,
        "error": error,
        "editing": editing,
        "stage_form": stage_form,
    }
    if wants_fragment(request):
        return render_fragment(request, "candidatures/list.html", context)
    return page(
        request, "candidatures/page.html", active="applications", context=context
    )


# ``retour`` of a gesture made on the application's page: a fixed value, never a URL (no open redirection).
BACK_TO_DOSSIER = "dossier"


def _after_change(
    request: Request, account: Account, application_id: int, retour: str = ""
) -> Response:
    if retour == BACK_TO_DOSSIER:
        return RedirectResponse(
            f"/candidatures/{application_id}#envoi", status_code=303
        )
    if not wants_fragment(request):
        return RedirectResponse("/candidatures", status_code=303)
    return _list(request, account)


@router.get("", response_class=HTMLResponse)
def applications_page(request: Request, account: CurrentAccount) -> HTMLResponse:
    return _list(request, account)


@router.post("/{application_id}/etape", response_class=HTMLResponse)
def move(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    etape: Annotated[str, Form()],
    saisie: Annotated[str, Form()] = "",
    action: Annotated[str, Form()] = "",
    echeance: Annotated[date | None, Form()] = None,
    retour: Annotated[str, Form()] = "",
) -> Response:
    """A stage change in one gesture, with the proposed next action; the user enters it (``saisie``) when the
    proposal has no date (Q3, « Entretien »). From the application's page (« CV prêt », « J'ai envoyé », D3 Q25), back
    to it."""
    if etape not in Stage or not owns(request, account, application_id):
        return Response(status_code=404)
    stage = Stage(etape)
    if stage is Stage.SENT:
        # No sending without its date, channel and documents (decision D5, Q5): the confirmation form.
        target = f"/candidatures/{application_id}/envoi#envoi"
        if wants_fragment(request):
            return Response(status_code=200, headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)
    proposed = proposal(stage, today_of(request))
    if not saisie and proposed is not None and proposed[1] is None:
        form = {"id": application_id, "stage": stage, "label": proposed[0]}
        return _list(request, account, stage_form=form)
    try:
        chosen = (
            make_next_action(action, echeance)
            if saisie
            else None
            if proposed is None
            else make_next_action(*proposed)
        )
    except InvalidChangeError as error:
        form = {"id": application_id, "stage": stage, "label": action}
        return _list(request, account, error=str(error), stage_form=form)
    with engine_of(request).begin() as connection:
        change_stage(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=application_id,
            stage=stage,
            next_action=chosen,
            now=now_of(request),
        )
    return _after_change(request, account, application_id, retour)


@router.post("/{application_id}/action", response_class=HTMLResponse)
def next_action(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    action: Annotated[str, Form()] = "",
    echeance: Annotated[date | None, Form()] = None,
) -> Response:
    """Set the next action; both fields empty clear it."""
    if not owns(request, account, application_id):
        return Response(status_code=404)
    try:
        chosen = make_next_action(action, echeance)
    except InvalidChangeError as error:
        return _list(request, account, error=str(error), editing=application_id)
    with engine_of(request).begin() as connection:
        set_next_action(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=application_id,
            next_action=chosen,
            now=now_of(request),
        )
    return _after_change(request, account, application_id)


@router.get("/{application_id}/action", response_class=HTMLResponse)
def edit_next_action(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    if not owns(request, account, application_id):
        return Response(status_code=404)
    return _list(request, account, editing=application_id)


@router.post("/{application_id}/differer", response_class=HTMLResponse)
def defer(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    jours: Annotated[int, Form()],
) -> Response:
    if not owns(request, account, application_id):
        return Response(status_code=404)
    try:
        with engine_of(request).begin() as connection:
            defer_next_action(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                days=jours,
                now=now_of(request),
                today=today_of(request),
            )
    except InvalidChangeError as error:
        return _list(request, account, error=str(error))
    return _after_change(request, account, application_id)


@router.post("/{application_id}/annuler", response_class=HTMLResponse)
def undo(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    retour: Annotated[str, Form()] = "",
) -> Response:
    """« Annuler » the latest change of the application (Q6); its creation takes the decision written with it (Q9)."""
    try:
        with engine_of(request).begin() as connection:
            cancel_last_change(
                SqlApplicationStore(connection),
                OffresDecisions(connection),
                account_id=account.id,
                application_id=application_id,
                now=now_of(request),
            )
    except LookupError:
        return Response(status_code=404)
    response = _after_change(request, account, application_id, retour)
    response.headers["HX-Trigger"] = OFFERS_CHANGED
    return response


# The box of an offer's sheet (loaded by the sheet of ``offres``).


def _box(
    request: Request,
    account: Account,
    offer_id: int,
    *,
    error: str | None = None,
) -> Response:
    with engine_of(request).begin() as connection:
        if not offres_web.offer_headings(connection, account.id, [offer_id]):
            return Response(status_code=404)
        application = SqlApplicationStore(connection).application_of_offer(
            account.id, offer_id
        )
        state = (
            None
            if application is None
            else dossier(SqlApplicationStore(connection).changes(application.id))
        )
        in_force = offres_web.decision_in_force(connection, account.id, offer_id)
    context = {
        "offer_id": offer_id,
        "application_id": None if application is None else application.id,
        "state": state if state is not None and state.open else None,
        "rejected": in_force is DecisionValue.REJECTED,
        "needs_reasons": needs_reasons(in_force),
        "error": error,
    }
    return render_fragment(request, "candidatures/offer_box.html", context)


@router.get("/offre/{offer_id}", response_class=HTMLResponse)
def offer_box(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    return _box(request, account, offer_id)


@router.get("/offre/{offer_id}/preparer", response_class=HTMLResponse)
def prepare_panel(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    """The reasons of « Intéressé » to choose before the application is opened (Q8)."""
    return _panel(request, account, offer_id)


def _panel(
    request: Request,
    account: Account,
    offer_id: int,
    *,
    checked: tuple[str, ...] = (),
    note: str = "",
    error: str | None = None,
) -> Response:
    with engine_of(request).begin() as connection:
        if not offres_web.offer_headings(connection, account.id, [offer_id]):
            return Response(status_code=404)
    context = {
        "offer_id": offer_id,
        "reasons": REASONS[DecisionValue.INTERESTED],
        "checked": checked,
        "note": note,
        "error": error,
    }
    if wants_fragment(request):
        return render_fragment(request, "candidatures/prepare.html", context)
    return page(
        request,
        "candidatures/prepare_page.html",
        active="applications",
        context=context,
    )


@router.post("/offre/{offer_id}/preparer", response_class=HTMLResponse)
def prepare(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    motifs: Annotated[list[str] | None, Form()] = None,
    precision: Annotated[str, Form()] = "",
) -> Response:
    """« Préparer la candidature »: the decision « Intéressé » when needed, and the application, in one transaction."""
    engine = engine_of(request)
    with engine.begin() as connection:
        if not offres_web.offer_headings(connection, account.id, [offer_id]):
            return Response(status_code=404)
        in_force = offres_web.decision_in_force(connection, account.id, offer_id)
    interest = None
    if needs_reasons(in_force) and in_force is not DecisionValue.REJECTED:
        try:
            interest = application_decision(motifs or [], precision)
        except InvalidDecisionError as error:
            return _panel(
                request,
                account,
                offer_id,
                checked=tuple(motifs or ()),
                note=precision,
                error=str(error),
            )
    try:
        with engine.begin() as connection:
            application_id = prepare_application(
                SqlApplicationStore(connection),
                OffresDecisions(connection),
                account_id=account.id,
                offer_id=offer_id,
                interest=interest,
                now=now_of(request),
                today=today_of(request),
            )
    except InvalidChangeError as error:
        if not wants_fragment(request):
            return RedirectResponse(f"/offres/{offer_id}/fiche", status_code=303)
        return _box(request, account, offer_id, error=str(error))
    # Straight to the application's page (decision D3, Q25).
    target_url = f"/candidatures/{application_id}"
    if not wants_fragment(request):
        return RedirectResponse(target_url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": target_url})
