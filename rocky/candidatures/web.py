"""Applications (step D1): the box « Préparer la candidature » of an offer's sheet and a plain list at /candidatures.

The screen 📝 Candidatures proper is step D6. Each route runs one use case in one transaction; the server renders
every state as HTML, HTMX swaps the fragments, and requests without HTMX get a redirection or a whole page.
Decision ``docs/decisions/D1-dossier-statuts.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection, Engine

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
from rocky.candidatures.targeting import (
    COVERAGE_LABELS,
    Coverage,
    CoverageLine,
    Targeted,
    cited_skills,
    coverage,
    selection_json,
    selection_of,
    target,
)
from rocky.candidatures.usecases import (
    adjust_cv_selection,
    cancel_last_change,
    change_stage,
    defer_next_action,
    needs_reasons,
    prepare_application,
    set_next_action,
)
from rocky.offres import web as offres_web
from rocky.offres.analysis.model import IMPORTANCE_LABELS, Importance, PostingAnalysis
from rocky.offres.decisions import (
    REASONS,
    Decision,
    DecisionValue,
    InvalidDecisionError,
    application_decision,
)
from rocky.offres.model import OfferHeading
from rocky.profil import web as profil_web
from rocky.profil.cv import layout as cv_layout
from rocky.profil.cv.layout import check_layout
from rocky.profil.cv.rendering import CvRefusedError
from rocky.profil.cv.template import Slots
from rocky.profil.model import CvLayout, Profile, SkillCategory
from rocky.profil.rules import ProfileInputError
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.events import JsonValue
from rocky.system.render import RenderError
from rocky.system.shell import page, wants_fragment

TEMPLATES = Path(__file__).parent / "templates"
# Refreshes the offers list when « Préparer » records a decision (``offres.web.OFFERS_CHANGED``).
OFFERS_CHANGED = offres_web.OFFERS_CHANGED

router = APIRouter(prefix="/candidatures")


def install(app: FastAPI) -> None:
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(stage_labels=STAGE_LABELS)
    app.include_router(router)


class OffresDecisions:
    """``OfferDecisions`` on the public functions of ``offres``, in the caller's transaction."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def decision_in_force(self, account_id: int, offer_id: int) -> DecisionValue | None:
        return offres_web.decision_in_force(self._conn, account_id, offer_id)

    def record_interested(
        self, account_id: int, offer_id: int, decision: Decision, now: datetime
    ) -> int:
        return offres_web.record_application_decision(
            self._conn,
            account_id=account_id,
            offer_id=offer_id,
            decision=decision,
            now=now,
        )

    def cancel(self, account_id: int, decision_id: int, now: datetime) -> bool:
        return offres_web.cancel_application_decision(
            self._conn, account_id=account_id, decision_id=decision_id, now=now
        )


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


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.auth.clock
    return clock()


def _today(request: Request) -> date:
    today: Callable[[], date] = request.app.state.import_today
    return today()


def _fragment(
    request: Request, name: str, context: Mapping[str, object]
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, name, dict(context))


def _list(
    request: Request,
    account: Account,
    *,
    error: str | None = None,
    editing: int | None = None,
    stage_form: Mapping[str, object] | None = None,
) -> HTMLResponse:
    """The list: a whole page, or its section for HTMX."""
    today = _today(request)
    with _engine(request).begin() as connection:
        rows = rows_of(connection, account.id, today)
    context = {
        "rows": rows,
        "today": today,
        "stages": list(Stage),
        "defer_days": DEFER_DAYS,
        "error": error,
        "editing": editing,
        "stage_form": stage_form,
    }
    if wants_fragment(request):
        return _fragment(request, "candidatures/list.html", context)
    return page(
        request, "candidatures/page.html", active="applications", context=context
    )


def _after_change(request: Request, account: Account) -> Response:
    if not wants_fragment(request):
        return RedirectResponse("/candidatures", status_code=303)
    return _list(request, account)


