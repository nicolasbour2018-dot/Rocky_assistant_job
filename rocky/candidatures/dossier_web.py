"""The page of an application (decisions D3, D4, D5): its CV, its letter, its sending, step by step."""

from __future__ import annotations

import base64
import io
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
    read_switch,
)
from rocky.candidatures.model import (
    BEFORE_SENDING,
    CHANNEL_LABELS,
    DEFAULT_LANGUAGE,
    DEFER_DAYS,
    FOLLOW_UP_STAGES,
    FORWARD,
    ISSUES,
    LANGUAGE_LABELS,
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
    Note,
    NoteRow,
    Prefill,
    Revision,
    RevisionKind,
    Sending,
    Stage,
)
from rocky.candidatures.rules import (
    STEP_LABELS,
    Journey,
    Step,
    done_message,
    dossier,
    journey,
    language_in_force,
    last_done,
    notes_in_force,
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
from rocky.candidatures.timeline import Line, timeline
from rocky.candidatures.usecases import (
    NOT_READY,
    PREFILL_STAGES,
    add_note,
    adjust_cv_selection,
    choose_language,
    confirm_sending,
    letter_ready,
    record_prefill,
    record_revisions,
    remove_note,
    set_employer_domain,
    skip_letter,
    validate_letter,
    validate_message,
)
from rocky.candidatures.web_common import (
    engine_of,
    now_of,
    owns,
    render_fragment,
    today_of,
)
from rocky.offres import web as offres_web
from rocky.offres.analysis.model import IMPORTANCE_LABELS, Importance, PostingAnalysis
from rocky.offres.analysis.usecases import Summary
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
from rocky.system.events import JsonValue, StoredEvent, events_about
from rocky.system.files import FileError, FileStore
from rocky.system.render import RenderError, rasterize
from rocky.system.shell import content_disposition, page, wants_fragment
from rocky.system.workstation import (
    FIELDS,
    JobFile,
    PrefillJob,
    Workstation,
    WorkstationUnavailableError,
    target_is_valid,
)

router = APIRouter(prefix="/candidatures")


# The page of an application, one step at a time (decision D6, Q2): 1. CV targeted at the offer (D3), 2. Letter (D4),
# 3. Sending, by the user on the site where the offer is applied for (D5), 4. Follow-up (D6).


def dossier_url(application_id: int, step: Step | None = None) -> str:
    """The page of the application on ``step``; without it, on the step it is at."""
    base = f"/candidatures/{application_id}"
    return base if step is None else f"{base}?etape={step.value}"


# « J'ai envoyé ma candidature »: the step « Envoi » with its confirmation open.
CONFIRM_URL = "/candidatures/{}/envoi"


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
    prefills: tuple[Prefill, ...] = ()  # DORMANT: forms prefilled by the workstation
    summary: Summary | None = None
    interest: tuple[tuple[str, ...], str | None] | None = (
        None  # reasons and note of « Intéressé »
    )
    language: str = (
        DEFAULT_LANGUAGE  # of the CV, the letter, the message, the PDFs (D6, Q4)
    )
    note_rows: tuple[NoteRow, ...] = ()
    events: tuple[StoredEvent, ...] = ()

    @property
    def notes(self) -> list[Note]:
        return notes_in_force(self.note_rows)

    @property
    def timeline(self) -> list[Line]:
        texts = {row.id: row.text for row in self.note_rows if row.text is not None}
        return timeline(self.events, texts)

    @property
    def deadline(self) -> date | None:
        """The offer's deadline, while the application is not sent (D6, Q8)."""
        return self.analysis.deadline if self.stage in BEFORE_SENDING else None


def _dossier(
    request: Request, account: Account, application_id: int
) -> ApplicationFile | None:
    """The application of the account with its targeted CV; None for an unknown one or one of another account."""
    profile = profil_web.profile_of(request, account)
    slots = profil_web.cv_slots(request, account)
    with engine_of(request).begin() as connection:
        store = SqlApplicationStore(connection)
        application = store.locked_application(account.id, application_id)
        if application is None:
            return None
        state = dossier(store.changes(application.id))
        heading = offres_web.offer_headings(
            connection, account.id, [application.offer_id]
        ).get(application.offer_id)
        analysis = offres_web.offer_analysis(
            connection, account.id, application.offer_id, profile, today_of(request)
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
        language = language_in_force(store.language(application.id))
        note_rows = tuple(store.notes(application.id))
        journal = tuple(
            events_about(connection, account.id, "application", str(application.id))
        )
        sendings = tuple(store.sendings(application.id))
        prefills = tuple(store.prefills(application.id))
    if heading is None or analysis is None:
        return None
    proposal = target(profile.cv, profile, analysis, slots)
    kept = None if stored is None else selection_of(stored, profile)
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
        language=language,
        note_rows=note_rows,
        events=journal,
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
    switch: tuple[int, str] | None = None,
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
        switch=switch,
    )
    return LetterContext(view, brief, reference, sources)


STEP_TEMPLATES = {
    Step.CV: "candidatures/cv_step.html",
    Step.LETTER: "candidatures/letter_step.html",
    Step.SEND: "candidatures/send_step.html",
    Step.FOLLOW: "candidatures/follow_step.html",
}


def _dossier_page(
    request: Request,
    account: Account,
    application_id: int,
    *,
    step: Step | None = None,
    error: str | None = None,
    cv_refusal: tuple[str, ...] = (),
    check: CvCheck | None = None,
    status_code: int = 200,
    editing: bool = False,
    adaptation: Adaptation | None = None,
    letter_error: str | None = None,
    letter_refusal: tuple[str, ...] = (),
    letter_check: CvCheck | None = None,
    proposed_message: tuple[str, tuple[str, ...]] | None = None,
    message_error: str | None = None,
    submitted: Mapping[str, str] | None = None,
    letter_switch: tuple[int, str] | None = None,
    letter_preview: LetterPreview | None = None,
    send_error: str | None = None,
    confirming: bool = False,
    confirm_submitted: Mapping[str, str] | None = None,
    confirm_error: str | None = None,
    prefilling: bool = False,  # DORMANT: the panel « Préremplir »
    prefill_error: str | None = None,
    follow_error: str | None = None,
    editing_action: bool = False,
    note_text: str = "",
    done: bool = False,
) -> Response:
    """The page of the application on ``step`` (by default, the step it is at), or that step alone for HTMX."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    shown = step or found.journey.current
    language = found.language
    send = _send(request, account, found, language)
    confirm: ConfirmForm | None = None
    if shown is Step.SEND and not found.journey.sent:
        confirm = confirm_form(
            send, today_of(request), confirm_submitted, confirm_error
        )
    letter = _letter(
        request,
        account,
        found,
        language,
        editing=editing,
        adaptation=adaptation,
        submitted=submitted,
        switch=letter_switch,
    )
    context = {
        "dossier": found,
        "step": shown,
        "step_labels": STEP_LABELS,
        "language_labels": LANGUAGE_LABELS,
        "view": found.view,
        "error": error,
        "cv_refusal": cv_refusal,
        "check": check,
        "language": language,
        # The English CV waits for texts in English: the translation screen is the way out.
        "missing_english": any(r.startswith(MISSING_ENGLISH) for r in cv_refusal),
        "to_review": translation_web.to_review(request, account)
        if language == "en"
        else (),
        "english_outdated": language == "en"
        and translation_web.english_cv_outdated(request, account),
        "importance_labels": IMPORTANCE_LABELS,
        "coverage_labels": COVERAGE_LABELS,
        "apply_domain": urlsplit(found.offer.apply_at).hostname or "",
        "today": today_of(request),
        "Stage": Stage,
        "Step": Step,
        "letter": letter.view,
        "letter_error": letter_error,
        "letter_refusal": letter_refusal,
        "letter_check": letter_check,
        "letter_preview": letter_preview,
        "letter_body": _letter_body(found, letter.view, today_of(request)),
        "proposed_message": proposed_message,
        "message_error": message_error,
        "LetterState": LetterState,
        "origin_labels": ORIGIN_LABELS,
        "choices": {"original": ORIGINAL, "adapted": ADAPTED, "mine": MINE},
        "send": send,
        "send_error": send_error,
        "confirm": confirm,
        "confirm_open": confirming or confirm_submitted is not None,
        "prefilling": prefilling and found.stage in PREFILL_STAGES,
        "prefill_error": prefill_error,
        "channels": list(Channel),
        "channel_labels": CHANNEL_LABELS,
        "field_labels": FIELDS,
        "RevisionKind": RevisionKind,
        "NONE": NONE,
        "follow_error": follow_error,
        # What « Fait » did (recette of D6), while it is the latest change in force.
        "done_notice": done_message(*finished)
        if done and (finished := last_done(found.changes)) is not None
        else None,
        "editing_action": editing_action,
        "note_text": note_text,
        "defer_days": DEFER_DAYS,
        "stages": list(Stage),
        "forward": [s for s in FORWARD if s is not Stage.PREFILLED],
        "issues": [s for s in Stage if s in ISSUES],
        "follow_up_stages": FOLLOW_UP_STAGES,
        "employer_domain": _employer_domain(request, application_id),
    }
    if wants_fragment(request):
        return render_fragment(request, STEP_TEMPLATES[shown], context)
    return page(
        request,
        "candidatures/dossier.html",
        active="applications",
        status_code=status_code,
        context=context,
    )


def _employer_domain(request: Request, application_id: int) -> str | None:
    with engine_of(request).connect() as connection:
        return SqlApplicationStore(connection).employer_domain(application_id)


def follow_up_refused(
    request: Request,
    account: Account,
    application_id: int,
    error: str,
    *,
    editing: bool = False,
) -> Response:
    """A gesture of the step « Suivi » refused: the step again, with its reason (the list's gestures, ``web``)."""
    return _dossier_page(
        request,
        account,
        application_id,
        step=Step.FOLLOW,
        follow_error=error,
        editing_action=editing,
    )


def _letter_body(found: ApplicationFile, view: LetterView, today: date) -> str:
    """The letter in force, to paste in a form (Q5)."""
    if view.version is None:
        return ""
    return letter_sheet(found.profile.identity, view.version, today).body


def _shown_step(etape: str) -> Step | None:
    return Step(etape) if etape in set(Step) else None


@router.get("/{application_id}", response_class=HTMLResponse)
def dossier_page(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    etape: str = "",
    modifier: bool = False,
    action: bool = False,
    fait: bool = False,
) -> Response:
    """``etape``: the step shown, by default the one the application is at; ``modifier`` opens the letter in force to
    edit; ``action`` the next action (step « Suivi »)."""
    return _dossier_page(
        request,
        account,
        application_id,
        step=_shown_step(etape),
        editing=modifier,
        editing_action=action,
        done=fait,
    )


@router.post("/{application_id}/langue", response_class=HTMLResponse)
def language(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    langue: Annotated[str, Form()],
    etape: Annotated[str, Form()] = "",
) -> Response:
    """The language of the application (D6, Q4): back to the step it was chosen from."""
    try:
        with engine_of(request).begin() as connection:
            choose_language(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                language=langue,
                now=now_of(request),
            )
    except LookupError:
        return Response(status_code=404)
    except InvalidChangeError as error:
        return _dossier_page(
            request, account, application_id, step=_shown_step(etape), error=str(error)
        )
    return RedirectResponse(
        dossier_url(application_id, _shown_step(etape)), status_code=303
    )


@router.post("/{application_id}/domaine", response_class=HTMLResponse)
def employer_domain(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    domaine: Annotated[str, Form()] = "",
) -> Response:
    """The employer's e-mail domain (decision E2, Q3): its replies are recognised by it in 📬 Messages."""
    try:
        with engine_of(request).begin() as connection:
            set_employer_domain(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                typed=domaine,
                now=now_of(request),
            )
    except LookupError:
        return Response(status_code=404)
    except InvalidChangeError as error:
        return follow_up_refused(request, account, application_id, str(error))
    return _to_step(application_id, Step.FOLLOW)


@router.post("/{application_id}/notes", response_class=HTMLResponse)
def note(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    texte: Annotated[str, Form()] = "",
) -> Response:
    """A dated note (D6, Q6)."""
    try:
        with engine_of(request).begin() as connection:
            add_note(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                text=texte,
                now=now_of(request),
            )
    except LookupError:
        return Response(status_code=404)
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            step=Step.FOLLOW,
            follow_error=str(error),
            note_text=texte,
        )
    return _to_step(application_id, Step.FOLLOW)


@router.post("/{application_id}/notes/{note_id}/retirer", response_class=HTMLResponse)
def unnote(
    request: Request, account: CurrentAccount, application_id: int, note_id: int
) -> Response:
    """Remove a note (D6, Q6): the removal is kept."""
    try:
        with engine_of(request).begin() as connection:
            remove_note(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                note_id=note_id,
                now=now_of(request),
            )
    except LookupError:
        return Response(status_code=404)
    except InvalidChangeError as error:
        return follow_up_refused(request, account, application_id, str(error))
    return _to_step(application_id, Step.FOLLOW)


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
        return _dossier_page(
            request, account, application_id, step=Step.CV, error=str(error)
        )
    return _save_selection(request, account, application_id, selection_json(layout))


@router.post("/{application_id}/cv/proposition", response_class=HTMLResponse)
def reset_cv(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """Back to the rules' proposal (Q4): appended like any adjustment."""
    if not owns(request, account, application_id):
        return Response(status_code=404)
    return _save_selection(request, account, application_id, None)


def _save_selection(
    request: Request,
    account: Account,
    application_id: int,
    layout: Mapping[str, JsonValue] | None,
) -> Response:
    try:
        with engine_of(request).begin() as connection:
            adjust_cv_selection(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                layout=layout,
                now=now_of(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request, account, application_id, step=Step.CV, error=str(error)
        )
    if not wants_fragment(request):
        return _to_step(application_id, Step.CV)
    return _dossier_page(request, account, application_id, step=Step.CV)


@router.post("/{application_id}/cv/verifier", response_class=HTMLResponse)
def check_application_cv(
    request: Request,
    account: CurrentAccount,
    application_id: int,
) -> Response:
    """« Vérifier ce CV » (decision D2, Q12) on the CV this application sends: its selection, its language."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    profile = replace(found.profile, cv=found.layout)
    try:
        document, facts = profil_web.cv_document(
            request, account, profile, found.language
        )
    except CvRefusedError as error:
        return _dossier_page(
            request, account, application_id, step=Step.CV, cv_refusal=error.reasons
        )
    except RenderError as error:
        return _dossier_page(
            request, account, application_id, step=Step.CV, cv_refusal=(error.reason,)
        )
    return _dossier_page(
        request,
        account,
        application_id,
        step=Step.CV,
        check=check_cv(document.pdf, facts),
    )


@router.get("/{application_id}/cv.pdf")
def cv_pdf(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    apercu: bool = False,
) -> Response:
    """The CV of the application in its language (Q9; D6, Q4); refused with its reasons."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language
    profile = replace(found.profile, cv=found.layout)
    try:
        document, _ = profil_web.cv_document(request, account, profile, language)
    except CvRefusedError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            step=Step.CV,
            cv_refusal=error.reasons,
            status_code=409,
        )
    except RenderError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            step=Step.CV,
            cv_refusal=(error.reason,),
            status_code=409,
        )
    name = "_".join(profile.identity.full_name.split()) or "CV"
    disposition = "inline" if apercu else "attachment"
    return Response(
        document.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                disposition, f"CV_{name}_{language.upper()}.pdf"
            ),
            "Cache-Control": "no-store",
        },
    )


