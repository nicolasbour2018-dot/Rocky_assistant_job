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
    BEFORE_SENDING,
    DEFER_DAYS,
    FOLLOW_UP_STAGES,
    STAGE_LABELS,
    InvalidChangeError,
    NextAction,
    Stage,
)
from rocky.candidatures.rules import (
    TAB_LABELS,
    Step,
    Tab,
    dossier,
    is_overdue,
    make_next_action,
    proposal,
    tabs_of,
)
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.usecases import (
    cancel_last_change,
    change_stage,
    defer_next_action,
    mark_action_done,
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
    """One open application of the screen."""

    id: int
    offer: OfferHeading
    stage: Stage
    next_action: NextAction | None
    overdue: bool
    deadline: (
        date | None
    )  # the offer's, shown while the application is not sent (D6, Q8)
    tabs: frozenset[Tab]

    @property
    def done_offered(self) -> bool:
        """« Fait » is offered (D6, Q5): an action in force, after the sending."""
        return self.next_action is not None and self.stage in FOLLOW_UP_STAGES

    @property
    def shows_deadline(self) -> bool:
        return self.deadline is not None and self.stage in BEFORE_SENDING


def rows_of(connection: Connection, account_id: int, today: date) -> list[Row]:
    """The open applications of the account (a cancelled creation is not one)."""
    found = SqlApplicationStore(connection).applications_of(account_id)
    offer_ids = [application.offer_id for application, _ in found]
    headings = offres_web.offer_headings(connection, account_id, offer_ids)
    deadlines = offres_web.offer_deadlines(connection, account_id, offer_ids, today)
    return [
        Row(
            application.id,
            headings[application.offer_id],
            state.stage,
            state.next_action,
            is_overdue(state.next_action, today),
            deadlines.get(application.offer_id),
            tabs_of(state.stage, state.next_action, today),
        )
        for application, changes in found
        if (state := dossier(changes)).stage is not None
    ]


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


@dataclass(frozen=True)
class Screen:
    """The screen 📝 Candidatures on one tab (decision D6, Q1)."""

    tab: Tab
    counts: Mapping[Tab, int]
    rows: list[Row]
    to_prepare: list[OfferHeading]
    upcoming: Row | None  # the next action to come, when nothing is to do today


def _due(row: Row) -> date:
    return row.next_action.due if row.next_action else date.max


def screen(rows: list[Row], to_prepare: list[OfferHeading], tab: Tab) -> Screen:
    """The rows of ``tab``: the most urgent first; the closed ones, the latest first."""
    counts: dict[Tab, int] = {
        found: sum(1 for row in rows if found in row.tabs) for found in Tab
    }
    counts[Tab.TO_PREPARE] = len(to_prepare)
    shown = [row for row in rows if tab in row.tabs]
    if tab is Tab.CLOSED:
        shown.sort(key=lambda row: -row.id)
    else:
        shown.sort(key=lambda row: (_due(row), row.id))
    later = sorted(
        (row for row in rows if row.next_action and Tab.TO_DO not in row.tabs),
        key=lambda row: (_due(row), row.id),
    )
    return Screen(tab, counts, shown, to_prepare, later[0] if later else None)


def _tab(vue: str | None) -> Tab:
    return Tab(vue) if vue in set(Tab) else Tab.TO_DO


def _list(
    request: Request,
    account: Account,
    *,
    tab: Tab = Tab.TO_DO,
    error: str | None = None,
    editing: int | None = None,
    stage_form: Mapping[str, object] | None = None,
) -> HTMLResponse:
    """The screen: a whole page, or its section for HTMX."""
    today = today_of(request)
    with engine_of(request).begin() as connection:
        rows = rows_of(connection, account.id, today)
        to_prepare = to_prepare_of(connection, account.id, rows)
    context = {
        "screen": screen(rows, to_prepare, tab),
        "Tab": Tab,
        "tab_labels": TAB_LABELS,
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


def _list_url(tab: Tab) -> str:
    return "/candidatures" if tab is Tab.TO_DO else f"/candidatures?vue={tab.value}"


# ``retour`` of a gesture made on the application's page: a step of its page, a fixed value and never a URL (no open
# redirection). « dossier »: the step it opens on.
BACK_TO_DOSSIER = "dossier"


def _step(retour: str) -> Step | None:
    return Step(retour) if retour in set(Step) else None


def _after_change(
    request: Request,
    account: Account,
    application_id: int,
    retour: str = "",
    vue: str = "",
) -> Response:
    step = _step(retour)
    if step is not None or retour == BACK_TO_DOSSIER:
        return RedirectResponse(
            dossier_web.dossier_url(application_id, step), status_code=303
        )
    if not wants_fragment(request):
        return RedirectResponse(_list_url(_tab(vue)), status_code=303)
    return _list(request, account, tab=_tab(vue))


@router.get("", response_class=HTMLResponse)
def applications_page(
    request: Request, account: CurrentAccount, vue: str = ""
) -> HTMLResponse:
    return _list(request, account, tab=_tab(vue))


def _deadline(request: Request, account: Account, application_id: int) -> date | None:
    """The deadline of the application's offer, or None."""
    with engine_of(request).begin() as connection:
        application = SqlApplicationStore(connection).locked_application(
            account.id, application_id
        )
        if application is None:
            return None
        return offres_web.offer_deadlines(
            connection, account.id, [application.offer_id], today_of(request)
        ).get(application.offer_id)


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
    vue: Annotated[str, Form()] = "",
) -> Response:
    """A stage change in one gesture, with the proposed next action; the user enters it (``saisie``) when the
    proposal has no date (Q3, « Entretien »). From the application's page (« CV prêt », the step « Suivi »), back
    to it."""
    if etape not in Stage or not owns(request, account, application_id):
        return Response(status_code=404)
    stage = Stage(etape)
    if stage is Stage.SENT:
        # No sending without its date, channel and documents (decision D5, Q5): the confirmation form.
        target = dossier_web.CONFIRM_URL.format(application_id)
        if wants_fragment(request):
            return Response(status_code=200, headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)
    tab = _tab(vue)
    proposed = proposal(
        stage, today_of(request), _deadline(request, account, application_id)
    )
    if not saisie and proposed is not None and proposed[1] is None:
        form = {"id": application_id, "stage": stage, "label": proposed[0]}
        return _list(request, account, tab=tab, stage_form=form)
    try:
        chosen = (
            make_next_action(action, echeance)
            if saisie
            else None
            if proposed is None
            else make_next_action(*proposed)
        )
    except InvalidChangeError as error:
        if _step(retour) is not None:
            return dossier_web.follow_up_refused(
                request, account, application_id, str(error)
            )
        form = {"id": application_id, "stage": stage, "label": action}
        return _list(request, account, tab=tab, error=str(error), stage_form=form)
    with engine_of(request).begin() as connection:
        change_stage(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=application_id,
            stage=stage,
            next_action=chosen,
            now=now_of(request),
        )
    return _after_change(request, account, application_id, retour, vue)


@router.post("/{application_id}/action", response_class=HTMLResponse)
def next_action(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    action: Annotated[str, Form()] = "",
    echeance: Annotated[date | None, Form()] = None,
    retour: Annotated[str, Form()] = "",
    vue: Annotated[str, Form()] = "",
) -> Response:
    """Set the next action; both fields empty clear it."""
    if not owns(request, account, application_id):
        return Response(status_code=404)
    try:
        chosen = make_next_action(action, echeance)
    except InvalidChangeError as error:
        if _step(retour) is not None:
            return dossier_web.follow_up_refused(
                request, account, application_id, str(error), editing=True
            )
        return _list(
            request, account, tab=_tab(vue), error=str(error), editing=application_id
        )
    with engine_of(request).begin() as connection:
        set_next_action(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=application_id,
            next_action=chosen,
            now=now_of(request),
        )
    return _after_change(request, account, application_id, retour, vue)


@router.get("/{application_id}/action", response_class=HTMLResponse)
def edit_next_action(
    request: Request, account: CurrentAccount, application_id: int, vue: str = ""
) -> Response:
    if not owns(request, account, application_id):
        return Response(status_code=404)
    return _list(request, account, tab=_tab(vue), editing=application_id)


@router.post("/{application_id}/differer", response_class=HTMLResponse)
def defer(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    jours: Annotated[int, Form()],
    retour: Annotated[str, Form()] = "",
    vue: Annotated[str, Form()] = "",
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
        return _refused(request, account, application_id, retour, vue, str(error))
    return _after_change(request, account, application_id, retour, vue)


@router.post("/{application_id}/fait", response_class=HTMLResponse)
def done(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    retour: Annotated[str, Form()] = "",
    vue: Annotated[str, Form()] = "",
) -> Response:
    """« Fait » (decision D6, Q5): the action is done, the next one proposed for the stage follows it."""
    try:
        with engine_of(request).begin() as connection:
            mark_action_done(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                now=now_of(request),
                today=today_of(request),
            )
    except LookupError:
        return Response(status_code=404)
    except InvalidChangeError as error:
        return _refused(request, account, application_id, retour, vue, str(error))
    return _after_change(request, account, application_id, retour, vue)


def _refused(
    request: Request,
    account: Account,
    application_id: int,
    retour: str,
    vue: str,
    error: str,
) -> Response:
    """A gesture refused: its reason, where it was made."""
    if _step(retour) is not None:
        return dossier_web.follow_up_refused(request, account, application_id, error)
    return _list(request, account, tab=_tab(vue), error=error)


@router.post("/{application_id}/annuler", response_class=HTMLResponse)
def undo(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    retour: Annotated[str, Form()] = "",
    vue: Annotated[str, Form()] = "",
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
    response = _after_change(request, account, application_id, retour, vue)
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
        deadline = offres_web.offer_deadlines(
            connection, account.id, [offer_id], today_of(request)
        ).get(offer_id)
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
                deadline=deadline,
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