def _owned(request: Request, account: Account, application_id: int) -> bool:
    with _engine(request).begin() as connection:
        store = SqlApplicationStore(connection)
        return store.locked_application(account.id, application_id) is not None


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
) -> Response:
    """A stage change in one gesture, with the proposed next action; the user enters it (``saisie``) when the
    proposal has no date (Q3, « Entretien »)."""
    if etape not in Stage or not _owned(request, account, application_id):
        return Response(status_code=404)
    stage = Stage(etape)
    proposed = proposal(stage, _today(request))
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
    with _engine(request).begin() as connection:
        change_stage(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=application_id,
            stage=stage,
            next_action=chosen,
            now=_now(request),
        )
    return _after_change(request, account)


@router.post("/{application_id}/action", response_class=HTMLResponse)
def next_action(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    action: Annotated[str, Form()] = "",
    echeance: Annotated[date | None, Form()] = None,
) -> Response:
    """Set the next action; both fields empty clear it."""
    if not _owned(request, account, application_id):
        return Response(status_code=404)
    try:
        chosen = make_next_action(action, echeance)
    except InvalidChangeError as error:
        return _list(request, account, error=str(error), editing=application_id)
    with _engine(request).begin() as connection:
        set_next_action(
            SqlApplicationStore(connection),
            account_id=account.id,
            application_id=application_id,
            next_action=chosen,
            now=_now(request),
        )
    return _after_change(request, account)


@router.get("/{application_id}/action", response_class=HTMLResponse)
def edit_next_action(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    if not _owned(request, account, application_id):
        return Response(status_code=404)
    return _list(request, account, editing=application_id)


@router.post("/{application_id}/differer", response_class=HTMLResponse)
def defer(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    jours: Annotated[int, Form()],
) -> Response:
    if not _owned(request, account, application_id):
        return Response(status_code=404)
    try:
        with _engine(request).begin() as connection:
            defer_next_action(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                days=jours,
                now=_now(request),
                today=_today(request),
            )
    except InvalidChangeError as error:
        return _list(request, account, error=str(error))
    return _after_change(request, account)


@router.post("/{application_id}/annuler", response_class=HTMLResponse)
def undo(request: Request, account: CurrentAccount, application_id: int) -> Response:
    """« Annuler » the latest change of the application (Q6); its creation takes the decision written with it (Q9)."""
    try:
        with _engine(request).begin() as connection:
            cancel_last_change(
                SqlApplicationStore(connection),
                OffresDecisions(connection),
                account_id=account.id,
                application_id=application_id,
                now=_now(request),
            )
    except LookupError:
        return Response(status_code=404)
    response = _after_change(request, account)
    response.headers["HX-Trigger"] = OFFERS_CHANGED
    return response


# The box of an offer's sheet (loaded by the sheet of ``offres``).


def _box(
    request: Request,
    account: Account,
    offer_id: int,
    *,
    error: str | None = None,
    prepared: bool = False,
) -> Response:
    with _engine(request).begin() as connection:
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
        "prepared": prepared,
    }
    return _fragment(request, "candidatures/offer_box.html", context)


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
    with _engine(request).begin() as connection:
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
        return _fragment(request, "candidatures/prepare.html", context)
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
    engine = _engine(request)
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
            prepare_application(
                SqlApplicationStore(connection),
                OffresDecisions(connection),
                account_id=account.id,
                offer_id=offer_id,
                interest=interest,
                now=_now(request),
                today=_today(request),
            )
    except InvalidChangeError as error:
        if not wants_fragment(request):
            return RedirectResponse(f"/offres/{offer_id}/fiche", status_code=303)
        return _box(request, account, offer_id, error=str(error))
    if not wants_fragment(request):
        return RedirectResponse("/candidatures", status_code=303)
    response = _box(request, account, offer_id, prepared=True)
    response.headers["HX-Trigger"] = OFFERS_CHANGED
    return response


# The page of an application (decision D3, Q23): for now its step « CV », the CV targeted at the offer (Q1–Q4, Q9–Q11).


@dataclass(frozen=True)
class CvItem:
    id: int
    label: str
    reason: str