# The step « Lettre » (decision D4) and the accompanying message of the step « Envoi » (Q1, Q12).


async def _form_data(request: Request) -> AsyncIterator[FormData]:
    form = await request.form()
    try:
        yield form
    finally:
        await form.close()


FormFields = Annotated[FormData, Depends(_form_data)]


def _to_step(application_id: int, step: Step) -> Response:
    return RedirectResponse(dossier_url(application_id, step), status_code=303)


@router.post("/{application_id}/lettre/adapter", response_class=HTMLResponse)
def adapt_letter(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    consentement: Annotated[str, Form()] = "",
) -> Response:
    """« Adapter à l'annonce » (Q7, Q14, Q15): one call to the model after the user's consent; nothing is stored."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language

    def again(
        letter_error: str | None = None, adaptation: Adaptation | None = None
    ) -> Response:
        return _dossier_page(
            request,
            account,
            application_id,
            letter_error=letter_error,
            adaptation=adaptation,
            step=Step.LETTER,
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
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language
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
        with engine_of(request).begin() as connection:
            validate_letter(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                letter=new,
                now=now_of(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            editing=True,
            letter_error=str(error),
            step=Step.LETTER,
        )
    return _to_step(application_id, Step.LETTER)


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
    if not owns(request, account, application_id):
        return Response(status_code=404)
    today = today_of(request)
    try:
        with engine_of(request).begin() as connection:
            store = SqlApplicationStore(connection)
            application = store.locked_application(account.id, application_id)
            assert application is not None  # noqa: S101  (owns() checked it)
            # The sending proposed by the gesture stops at the offer's deadline (decision D6, Q8; step H1).
            deadline = offres_web.offer_deadlines(
                connection, account.id, [application.offer_id], today
            ).get(application.offer_id)
            use_case(
                store,
                account_id=account.id,
                application_id=application_id,
                now=now_of(request),
                today=today,
                deadline=deadline,
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            letter_error=str(error),
            step=Step.LETTER,
        )
    return _to_step(application_id, Step.SEND)


def _letter_pdf(
    request: Request, account: Account, application_id: int
) -> tuple[bytes, LetterVersion, ApplicationFile] | Response:
    """The PDF of the letter in force in the application's language; or the page telling why there is none (409)."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    version = in_force(found.letters, found.language)
    preview = None
    try:
        if version is None:
            raise LetterRefusedError(("Valide d'abord cette lettre.",))
        sheet = letter_sheet(found.profile.identity, version, today_of(request))
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
        letter_refusal=reasons,
        letter_preview=preview,
        status_code=409,
        step=Step.LETTER,
    )


