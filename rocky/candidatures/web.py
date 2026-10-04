"""Applications (step D1): the box « Préparer la candidature » of an offer's sheet and a plain list at /candidatures.

The screen 📝 Candidatures proper is step D6. Each route runs one use case in one transaction; the server renders
every state as HTML, HTMX swaps the fragments, and requests without HTMX get a redirection or a whole page.
Decision ``docs/decisions/D1-dossier-statuts.md``.
"""

from __future__ import annotations

import base64
import io
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection, Engine
from starlette.datastructures import FormData

from rocky.candidatures.letter import (
    Adaptation,
    Brief,
    LetterError,
    adapt,
    in_force,
    letter_sheet,
    letter_state,
    propose_message,
    sources_text,
)
from rocky.candidatures.letter_render import (
    LetterRefusedError,
    draw_letter,
    letter_fingerprint,
    render_letter,
)
from rocky.candidatures.letter_view import (
    ADAPTED,
    MINE,
    ORIGIN_LABELS,
    ORIGINAL,
    LetterView,
    adaptation_from_form,
    brief_of,
    job_and_company,
    letter_reference,
    letter_view,
    message_signals,
    preview_version,
    read_letter,
    read_message,
)
from rocky.candidatures.model import (
    CHANNEL_LABELS,
    DEFER_DAYS,
    ISSUES,
    STAGE_LABELS,
    Change,
    Channel,
    InvalidChangeError,
    LetterEntry,
    LetterState,
    LetterVersion,
    MessageVersion,
    NewPrefill,
    NewRevision,
    NextAction,
    Prefill,
    Revision,
    RevisionKind,
    Sending,
    Stage,
)
from rocky.candidatures.rules import (
    Journey,
    Step,
    dossier,
    is_overdue,
    journey,
    make_next_action,
    proposal,
    revision_filename,
    sending_in_force,
    sent_change,
)
from rocky.candidatures.send_view import (
    NONE,
    ConfirmForm,
    SendView,
    confirm_form,
    read_sending,
    send_view,
)
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
    NOT_READY,
    PREFILL_STAGES,
    adjust_cv_selection,
    cancel_last_change,
    change_stage,
    confirm_sending,
    defer_next_action,
    letter_ready,
    needs_reasons,
    prepare_application,
    record_prefill,
    record_revisions,
    set_next_action,
    skip_letter,
    validate_letter,
    validate_message,
)
from rocky.offres import web as offres_web
from rocky.offres.analysis.model import IMPORTANCE_LABELS, Importance, PostingAnalysis
from rocky.offres.analysis.usecases import Summary
from rocky.offres.decisions import (
    REASONS,
    Decision,
    DecisionValue,
    InvalidDecisionError,
    application_decision,
)
from rocky.offres.model import OfferHeading
from rocky.profil import letter_web as profil_letters
from rocky.profil import translation_web
from rocky.profil import web as profil_web
from rocky.profil.cv import layout as cv_layout
from rocky.profil.cv.check import CvCheck, Fact, check_cv
from rocky.profil.cv.layout import check_layout
from rocky.profil.cv.rendering import MISSING_ENGLISH, CvRefusedError
from rocky.profil.cv.template import Slots
from rocky.profil.model import CvLayout, Profile, SkillCategory
from rocky.profil.rules import ProfileInputError
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.events import JsonValue
from rocky.system.files import FileError, FileStore
from rocky.system.render import RenderError, rasterize
from rocky.system.shell import page, wants_fragment
from rocky.system.workstation import (
    FIELDS,
    JobFile,
    PrefillJob,
    Workstation,
    WorkstationClient,
    WorkstationUnavailableError,
    target_is_valid,
)

TEMPLATES = Path(__file__).parent / "templates"
# Refreshes the offers list when « Préparer » records a decision (``offres.web.OFFERS_CHANGED``).
OFFERS_CHANGED = offres_web.OFFERS_CHANGED

router = APIRouter(prefix="/candidatures")