@dataclass(frozen=True)
class CvView:
    """What the step « CV » shows: the selection in force with its reasons, what else the rules propose, and the
    posting's coverage."""

    groups: tuple[tuple[str, tuple[CvItem, ...]], ...]
    transversal: tuple[CvItem, ...]
    projects: tuple[CvItem, ...]
    other_projects: tuple[CvItem, ...]
    proposed: tuple[tuple[CvItem, bool], ...]  # (skill, technical)
    coverage: tuple[CoverageLine, ...]
    adjusted: bool  # the user adjusted the rules' proposal
    outdated: bool  # an adjustment the master CV's groups no longer allow: the rules propose again


@dataclass(frozen=True)
class ApplicationFile:
    application_id: int
    offer: OfferHeading
    stage: Stage | None
    profile: Profile
    layout: CvLayout
    slots: Slots
    view: CvView


def _dossier(
    request: Request, account: Account, application_id: int
) -> ApplicationFile | None:
    """The application of the account with its targeted CV; None for an unknown one or one of another account."""
    profile = profil_web.profile_of(request, account)
    slots = profil_web.cv_slots(request, account)
    with _engine(request).begin() as connection:
        store = SqlApplicationStore(connection)
        application = store.locked_application(account.id, application_id)
        if application is None:
            return None
        state = dossier(store.changes(application.id))
        heading = offres_web.offer_headings(
            connection, account.id, [application.offer_id]
        ).get(application.offer_id)
        analysis = offres_web.offer_analysis(
            connection, account.id, application.offer_id, profile, _today(request)
        )
        stored = store.cv_selection(application.id)
    if heading is None or analysis is None:
        return None
    proposal = target(profile.cv, profile, analysis, slots)
    kept = None if stored is None else selection_of(stored, profile.cv)
    layout = kept or proposal.layout
    return ApplicationFile(
        application_id=application.id,
        offer=heading,
        stage=state.stage if state.open else None,
        profile=profile,
        layout=layout,
        slots=slots,
        view=_cv_view(profile, layout, proposal, analysis, stored, kept),
    )


def _cv_view(
    profile: Profile,
    layout: CvLayout,
    proposal: Targeted,
    analysis: PostingAnalysis,
    stored: Mapping[str, object] | None,
    kept: CvLayout | None,
) -> CvView:
    skills = {skill.id: skill for skill in profile.skills}
    projects = {project.id: project for project in profile.projects}

    cited = cited_skills(profile, analysis)

    def skill(skill_id: int) -> CvItem:
        reason = proposal.reasons.get(("skill", skill_id))
        if reason is None:
            importance = cited.get(skill_id)
            reason = (
                "Ajoutée par toi"
                if importance is None
                else f"Citée par l'annonce ({IMPORTANCE_LABELS[importance].lower()}) : ajoutée par toi"
            )
        return CvItem(skill_id, skills[skill_id].label.fr, reason)

    def project(project_id: int, reason: str | None = None) -> CvItem:
        found = reason or proposal.reasons.get(
            ("project", project_id), "Ajouté par toi"
        )
        return CvItem(project_id, projects[project_id].content.name.fr, found)

    shown = {s for group in layout.groups for s in group.skill_ids} | set(
        layout.transversal
    )
    proposed = {
        skill_id: reason
        for skill_id, reason in proposal.proposed.items()
        if skill_id not in shown
    }
    lines = coverage(layout, profile, analysis)
    for line in lines:
        if line.coverage is Coverage.IN_PROFILE and line.skill_id is not None:
            proposed.setdefault(
                line.skill_id,
                f"{IMPORTANCE_LABELS[line.importance or Importance.DETECTED]} dans l'annonce",
            )
    return CvView(
        groups=tuple(
            (group.name.fr, tuple(skill(s) for s in group.skill_ids if s in skills))
            for group in layout.groups
        ),
        transversal=tuple(skill(s) for s in layout.transversal if s in skills),
        projects=tuple(project(p) for p in layout.projects if p in projects),
        other_projects=tuple(
            project(p.id, proposal.left_out.get(p.id, "Hors du CV"))
            for p in profile.projects
            if p.id not in layout.projects
        ),
        proposed=tuple(
            (
                CvItem(skill_id, skills[skill_id].label.fr, reason),
                skills[skill_id].content.category is SkillCategory.TECHNICAL,
            )
            for skill_id, reason in proposed.items()
            if skill_id in skills
        ),
        coverage=lines,
        adjusted=kept is not None,
        outdated=stored is not None and kept is None,
    )