@dataclass(frozen=True)
class LetterPreview:
    """A page as it would be sent (the letter, the CV: decision D6, recette), as an image, and what makes it unfit."""

    png_base64: str
    problems: tuple[str, ...]


PREVIEW_DPI = 110


def _preview(pdf: bytes, problems: tuple[str, ...]) -> LetterPreview:
    buffer = io.BytesIO()
    rasterize(pdf, PREVIEW_DPI)[0].save(buffer, format="PNG", optimize=True)
    return LetterPreview(base64.b64encode(buffer.getvalue()).decode(), problems)


PREVIEW = "candidatures/page_preview.html"


def _preview_fragment(
    request: Request,
    preview: LetterPreview | None,
    *,
    document: str,
    pdf_url: str,
    refusal: tuple[str, ...] = (),
) -> Response:
    return render_fragment(
        request,
        PREVIEW,
        {
            "preview": preview,
            "refusal": refusal,
            "document": document,
            "pdf_url": pdf_url,
        },
    )


@router.get("/{application_id}/cv/apercu", response_class=HTMLResponse)
def cv_preview(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """The CV of the application as an image (decision D6, recette): seen at a glance beside the step, what spills over
    named under it. Nothing is kept."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    profile = replace(found.profile, cv=found.layout)
    pdf_url = f"/candidatures/{application_id}/cv.pdf?apercu=1"
    try:
        pdf, problems = profil_web.cv_drawing(request, account, profile, found.language)
        preview = _preview(pdf, problems)
    except CvRefusedError as error:
        return _preview_fragment(
            request, None, document="CV", pdf_url=pdf_url, refusal=error.reasons
        )
    except RenderError as error:
        return _preview_fragment(
            request, None, document="CV", pdf_url=pdf_url, refusal=(error.reason,)
        )
    return _preview_fragment(request, preview, document="CV", pdf_url=pdf_url)


@router.get("/{application_id}/lettre/apercu", response_class=HTMLResponse)
def letter_preview(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """The letter in force as an image (decision D6, recette), loaded beside the step. Nothing is kept."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    pdf_url = f"/candidatures/{application_id}/lettre.pdf?apercu=1"
    version = in_force(found.letters, found.language)
    if version is None:
        return _preview_fragment(
            request,
            None,
            document="lettre",
            pdf_url=pdf_url,
            refusal=("Valide d'abord cette lettre.",),
        )
    try:
        pdf, problems = draw_letter(
            letter_sheet(found.profile.identity, version, today_of(request))
        )
        preview = _preview(pdf, problems)
    except RenderError as error:
        return _preview_fragment(
            request, None, document="lettre", pdf_url=pdf_url, refusal=(error.reason,)
        )
    return _preview_fragment(request, preview, document="lettre", pdf_url=pdf_url)


@router.post("/{application_id}/lettre/apercu", response_class=HTMLResponse)
def preview_letter(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """« Aperçu de la lettre »: the letter as the form composes it (nothing stored), or the one in force."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language
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
                now_of(request),
            )
        else:
            version = letter.view.version
        if version is None:
            raise InvalidChangeError("Rien à montrer : compose d'abord ta lettre.")
        pdf, problems = draw_letter(
            letter_sheet(found.profile.identity, version, today_of(request))
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
        editing=editing,
        adaptation=adaptation_from_form(fields, generic)
        if editing and generic is not None
        else None,
        submitted=fields if editing else None,
        letter_error=error_text,
        letter_preview=preview,
        step=Step.LETTER,
    )


@router.post("/{application_id}/lettre/basculer", response_class=HTMLResponse)
def switch_version(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """The switch « Ta lettre · Gemini » of one paragraph (D6, Q3), rendered by the server (decision B4, criterion
    e): the form comes back as the user left it, that paragraph's text replaced. Nothing is stored."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    letter = _letter(request, account, found, found.language)
    generic = letter.view.generic
    fields = {key: value for key, value in form.multi_items() if isinstance(value, str)}
    if generic is None:
        return _dossier_page(request, account, application_id, step=Step.LETTER)
    return _dossier_page(
        request,
        account,
        application_id,
        step=Step.LETTER,
        editing=True,
        adaptation=adaptation_from_form(fields, generic),
        submitted=fields,
        letter_switch=read_switch(fields.get("basculer", "")),
    )


@router.get("/{application_id}/lettre.pdf")
def letter_pdf(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    apercu: bool = False,
) -> Response:
    rendered = _letter_pdf(request, account, application_id)
    if isinstance(rendered, Response):
        return rendered
    pdf, _, found = rendered
    language = found.language
    name = "_".join(found.profile.identity.full_name.split()) or "Lettre"
    disposition = "inline" if apercu else "attachment"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                disposition, f"Lettre_{name}_{language.upper()}.pdf"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.post("/{application_id}/lettre/verifier", response_class=HTMLResponse)
def check_letter(
    request: Request,
    account: CurrentAccount,
    application_id: int,
) -> Response:
    """« Vérifier cette lettre » (Q19): the three PDF readers on the letter in force."""
    rendered = _letter_pdf(request, account, application_id)
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
        letter_check=check_cv(pdf, [f for f in facts if f.text], document="la lettre"),
        step=Step.LETTER,
    )


@router.post("/{application_id}/message/proposer", response_class=HTMLResponse)
def propose_accompanying_message(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    consentement: Annotated[str, Form()] = "",
) -> Response:
    """« Proposer un message » (Q12): one call on the user's gesture, never automatic; nothing stored."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language

    def again(
        message_error: str | None = None,
        proposed: tuple[str, tuple[str, ...]] | None = None,
    ) -> Response:
        return _dossier_page(
            request,
            account,
            application_id,
            message_error=message_error,
            proposed_message=proposed,
            step=Step.SEND,
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
    texte: Annotated[str, Form()] = "",
    propose: Annotated[str, Form()] = "",
) -> Response:
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language
    letter = _letter(request, account, found, language)
    message = read_message(
        texte,
        propose,
        language=language,
        reference=letter.reference,
        sources=letter.sources,
    )
    try:
        with engine_of(request).begin() as connection:
            validate_message(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                message=message,
                now=now_of(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            message_error=str(error),
            proposed_message=(message.text, message.signals),
            step=Step.SEND,
        )
    return _to_step(application_id, Step.SEND)


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
                letter_sheet(found.profile.identity, version, today_of(request))
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
        sheet = letter_sheet(found.profile.identity, version, today_of(request))
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
) -> Response:
    """« Générer les PDF à envoyer » (Q2): each PDF stored once under its hash, then its revision; the earlier ones
    stay. A file written before a transaction that fails is left without row: it changes nothing."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language
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
        with engine_of(request).begin() as connection:
            record_revisions(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                revisions=revisions,
                now=now_of(request),
            )
    except (CvRefusedError, LetterRefusedError) as error:
        reason = " ".join(error.reasons)
    except RenderError as error:
        reason = error.reason
    except InvalidChangeError as error:
        reason = str(error)
    else:
        return _to_step(application_id, Step.SEND)
    return _dossier_page(
        request,
        account,
        application_id,
        send_error=f"Rien n'a été généré : {reason}",
        step=Step.SEND,
    )


@router.get("/{application_id}/documents/{revision_id}.pdf")
def revision_pdf(
    request: Request,
    account: CurrentAccount,
    application_id: int,
    revision_id: int,
    apercu: bool = False,
) -> Response:
    """A revision exactly as it was generated: its bytes are read back with their hash checked (Q2)."""
    with engine_of(request).begin() as connection:
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
                "Content-Disposition": content_disposition(
                    "inline" if apercu else "attachment", filename
                ),
                "Cache-Control": "no-store",
            },
        )
    return _dossier_page(
        request,
        account,
        application_id,
        send_error=f"Ce PDF ne peut pas être servi : {reason}",
        status_code=409,
        step=Step.SEND,
    )