def install(app: FastAPI) -> None:
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(stage_labels=STAGE_LABELS)
    # The Rocky workstation that prefills forms (decision D5, Q1); replaced by the tests.
    app.state.workstation = WorkstationClient(app.state.settings.workstation_url)
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
        return _fragment(request, "candidatures/list.html", context)
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
    retour: Annotated[str, Form()] = "",
) -> Response:
    """A stage change in one gesture, with the proposed next action; the user enters it (``saisie``) when the
    proposal has no date (Q3, « Entretien »). From the application's page (« CV prêt », « J'ai envoyé », D3 Q25), back
    to it."""
    if etape not in Stage or not _owned(request, account, application_id):
        return Response(status_code=404)
    stage = Stage(etape)
    if stage is Stage.SENT:
        # No sending without its date, channel and documents (decision D5, Q5): the confirmation form.
        target = f"/candidatures/{application_id}/envoi#envoi"
        if wants_fragment(request):
            return Response(status_code=200, headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)
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
    return _after_change(request, account, application_id)


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
            application_id = prepare_application(
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
    # Straight to the application's page (decision D3, Q25).
    target_url = f"/candidatures/{application_id}"
    if not wants_fragment(request):
        return RedirectResponse(target_url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": target_url})


# The page of an application (decision D3, Q23, Q25): 1. CV targeted at the offer (Q1–Q4, Q9–Q11), 2. Letter (D4),
# 3. Sending, by the user on the site where the offer is applied for.


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
    next_action: NextAction | None
    journey: Journey
    profile: Profile
    layout: CvLayout
    slots: Slots
    view: CvView
    analysis: PostingAnalysis
    letters: tuple[LetterEntry, ...] = ()
    messages: tuple[MessageVersion, ...] = ()
    # A stage « Envoyée » confirmed before D5, without sending: its letter is deduced from the dates (D4, Q20).
    sent_at: datetime | None = None
    sent_letter_id: int | None = (
        None  # the letter version of the revision sent (decision D5)
    )
    changes: tuple[Change, ...] = ()
    revisions: tuple[Revision, ...] = ()
    sendings: tuple[Sending, ...] = ()
    prefills: tuple[Prefill, ...] = ()
    summary: Summary | None = None
    interest: tuple[tuple[str, ...], str | None] | None = (
        None  # reasons and note of « Intéressé »
    )


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
        letters = tuple(store.letters(application.id))
        messages = tuple(store.messages(application.id))
        summary = offres_web.offer_summary(connection, account.id, application.offer_id)
        interest = offres_web.interested_reason(
            connection, account.id, application.offer_id
        )
        every_change = tuple(store.changes(application.id))
        revisions = tuple(store.revisions(application.id))
        sendings = tuple(store.sendings(application.id))
        prefills = tuple(store.prefills(application.id))
    if heading is None or analysis is None:
        return None
    proposal = target(profile.cv, profile, analysis, slots)
    kept = None if stored is None else selection_of(stored, profile.cv)
    layout = kept or proposal.layout
    sending = sending_in_force(every_change, sendings)
    sent = sent_change(every_change)
    letter_sent = None if sending is None else sending.letter_revision_id
    sent_letter_id = next((r.letter_id for r in revisions if r.id == letter_sent), None)
    return ApplicationFile(
        application_id=application.id,
        offer=heading,
        stage=state.stage if state.open else None,
        next_action=state.next_action if state.open else None,
        journey=journey(state.stage if state.open else None, letter_state(letters)),
        profile=profile,
        layout=layout,
        slots=slots,
        view=_cv_view(profile, layout, proposal, analysis, stored, kept),
        analysis=analysis,
        letters=letters,
        messages=messages,
        sent_at=sent.changed_at if sent is not None and sending is None else None,
        sent_letter_id=sent_letter_id,
        changes=every_change,
        revisions=revisions,
        sendings=sendings,
        prefills=prefills,
        summary=summary,
        interest=interest,
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


@dataclass(frozen=True)
class LetterContext:
    """The step « Lettre » in one language, and what its checks compare a text with (decision D4, Q8)."""

    view: LetterView
    brief: Brief
    reference: str  # the user's own letter
    sources: str  # what a proposed text may draw on


def _letter(
    request: Request,
    account: Account,
    found: ApplicationFile,
    language: str,
    *,
    editing: bool = False,
    adaptation: Adaptation | None = None,
    submitted: Mapping[str, str] | None = None,
) -> LetterContext:
    letters = profil_letters.generic_letters(request, account)
    generic = letters.of(language)
    brief = brief_of(
        language=language,
        offer=found.offer,
        profile=found.profile,
        layout=found.layout,
        analysis=found.analysis,
        summary=found.summary,
        interest=found.interest,
        generic=generic,
    )
    reference = letter_reference(generic)
    sources = sources_text(brief, found.profile)
    view = letter_view(
        language=language,
        offer=found.offer,
        generic=generic,
        english_outdated=letters.english_outdated,
        entries=found.letters,
        messages=found.messages,
        sent_at=found.sent_at,
        sent_letter_id=found.sent_letter_id,
        editing=editing,
        adaptation=adaptation,
        reference=reference,
        sources=sources,
        submitted=submitted,
    )
    return LetterContext(view, brief, reference, sources)


CV_STEP = "candidatures/cv_step.html"
LETTER_STEP = "candidatures/letter_step.html"
SEND_STEP = "candidatures/send_step.html"


def _dossier_page(
    request: Request,
    account: Account,
    application_id: int,
    *,
    error: str | None = None,
    cv_refusal: tuple[str, ...] = (),
    check: CvCheck | None = None,
    check_language: str = "fr",
    status_code: int = 200,
    language: str = "fr",
    editing: bool = False,
    adaptation: Adaptation | None = None,
    letter_error: str | None = None,
    letter_refusal: tuple[str, ...] = (),
    letter_check: CvCheck | None = None,
    proposed_message: tuple[str, tuple[str, ...]] | None = None,
    message_error: str | None = None,
    submitted: Mapping[str, str] | None = None,
    letter_preview: LetterPreview | None = None,
    send_error: str | None = None,
    confirming: bool = False,
    confirm_submitted: Mapping[str, str] | None = None,
    confirm_error: str | None = None,
    prefilling: bool = False,
    prefill_error: str | None = None,
    fragment: str = CV_STEP,
) -> Response:
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    send = _send(request, account, found, language)
    confirm: ConfirmForm | None = None
    if confirming or confirm_submitted is not None:
        confirm = confirm_form(send, _today(request), confirm_submitted, confirm_error)
    letter = _letter(
        request,
        account,
        found,
        language,
        editing=editing,
        adaptation=adaptation,
        submitted=submitted,
    )
    context = {
        "dossier": found,
        "view": found.view,
        "error": error,
        "cv_refusal": cv_refusal,
        "check": check,
        "language": check_language,
        # The English CV waits for texts in English: the translation screen is the way out.
        "missing_english": any(r.startswith(MISSING_ENGLISH) for r in cv_refusal),
        "to_review": translation_web.to_review(request, account),
        "english_outdated": translation_web.english_cv_outdated(request, account),
        "importance_labels": IMPORTANCE_LABELS,
        "coverage_labels": COVERAGE_LABELS,
        "apply_domain": urlsplit(found.offer.apply_at).hostname or "",
        "Stage": Stage,
        "Step": Step,
        "letter": letter.view,
        "letter_error": letter_error,
        "letter_refusal": letter_refusal,
        "letter_check": letter_check,
        "letter_preview": letter_preview,
        "letter_body": _letter_body(found, letter.view, _today(request)),
        "proposed_message": proposed_message,
        "message_error": message_error,
        "LetterState": LetterState,
        "origin_labels": ORIGIN_LABELS,
        "choices": {"original": ORIGINAL, "adapted": ADAPTED, "mine": MINE},
        "send": send,
        "send_error": send_error,
        "confirm": confirm,
        "prefilling": prefilling and found.stage in PREFILL_STAGES,
        "prefill_error": prefill_error,
        "channels": list(Channel),
        "channel_labels": CHANNEL_LABELS,
        "field_labels": FIELDS,
        "RevisionKind": RevisionKind,
        "NONE": NONE,
    }
    if wants_fragment(request):
        return _fragment(request, fragment, context)
    return page(
        request,
        "candidatures/dossier.html",
        active="applications",
        status_code=status_code,
        context=context,
    )


def _letter_body(found: ApplicationFile, view: LetterView, today: date) -> str:
    """The letter in force, to paste in a form (Q5)."""
    if view.version is None:
        return ""
    return letter_sheet(found.profile.identity, view.version, today).body


@router.get("/{application_id}", response_class=HTMLResponse)
def dossier_page(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    lettre: str = "fr",
    modifier: bool = False,
) -> Response:
    """``lettre``: the language of the step « Lettre » shown; ``modifier`` opens the letter in force to edit."""
    return _dossier_page(
        request, account, application_id, language=_language(lettre), editing=modifier
    )


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


@router.post("/{application_id}/cv/verifier", response_class=HTMLResponse)
def check_application_cv(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()] = "fr",
) -> Response:
    """« Vérifier ce CV » (decision D2, Q12) on the CV this application sends: its selection, its language."""
    language = "en" if langue == "en" else "fr"
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    profile = replace(found.profile, cv=found.layout)
    try:
        document, facts = profil_web.cv_document(request, account, profile, language)
    except CvRefusedError as error:
        return _dossier_page(request, account, application_id, cv_refusal=error.reasons)
    except RenderError as error:
        return _dossier_page(
            request, account, application_id, cv_refusal=(error.reason,)
        )
    return _dossier_page(
        request,
        account,
        application_id,
        check=check_cv(document.pdf, facts),
        check_language=language,
    )


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


# The step « Lettre » (decision D4) and the accompanying message of the step « Envoi » (Q1, Q12).


def _language(value: object) -> str:
    return "en" if value == "en" else "fr"


async def _form_data(request: Request) -> AsyncIterator[FormData]:
    form = await request.form()
    try:
        yield form
    finally:
        await form.close()


FormFields = Annotated[FormData, Depends(_form_data)]


def _to_dossier(application_id: int, anchor: str, language: str = "fr") -> Response:
    query = "?lettre=en" if language == "en" else ""
    return RedirectResponse(
        f"/candidatures/{application_id}{query}#{anchor}", status_code=303
    )


@router.post("/{application_id}/lettre/adapter", response_class=HTMLResponse)
def adapt_letter(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()] = "fr",
    consentement: Annotated[str, Form()] = "",
) -> Response:
    """« Adapter à l'annonce » (Q7, Q14, Q15): one call to the model after the user's consent; nothing is stored."""
    language = _language(langue)
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)

    def again(
        letter_error: str | None = None, adaptation: Adaptation | None = None
    ) -> Response:
        return _dossier_page(
            request,
            account,
            application_id,
            language=language,
            letter_error=letter_error,
            adaptation=adaptation,
            fragment=LETTER_STEP,
        )

    if not consentement:
        return again(
            letter_error="Coche l'accord d'envoi pour que Rocky propose une adaptation."
        )
    letter = _letter(request, account, found, language)
    if letter.view.refusal is not None:
        return again(letter_error=letter.view.refusal)
    try:
        adaptation = adapt(letter.brief, request.app.state.llm_model)
    except LetterError as error:
        return again(letter_error=error.reason)
    return again(adaptation=adaptation)