# The gestures of the step « CV » (the pure functions of the master CV's layout, applied to the application's own).
CV_GESTURES: dict[str, Callable[[CvLayout, Profile, int, int | None], CvLayout]] = {
    "competence-monter": lambda cv, _, item, __: cv_layout.move_skill(cv, item, -1),
    "competence-descendre": lambda cv, _, item, __: cv_layout.move_skill(cv, item, 1),
    "competence-retirer": lambda cv, _, item, __: cv_layout.remove_skill(cv, item),
    "competence-ajouter": lambda cv, profile, item, group: cv_layout.place_skill(
        cv, profile, item, group or 0
    ),
    "projet-basculer": lambda cv, _, item, __: cv_layout.toggle_project(cv, item),
    "projet-monter": lambda cv, _, item, __: cv_layout.move_project(cv, item, -1),
    "projet-descendre": lambda cv, _, item, __: cv_layout.move_project(cv, item, 1),
}


def _dossier_page(
    request: Request,
    account: Account,
    application_id: int,
    *,
    error: str | None = None,
    cv_refusal: tuple[str, ...] = (),
    status_code: int = 200,
) -> Response:
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    context = {
        "dossier": found,
        "view": found.view,
        "error": error,
        "cv_refusal": cv_refusal,
        "importance_labels": IMPORTANCE_LABELS,
        "coverage_labels": COVERAGE_LABELS,
    }
    if wants_fragment(request):
        return _fragment(request, "candidatures/cv_step.html", context)
    return page(
        request,
        "candidatures/dossier.html",
        active="applications",
        status_code=status_code,
        context=context,
    )


@router.get("/{application_id}", response_class=HTMLResponse)
def dossier_page(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    return _dossier_page(request, account, application_id)


@router.post("/{application_id}/cv", response_class=HTMLResponse)
def adjust_cv(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    geste: Annotated[str, Form()],
    element: Annotated[int, Form()],
    groupe: Annotated[int | None, Form()] = None,
) -> Response:
    """One gesture on the application's CV: kept as its own selection (Q4), checked like the master CV (Q26)."""
    found = _dossier(request, account, application_id)
    gesture = CV_GESTURES.get(geste)
    if found is None or gesture is None:
        return Response(status_code=404)
    layout = gesture(found.layout, found.profile, element, groupe)
    try:
        check_layout(found.profile, layout, found.slots)
    except ProfileInputError as error:
        return _dossier_page(request, account, application_id, error=str(error))
    return _save_selection(request, account, application_id, selection_json(layout))


@router.post("/{application_id}/cv/proposition", response_class=HTMLResponse)
def reset_cv(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """Back to the rules' proposal (Q4): appended like any adjustment."""
    if not _owned(request, account, application_id):
        return Response(status_code=404)
    return _save_selection(request, account, application_id, None)


def _save_selection(
    request: Request,
    account: Account,
    application_id: int,
    layout: Mapping[str, JsonValue] | None,
) -> Response:
    try:
        with _engine(request).begin() as connection:
            adjust_cv_selection(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                layout=layout,
                now=_now(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(request, account, application_id, error=str(error))
    if not wants_fragment(request):
        return RedirectResponse(f"/candidatures/{application_id}", status_code=303)
    return _dossier_page(request, account, application_id)


@router.get("/{application_id}/cv.pdf")
def cv_pdf(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: str = "fr",
    apercu: bool = False,
) -> Response:
    """The CV of the application in French or in English (Q9), on the same selection; refused with its reasons."""
    language = "en" if langue == "en" else "fr"
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    profile = replace(found.profile, cv=found.layout)
    try:
        document, _ = profil_web.cv_document(request, account, profile, language)
    except CvRefusedError as error:
        return _dossier_page(
            request, account, application_id, cv_refusal=error.reasons, status_code=409
        )
    except RenderError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            cv_refusal=(error.reason,),
            status_code=409,
        )
    name = "_".join(profile.identity.full_name.split()) or "CV"
    disposition = "inline" if apercu else "attachment"
    return Response(
        document.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="CV_{name}_{language.upper()}.pdf"',
            "Cache-Control": "no-store",
        },
    )