@router.get("/{application_id}/envoi", response_class=HTMLResponse)
def sending_form(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """« J'ai envoyé ma candidature »: the form of the sending (Q3, Q5), the latest revisions checked."""
    return _dossier_page(
        request,
        account,
        application_id,
        confirming=True,
        step=Step.SEND,
    )


@router.post("/{application_id}/envoi", response_class=HTMLResponse)
def confirm(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """The sending confirmed: the stage « Envoyée » and what documents it, in one transaction."""
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language
    fields = {key: value for key, value in form.multi_items() if isinstance(value, str)}
    try:
        sending = read_sending(fields, _send(request, account, found, language))
        with engine_of(request).begin() as connection:
            confirm_sending(
                SqlApplicationStore(connection),
                account_id=account.id,
                application_id=application_id,
                sending=sending,
                now=now_of(request),
                today=today_of(request),
            )
    except InvalidChangeError as error:
        return _dossier_page(
            request,
            account,
            application_id,
            confirm_submitted=fields,
            confirm_error=str(error),
            step=Step.SEND,
        )
    return _to_step(application_id, Step.FOLLOW)


# DORMANT (decision D5, acceptance of 04/10): the two routes of the prefilling, closed by ``PREFILL_ENABLED``.


def _prefill_enabled(request: Request) -> bool:
    enabled: bool = request.app.state.prefill_enabled
    return enabled


@router.get("/{application_id}/preremplir", response_class=HTMLResponse)
def prefill_panel(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """DORMANT. What the workstation will put in the form, to confirm before it does (Q1, Q4)."""
    if not _prefill_enabled(request):
        return Response(status_code=404)
    return _dossier_page(
        request,
        account,
        application_id,
        prefilling=True,
        step=Step.SEND,
    )


CHANGED_SINCE_SHOWN = (
    "Les PDF à envoyer ont changé depuis l'affichage : relis la confirmation."
)


@router.post("/{application_id}/preremplir", response_class=HTMLResponse)
def prefill(
    request: Request, account: CurrentAccount, application_id: int, form: FormFields
) -> Response:
    """DORMANT. « Préremplir le formulaire » (Q1, Q4, Q6): the exact revisions shown, read back and checked, handed
    to the workstation; once it took the form, its report and the stage « Préremplie » are written. Nothing is
    written when it did not."""
    if not _prefill_enabled(request):
        return Response(status_code=404)
    found = _dossier(request, account, application_id)
    if found is None:
        return Response(status_code=404)
    language = found.language

    def again(error: str) -> Response:
        return _dossier_page(
            request,
            account,
            application_id,
            prefilling=True,
            prefill_error=error,
            step=Step.SEND,
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
        with engine_of(request).begin() as connection:
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
                now=now_of(request),
                today=today_of(request),
            )
    except FileError as error:
        return again(error.reason)
    except WorkstationUnavailableError as error:
        return again(error.reason)
    except InvalidChangeError as error:
        return again(str(error))
    return _to_step(application_id, Step.SEND)