@router.post("/{application_id}/lettre/valider", response_class=HTMLResponse)
def validate(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """« Valider cette lettre » (Q11, Q17): a new version in force; the earlier ones stay."""
    language = _language(form.get("langue"))
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    letter = _letter(request, account, found, language)
    generic = letter.view.generic
    try:
        if generic is None:
            raise InvalidChangeError(letter.view.refusal or "Aucune lettre générique.")
        fields = {
            key: value for key, value in form.multi_items() if isinstance(value, str)
        }
        new = read_letter(
            fields,
            language=language,
            generic=generic,
            entries=found.letters,
            offer=found.offer,
            reference=letter.reference,
            sources=letter.sources,
        )
        with _engine(request).begin() as connection:
            validate_letter(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                letter=new,
                now=_now(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            language=language,
            editing=True,
            letter_error=str(error),
            fragment=LETTER_STEP,
        )
    return _to_dossier(application_id, "lettre", language)


@router.post("/{application_id}/lettre/sans", response_class=HTMLResponse)
def without_letter(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """« Pas de lettre pour cette candidature » (Q4, Q16)."""
    return _letter_gesture(request, account, application_id, skip_letter)


@router.post("/{application_id}/lettre/prete", response_class=HTMLResponse)
def letter_is_ready(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """« Lettre prête : passer à l'envoi » (Q16)."""
    return _letter_gesture(request, account, application_id, letter_ready)


def _letter_gesture(
    request: Request,
    account: Account,
    application_id: int,
    use_case: Callable[..., object],
) -> Response:
    if not _owned(request, account, application_id):
        return Response(status_code=404)
    try:
        with _engine(request).begin() as connection:
            use_case(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                now=_now(request),
                today=_today(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            letter_error=str(error),
            fragment=LETTER_STEP,
        )
    return _to_dossier(application_id, "envoi")


def _letter_pdf(
    request: Request, account: Account, application_id: int, language: str
) -> tuple[bytes, LetterVersion, ApplicationFile] | Response:
    """The PDF of the letter in force; or the page telling why there is none (409)."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    version = in_force(found.letters, language)
    preview = None
    try:
        if version is None:
            raise LetterRefusedError(("Valide d'abord cette lettre.",))
        sheet = letter_sheet(found.profile.identity, version, _today(request))
        pdf, problems = draw_letter(sheet)
        if not problems:
            return pdf, version, found
        # Refused, and shown: the page says what spills over (decision D4, recette).
        reasons, preview = problems, _preview(pdf, problems)
    except LetterRefusedError as error:
        reasons = error.reasons
    except RenderError as error:
        reasons = (error.reason,)
    return _dossier_page(
        request,
        account,
        application_id,
        language=language,
        letter_refusal=reasons,
        letter_preview=preview,
        status_code=409,
        fragment=LETTER_STEP,
    )


@dataclass(frozen=True)
class LetterPreview:
    """The page of the letter as it would be sent, as an image, and what makes it unfit."""

    png_base64: str
    problems: tuple[str, ...]


PREVIEW_DPI = 110


def _preview(pdf: bytes, problems: tuple[str, ...]) -> LetterPreview:
    buffer = io.BytesIO()
    rasterize(pdf, PREVIEW_DPI)[0].save(buffer, format="PNG", optimize=True)
    return LetterPreview(base64.b64encode(buffer.getvalue()).decode(), problems)


@router.post("/{application_id}/lettre/apercu", response_class=HTMLResponse)
def preview_letter(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """« Aperçu de la lettre »: the letter as the form composes it (nothing stored), or the one in force."""
    language = _language(form.get("langue"))
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    letter = _letter(request, account, found, language)
    generic = letter.view.generic
    fields = {key: value for key, value in form.multi_items() if isinstance(value, str)}
    editing = "empreinte" in fields and generic is not None
    error_text: str | None = None
    preview: LetterPreview | None = None
    try:
        if editing and generic is not None:
            version: LetterVersion | None = preview_version(
                read_letter(
                    fields,
                    language=language,
                    generic=generic,
                    entries=found.letters,
                    offer=found.offer,
                    reference=letter.reference,
                    sources=letter.sources,
                ),
                _now(request),
            )
        else:
            version = letter.view.version
        if version is None:
            raise InvalidChangeError("Rien à montrer : compose d'abord ta lettre.")
        pdf, problems = draw_letter(
            letter_sheet(found.profile.identity, version, _today(request))
        )
        preview = _preview(pdf, problems)
    except InvalidChangeError as error:
        error_text = str(error)
    except RenderError as error:
        error_text = error.reason
    return _dossier_page(
        request,
        account,
        application_id,
        language=language,
        editing=editing,
        adaptation=adaptation_from_form(fields, generic)
        if editing and generic is not None
        else None,
        submitted=fields if editing else None,
        letter_error=error_text,
        letter_preview=preview,
        fragment=LETTER_STEP,
    )


@router.get("/{application_id}/lettre.pdf")
def letter_pdf(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: str = "fr",
    apercu: bool = False,
) -> Response:
    language = _language(langue)
    rendered = _letter_pdf(request, account, application_id, language)
    if isinstance(rendered, Response):
        return rendered
    pdf, _, found = rendered
    name = "_".join(found.profile.identity.full_name.split()) or "Lettre"
    disposition = "inline" if apercu else "attachment"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="Lettre_{name}_{language.upper()}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/{application_id}/lettre/verifier", response_class=HTMLResponse)
def check_letter(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()] = "fr",
) -> Response:
    """« Vérifier cette lettre » (Q19): the three PDF readers on the letter in force."""
    language = _language(langue)
    rendered = _letter_pdf(request, account, application_id, language)
    if isinstance(rendered, Response):
        return rendered
    pdf, version, found = rendered
    _, company = job_and_company(found.offer)
    facts = [
        Fact("Nom", found.profile.identity.full_name),
        Fact("Objet", version.header.subject),
        Fact("Entreprise", company),
        *(
            Fact("Paragraphe", " ".join(p.text.split()[:8]))
            for p in version.paragraphs
            if p.text
        ),
    ]
    return _dossier_page(
        request,
        account,
        application_id,
        language=language,
        letter_check=check_cv(pdf, [f for f in facts if f.text], document="la lettre"),
        fragment=LETTER_STEP,
    )


@router.post("/{application_id}/message/proposer", response_class=HTMLResponse)
def propose_accompanying_message(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()] = "fr",
    consentement: Annotated[str, Form()] = "",
) -> Response:
    """« Proposer un message » (Q12): one call on the user's gesture, never automatic; nothing stored."""
    language = _language(langue)
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)

    def again(
        message_error: str | None = None,
        proposed: tuple[str, tuple[str, ...]] | None = None,
    ) -> Response:
        return _dossier_page(
            request,
            account,
            application_id,
            language=language,
            message_error=message_error,
            proposed_message=proposed,
            fragment=SEND_STEP,
        )

    if not consentement:
        return again(
            message_error="Coche l'accord d'envoi pour que Rocky propose un message."
        )
    letter = _letter(request, account, found, language)
    try:
        text = propose_message(
            letter.brief, letter.view.why_you, request.app.state.llm_model
        )
    except LetterError as error:
        return again(message_error=error.reason)
    found_signals = message_signals(text, language, letter.reference, letter.sources)
    return again(proposed=(text, found_signals))


@router.post("/{application_id}/message/valider", response_class=HTMLResponse)
def validate_accompanying_message(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()] = "fr",
    texte: Annotated[str, Form()] = "",
    propose: Annotated[str, Form()] = "",
) -> Response:
    language = _language(langue)
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    letter = _letter(request, account, found, language)
    message = read_message(
        texte,
        propose,
        language=language,
        reference=letter.reference,
        sources=letter.sources,
    )
    try:
        with _engine(request).begin() as connection:
            validate_message(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                message=message,
                now=_now(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            language=language,
            message_error=str(error),
            proposed_message=(message.text, message.signals),
            fragment=SEND_STEP,
        )
    return _to_dossier(application_id, "envoi", language)


# The step « Envoi »: revisions, sending, prefilling (decision D5).


def _files(request: Request) -> FileStore:
    root = request.app.state.settings.storage_root
    if root is None:
        raise InvalidChangeError(
            "Le stockage des fichiers n'est pas configuré (ROCKY_STORAGE_ROOT)."
        )
    return FileStore(root)


def _letter_to_send(found: ApplicationFile, language: str) -> LetterVersion | None:
    """The letter that goes with the CV: none once « Pas de lettre » is chosen (D4, Q4)."""
    if letter_state(found.letters) is LetterState.SKIPPED:
        return None
    return in_force(found.letters, language)


def _send(
    request: Request, account: Account, found: ApplicationFile, language: str
) -> SendView:
    """The step « Envoi » in ``language``. What the documents are made from now is computed only when a revision of
    that language exists (no rendering: the HTML only)."""
    version = _letter_to_send(found, language)
    inputs: dict[RevisionKind, str | None] = {}
    if any(revision.language == language for revision in found.revisions):
        profile = replace(found.profile, cv=found.layout)
        inputs[RevisionKind.CV] = profil_web.cv_fingerprint(
            request, account, profile, language
        )
        inputs[RevisionKind.LETTER] = (
            None
            if version is None
            else letter_fingerprint(
                letter_sheet(found.profile.identity, version, _today(request))
            )
        )
    return send_view(
        language=language,
        revisions=found.revisions,
        inputs=inputs,
        letter=letter_state(found.letters),
        letter_in_language=version is not None,
        messages=found.messages,
        changes=found.changes,
        sendings=found.sendings,
        prefills=found.prefills,
        stage=found.stage,
        identity=found.profile.identity,
        apply_url=found.offer.apply_at,
    )


@dataclass(frozen=True)
class Made:
    """A PDF just rendered, before it is stored."""

    kind: RevisionKind
    inputs_sha256: str
    letter_id: int | None
    pdf: bytes


def _make(
    request: Request, account: Account, found: ApplicationFile, language: str
) -> list[Made]:
    """The CV of the application and the letter in force in ``language``, both rendered before anything is written;
    raises ``CvRefusedError``, ``LetterRefusedError`` or ``RenderError`` with the reasons."""
    profile = replace(found.profile, cv=found.layout)
    inputs = profil_web.cv_fingerprint(request, account, profile, language)
    document, _ = profil_web.cv_document(request, account, profile, language)
    if inputs is None:  # the CV rendered: its template is readable
        raise CvRefusedError(("Ton gabarit de CV est illisible.",))
    made = [Made(RevisionKind.CV, inputs, None, document.pdf)]
    version = _letter_to_send(found, language)
    if version is not None:
        sheet = letter_sheet(found.profile.identity, version, _today(request))
        made.append(
            Made(
                RevisionKind.LETTER,
                letter_fingerprint(sheet),
                version.id,
                render_letter(sheet),
            )
        )
    return made


@router.post("/{application_id}/documents", response_class=HTMLResponse)
def generate(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()] = "fr",
) -> Response:
    """« Générer les PDF à envoyer » (Q2): each PDF stored once under its hash, then its revision; the earlier ones
    stay. A file written before a transaction that fails is left without row: it changes nothing."""
    language = _language(langue)
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    try:
        files = _files(request)
        revisions = []
        for made in _make(request, account, found, language):
            stored = files.put_file(account.id, "candidatures", made.pdf, "pdf")
            revisions.append(
                NewRevision(
                    made.kind,
                    language,
                    stored.path,
                    stored.sha256,
                    made.inputs_sha256,
                    made.letter_id,
                )
            )
        with _engine(request).begin() as connection:
            record_revisions(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                revisions=revisions,
                now=_now(request),
            )
    except (CvRefusedError, LetterRefusedError) as error:
        reason = " ".join(error.reasons)
    except RenderError as error:
        reason = error.reason
    except InvalidChangeError as error:
        reason = str(error)
    else:
        return _to_dossier(application_id, "envoi", language)
    return _dossier_page(
        request,
        account,
        application_id,
        language=language,
        send_error=f"Rien n'a été généré : {reason}",
        fragment=SEND_STEP,
    )


def _disposition(kind: str, filename: str) -> str:
    """``Content-Disposition`` for any name: an ASCII fallback and the exact name (RFC 6266)."""
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/{application_id}/documents/{revision_id}.pdf")
def revision_pdf(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    revision_id: int,
    apercu: bool = False,
) -> Response:
    """A revision exactly as it was generated: its bytes are read back with their hash checked (Q2)."""
    with _engine(request).begin() as connection:
        store = SqlApplicationStore(connection)
        if store.locked_application(account.id, application_id) is None:
            return Response(status_code=404)
        revision = next(
            (r for r in store.revisions(application_id) if r.id == revision_id), None
        )
    if revision is None:
        return Response(status_code=404)
    try:
        content = _files(request).read_file(revision.path, revision.sha256)
    except FileError as error:
        reason = error.reason
    except InvalidChangeError as error:
        reason = str(error)
    else:
        name = profil_web.profile_of(request, account).identity.full_name
        filename = revision_filename(revision.kind, name, revision.language)
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _disposition(
                    "inline" if apercu else "attachment", filename
                ),
                "Cache-Control": "no-store",
            },
        )
    return _dossier_page(
        request,
        account,
        application_id,
        language=revision.language,
        send_error=f"Ce PDF ne peut pas être servi : {reason}",
        status_code=409,
        fragment=SEND_STEP,
    )


@router.get("/{application_id}/envoi", response_class=HTMLResponse)
def sending_form(
    request: Request, account: CurrentAccount, application_id: int, lettre: str = "fr"
) -> Response:
    """« J'ai envoyé ma candidature »: the form of the sending (Q3, Q5), the latest revisions checked."""
    return _dossier_page(
        request,
        account,
        application_id,
        language=_language(lettre),
        confirming=True,
        fragment=SEND_STEP,
    )


@router.post("/{application_id}/envoi", response_class=HTMLResponse)
def confirm(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """The sending confirmed: the stage « Envoyée » and what documents it, in one transaction."""
    language = _language(form.get("langue"))
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    fields = {key: value for key, value in form.multi_items() if isinstance(value, str)}
    try:
        sending = read_sending(fields, _send(request, account, found, language))
        with _engine(request).begin() as connection:
            confirm_sending(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                sending=sending,
                now=_now(request),
                today=_today(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            language=language,
            confirm_submitted=fields,
            confirm_error=str(error),
            fragment=SEND_STEP,
        )
    return _to_dossier(application_id, "envoi", language)


@router.get("/{application_id}/preremplir", response_class=HTMLResponse)
def prefill_panel(
    request: Request, account: CurrentAccount, application_id: int, lettre: str = "fr"
) -> Response:
    """What the workstation will put in the form, to confirm before it does (Q1, Q4)."""
    return _dossier_page(
        request,
        account,
        application_id,
        language=_language(lettre),
        prefilling=True,
        fragment=SEND_STEP,
    )


CHANGED_SINCE_SHOWN = (
    "Les PDF à envoyer ont changé depuis l'affichage : relis la confirmation."
)


@router.post("/{application_id}/preremplir", response_class=HTMLResponse)
def prefill(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """« Préremplir le formulaire » (Q1, Q4, Q6): the exact revisions shown, read back and checked, handed to the
    workstation; once it took the form, its report and the stage « Préremplie » are written. Nothing is written when
    it did not."""
    language = _language(form.get("langue"))
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)

    def again(error: str) -> Response:
        return _dossier_page(
            request,
            account,
            application_id,
            language=language,
            prefilling=True,
            prefill_error=error,
            fragment=SEND_STEP,
        )

    if found.stage not in PREFILL_STAGES:
        return again(NOT_READY)
    if not form.get("consentement"):
        return again(
            "Coche la confirmation : ces données et ces fichiers vont dans le formulaire du site."
        )
    view = _send(request, account, found, language)
    cv, letter = view.latest(RevisionKind.CV), view.latest(RevisionKind.LETTER)
    if cv is None:
        return again("Génère d'abord les PDF à envoyer.")
    shown = (form.get("cv"), form.get("lettre"))
    if shown != (str(cv.revision.id), str(letter.revision.id) if letter else NONE):
        return again(CHANGED_SINCE_SHOWN)
    target_url = found.offer.apply_at
    if not target_is_valid(target_url):
        return again("Le lien de candidature de cette offre n'est pas une page web.")
    workstation: Workstation = request.app.state.workstation
    try:
        files = _files(request)
        job = PrefillJob(
            target_url,
            view.fields,
            tuple(
                JobFile(
                    line.revision.kind.value,
                    line.filename,
                    files.read_file(line.revision.path, line.revision.sha256),
                )
                for line in (cv, letter)
                if line is not None
            ),
        )
        report = workstation.prefill(job)
        with _engine(request).begin() as connection:
            record_prefill(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                prefill=NewPrefill(
                    target_url,
                    cv.revision.id,
                    None if letter is None else letter.revision.id,
                    None if view.message is None else view.message.id,
                    report.filled,
                    report.missing,
                ),
                now=_now(request),
                today=_today(request),
            )
    except FileError as error:
        return again(error.reason)
    except WorkstationUnavailableError as error:
        return again(error.reason)
    except InvalidChangeError as error:
        return again(str(error))
    return _to_dossier(application_id, "envoi", language)
