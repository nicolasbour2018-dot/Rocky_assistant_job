"""👤 Profil & kit screen and the guided onboarding.

The page is a list of sections; each section is read first and edited in place. HTMX replaces one section at
a time (``#section-<key>``); without HTMX, every route answers a whole page or a redirection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection, Engine
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile

from rocky.profil import letter_web, translation_web
from rocky.profil.cv import layout
from rocky.profil.cv.check import CvCheck, Fact, check_cv, expected_facts
from rocky.profil.cv.content import cv_content
from rocky.profil.cv.derived import (
    READABLE_FORMATS,
    TEMPLATE_FILE,
    derived_facts,
    derived_html,
    draw_derived,
    refuse_missing_variable_texts,
    render_derived,
    slots_of,
)
from rocky.profil.cv.importer import MAX_BYTES as IMPORT_MAX_BYTES
from rocky.profil.cv.importer import (
    ImportRefusedError,
    import_cv,
    import_language,
    read_proposals,
)
from rocky.profil.cv.photo import MAX_BYTES as PHOTO_MAX_BYTES
from rocky.profil.cv.photo import photo_suffix
from rocky.profil.cv.proposals import SECTIONS as PROPOSAL_SECTIONS
from rocky.profil.cv.proposals import apply as apply_proposals
from rocky.profil.cv.proposals import items as proposal_items
from rocky.profil.cv.rendering import (
    CvPdf,
    CvRefusedError,
    Photo,
    draw_neutral,
    neutral_headings,
    neutral_html,
    render_neutral,
)
from rocky.profil.cv.template import NEUTRAL_SLOTS, Slots
from rocky.profil.model import (
    CONTRACT_LABELS,
    EXPERIENCE_KIND_LABELS,
    LANGUAGE_LEVEL_LABELS,
    LANGUAGE_NAMES,
    REMOTE_LABELS,
    SKILL_CATEGORY_LABELS,
    SKILL_LEVEL_LABELS,
    TRACK_STATUS_LABELS,
    Contract,
    CvLayout,
    CvTemplateRecord,
    Experience,
    ExperienceKind,
    Language,
    LanguageLevel,
    Profile,
    Project,
    RemoteMode,
    Skill,
    SkillCategory,
    SkillLevel,
    StoredPhoto,
    Text,
    Track,
    TrackStatus,
)
from rocky.profil.rules import (
    ProfileInputError,
    make_experience,
    make_identity,
    make_language,
    make_preferences,
    make_project,
    make_skill,
    make_track,
    missing_for_ready,
    needs_onboarding,
    optional,
)
from rocky.profil.sql import SqlProfileStore
from rocky.profil.usecases import Clock, ProfileEditor
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.files import FileError, FileStore
from rocky.system.render import RenderError
from rocky.system.shell import (
    NAVIGATION,
    Action,
    Drawer,
    add_drawer,
    content_disposition,
    is_htmx,
    page,
    wants_fragment,
)

PROFILE_PATH = "/profil"
ONBOARDING_PATH = "/profil/demarrage"
NEW = "nouveau"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    # Sections holding texts in both languages show a FR / EN switch.
    bilingual: bool = False


SECTIONS = (
    Section("pistes", "Pistes"),
    Section("competences", "Compétences", bilingual=True),
    Section("langues", "Langues"),
    Section("parcours", "Expériences & formations", bilingual=True),
    Section("projets", "Projets", bilingual=True),
    Section("identite", "Identité & préférences", bilingual=True),
    Section("kit", "CV & kit de candidature", bilingual=True),
)
SECTION_KEYS = {section.key: section for section in SECTIONS}

MONTHS = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)

# Codes offered by the forms, in display order.
CHOICES = {
    "contracts": tuple(Contract),
    "remote_modes": tuple(RemoteMode),
    "levels": tuple(SkillLevel),
    "categories": tuple(SkillCategory),
    "language_levels": tuple(LanguageLevel),
    "kinds": tuple(ExperienceKind),
}

router = APIRouter(prefix=PROFILE_PATH)


def install(app: FastAPI) -> None:
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        profile_sections=SECTIONS,
        contract_labels=CONTRACT_LABELS,
        remote_labels=REMOTE_LABELS,
        track_status_labels=TRACK_STATUS_LABELS,
        skill_level_labels=SKILL_LEVEL_LABELS,
        skill_category_labels=SKILL_CATEGORY_LABELS,
        language_names=LANGUAGE_NAMES,
        language_level_labels=LANGUAGE_LEVEL_LABELS,
        experience_kind_labels=EXPERIENCE_KIND_LABELS,
        TrackStatus=TrackStatus,
        choices=CHOICES,
    )
    templates.env.filters["month"] = month
    templates.env.filters["html_id"] = translation_web.html_id
    # Before the profile's routes: ``/profil/{key}`` would take ``/profil/traduction`` or ``/profil/lettre``.
    app.include_router(translation_web.router)
    app.include_router(letter_web.router)
    app.include_router(router)
    add_drawer(app, "profile", _drawer)


def _drawer(request: Request, account: Account) -> Drawer:
    """What to do on 👤 Profil & kit (decision F1, Q12): an active track first, without it the watch finds nothing."""
    profile = profile_of(request, account)
    if any(track.status is TrackStatus.ACTIVE for track in profile.tracks):
        return Drawer(actions=(Action("Voir le CV et le kit", "/profil/kit"),))
    return Drawer(actions=(Action("Définir une piste", "/profil/pistes"),))


def onboarding_gate(
    main_paths: frozenset[str],
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Middleware: until the profile is ready or the onboarding put off, main pages lead to the onboarding.

    It must run after the session middleware (``request.state.account``): add it before that one.
    """

    async def gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        account: Account | None = getattr(request.state, "account", None)
        if (
            account is not None
            and request.method == "GET"
            and request.url.path in main_paths
            and await run_in_threadpool(_needs_onboarding, request, account)
        ):
            return RedirectResponse(ONBOARDING_PATH, status_code=303)
        return await call_next(request)

    return gate


MAIN_PATHS = frozenset(
    entry.path for entry in NAVIGATION if not entry.path.startswith(PROFILE_PATH)
)


def _needs_onboarding(request: Request, account: Account) -> bool:
    with _editor(request, account) as editor:
        return editor.needs_onboarding()


def month(day: date | None) -> str:
    if day is None:
        return "aujourd'hui"
    return f"{MONTHS[day.month - 1]} {day.year}"


# Transactions and responses


@contextmanager
def _editor(
    request: Request, account: Account, *, writes: bool = False
) -> Iterator[ProfileEditor]:
    """One use case, one transaction: committed on exit, rolled back on error.

    After a committed write, the other modules are told (``profile_changed``: the rescoring of the offers, C6 Q5).
    """
    engine: Engine = request.app.state.engine
    clock: Clock = request.app.state.auth.clock
    with engine.begin() as connection:
        yield ProfileEditor(
            SqlProfileStore(connection),
            clock=clock,
            account_id=account.id,
            email=account.email,
        )
    if writes:
        changed: Callable[[int], None] | None = getattr(
            request.app.state, "profile_changed", None
        )
        if changed is not None:
            changed(account.id)


def stored_profile(connection: Connection, account_id: int) -> Profile | None:
    """The account's profile for the other modules outside a request (the watch); None when it has none yet.

    Read only: unlike ``profile_of``, a missing profile is not created.
    """
    store = SqlProfileStore(connection)
    profile_id = store.find_profile_id(account_id)
    return None if profile_id is None else store.load(profile_id)


def profile_of(request: Request, account: Account) -> Profile:
    """The account's profile, for the screens of the other modules (read through the profile use case)."""
    with _editor(request, account) as editor:
        return editor.profile()


def _error_status(request: Request) -> int:
    # HTMX does not swap 4xx answers: a form error it asked for comes back as 200.
    return 200 if is_htmx(request) else 400


async def _form(request: Request) -> AsyncIterator[FormData]:
    """The submitted form; its uploaded files are closed once the answer is sent."""
    form = await request.form()
    try:
        yield form
    finally:
        await form.close()


Form = Annotated[FormData, Depends(_form)]


class Values:
    """Values shown in a form: what was just submitted (after an error), else the stored ones."""

    def __init__(
        self, stored: Mapping[str, Any], submitted: FormData | None = None
    ) -> None:
        self._stored = stored
        self._submitted = submitted

    def get(self, name: str) -> str:
        if self._submitted is not None:
            value = self._submitted.get(name)
            return value if isinstance(value, str) else ""
        stored = self._stored.get(name)
        if stored is None:
            return ""
        if isinstance(stored, tuple | list):
            return "\n".join(str(item) for item in stored)
        return str(stored)

    def has(self, name: str, value: str) -> bool:
        """For check boxes and multiple choices."""
        if self._submitted is not None:
            return value in self._submitted.getlist(name)
        stored = self._stored.get(name)
        if isinstance(stored, tuple | list | set | frozenset):
            return value in {str(item) for item in stored}
        return str(stored) == value if stored is not None else False


@dataclass
class SectionState:
    """How one section is shown: in which language, and what is being edited."""

    language: str = "fr"
    editing: str | None = None
    values: Values = field(default_factory=lambda: Values({}))
    error: str | None = None
    # Result of « Vérifier mon CV » (section « kit »), shown once, never stored.
    check: CvCheck | None = None


def _render(
    request: Request,
    profile: Profile,
    *,
    key: str | None = None,
    state: SectionState | None = None,
    status_code: int = 200,
    message: str | None = None,
) -> HTMLResponse:
    """One section (explicit HTMX request) or the whole page with that section in ``state``."""
    states = {section.key: SectionState() for section in SECTIONS}
    if key is not None and state is not None:
        states[key] = state
    context = {
        "profile": profile,
        "states": states,
        "skills_by_id": {skill.id: skill for skill in profile.skills},
        "missing": missing_for_ready(profile),
        "cv_templates": _templates_of(request, profile),
        "cv_missing_en": cv_content(
            profile, "en", request.app.state.auth.clock().date()
        ).missing,
        "onboarding_open": needs_onboarding(profile.onboarding),
        "message": message,
    }
    if key is not None and wants_fragment(request):
        return page(
            request,
            "profil/section.html",
            active="profile",
            status_code=status_code,
            context={**context, "section": SECTION_KEYS[key]},
        )
    return page(
        request,
        "profil/page.html",
        active="profile",
        status_code=status_code,
        context=context,
    )


def _saved(request: Request, profile: Profile, key: str) -> Response:
    if wants_fragment(request):
        return _render(request, profile, key=key, state=SectionState())
    return RedirectResponse(f"{PROFILE_PATH}#section-{key}", status_code=303)


def _refused(
    request: Request,
    profile: Profile,
    key: str,
    editing: str,
    form: FormData,
    error: ProfileInputError,
) -> Response:
    state = SectionState(editing=editing, values=Values({}, form), error=str(error))
    return _render(
        request, profile, key=key, state=state, status_code=_error_status(request)
    )


# Stored values shown in the edit forms


def _track_values(track: Track | None) -> dict[str, Any]:
    if track is None:
        return {}
    content = track.content
    return {
        "name": content.name,
        "titles": content.titles,
        "keywords": content.keywords,
        "excluded_keywords": content.excluded_keywords,
        "locations": content.locations,
    }


def _skill_values(skill: Skill | None) -> dict[str, Any]:
    if skill is None:
        return {"category": SkillCategory.TECHNICAL.value}
    content = skill.content
    return {
        "label_fr": content.label.fr,
        "label_en": content.label.en,
        "aliases": content.aliases,
        "category": content.category.value,
        "level": content.level.value if content.level else None,
        "is_key": "1" if content.is_key else None,
    }


def _language_values(language: Language | None) -> dict[str, Any]:
    if language is None:
        return {}
    return {"code": language.content.code, "level": language.content.level.value}


def _experience_values(experience: Experience | None) -> dict[str, Any]:
    if experience is None:
        return {"kind": ExperienceKind.JOB.value}
    content = experience.content
    return {
        "kind": content.kind.value,
        "title_fr": content.title.fr,
        "title_en": content.title.en,
        "organisation": content.organisation,
        "place": content.place,
        "start": content.start.strftime("%Y-%m"),
        "end": content.end.strftime("%Y-%m") if content.end else None,
        "bullets_fr": content.bullets_fr,
        "bullets_en": content.bullets_en,
        "skills": content.skill_ids,
    }


def _project_values(project: Project | None) -> dict[str, Any]:
    if project is None:
        return {}
    content = project.content
    values: dict[str, Any] = {
        "stack": content.stack,
        "stack_en": content.stack_en or (),
        "url": content.url,
        "skills": content.skill_ids,
    }
    for name in ("name", "problem", "work", "results"):
        text = getattr(content, name)
        values[f"{name}_fr"], values[f"{name}_en"] = text.fr, text.en
    return values


def _identity_values(profile: Profile) -> dict[str, Any]:
    identity = profile.identity
    return {
        "full_name": identity.full_name,
        "contact_email": identity.contact_email,
        "phone": identity.phone,
        "city": identity.city,
        "postal_code": identity.postal_code,
        "links": [f"{link.label} | {link.url}" for link in identity.links],
        "headline_fr": identity.headline.fr,
        "headline_en": identity.headline.en,
        "title_fr": identity.title.fr,
        "title_en": identity.title.en,
        "birth_date": identity.birth_date.isoformat() if identity.birth_date else None,
        "show_age": "1" if identity.show_age else None,
    }


def _preferences_values(profile: Profile) -> dict[str, Any]:
    preferences = profile.preferences
    return {
        "contracts": [c.value for c in preferences.contracts],
        "remote_modes": [m.value for m in preferences.remote_modes],
        "min_salary_eur": preferences.min_salary_eur,
        "min_daily_rate_eur": preferences.min_daily_rate_eur,
    }


def _stored_values(profile: Profile, key: str, editing: str) -> dict[str, Any] | None:
    """Values of the item being edited; None when it does not exist in this profile."""
    item_id = int(editing) if editing.isascii() and editing.isdigit() else None
    if editing != NEW and item_id is None and key not in ("identite", "kit"):
        return None
    finders: dict[str, Callable[[], dict[str, Any] | None]] = {
        "pistes": lambda: _found(profile.tracks, item_id, _track_values),
        "competences": lambda: _found(profile.skills, item_id, _skill_values),
        "langues": lambda: _found(profile.languages, item_id, _language_values),
        "parcours": lambda: _found(profile.experiences, item_id, _experience_values),
        "projets": lambda: _found(profile.projects, item_id, _project_values),
        "identite": lambda: (
            _identity_values(profile)
            if editing == "identite"
            else _preferences_values(profile)
            if editing == "preferences"
            else None
        ),
        "kit": lambda: _kit_values(profile, editing),
    }
    finder = finders.get(key)
    return None if finder is None else finder()


def _kit_values(profile: Profile, editing: str) -> dict[str, Any] | None:
    """Edited in place: ``groupe-<index>``, ``loisir-<index>``; added: ``nouveau-groupe``, ``nouveau-loisir``."""
    kind, _, index = editing.partition("-")
    if editing in ("nouveau-groupe", "nouveau-loisir"):
        return {}
    items: tuple[Any, ...] = (
        profile.cv.groups
        if kind == "groupe"
        else profile.cv.hobbies
        if kind == "loisir"
        else ()
    )
    if not (index.isascii() and index.isdigit()) or int(index) >= len(items):
        return None
    text = items[int(index)].name if kind == "groupe" else items[int(index)].label
    return {"name_fr": text.fr, "name_en": text.en}


def _found[T: (Track, Skill, Language, Experience, Project)](
    items: tuple[T, ...],
    item_id: int | None,
    values: Callable[[T | None], dict[str, Any]],
) -> dict[str, Any] | None:
    if item_id is None:
        return values(None)
    item = next((i for i in items if i.id == item_id), None)
    return None if item is None else values(item)


# Page and sections


@router.get("", response_class=HTMLResponse)
def profile_page(request: Request, account: CurrentAccount) -> HTMLResponse:
    return _render(request, profile_of(request, account))


@router.get("/demarrage", response_class=HTMLResponse)
def onboarding(
    request: Request, account: CurrentAccount, etape: int = 1
) -> HTMLResponse:
    profile = profile_of(request, account)
    return _onboarding_page(request, profile, max(1, min(etape, 3)))


def _onboarding_page(
    request: Request,
    profile: Profile,
    step: int,
    *,
    form: FormData | None = None,
    error: str | None = None,
    message: str | None = None,
) -> HTMLResponse:
    stored = _identity_values(profile) if step == 1 else {}
    response = page(
        request,
        "profil/onboarding.html",
        active="profile",
        status_code=_error_status(request) if error else 200,
        context={
            "profile": profile,
            "step": step,
            "values": Values(stored, form),
            "error": error,
            "message": message,
        },
    )
    if request.method == "POST":
        # A boosted form would leave the POST address in the bar, which a reload cannot show.
        response.headers["HX-Replace-Url"] = f"{ONBOARDING_PATH}?etape={step}"
    return response


@router.post("/demarrage/identite", response_class=HTMLResponse)
def onboarding_identity(
    request: Request, account: CurrentAccount, form: Form
) -> Response:
    """Step 1 asks for four fields; the other identity fields are kept as they are."""
    try:
        with _editor(request, account, writes=True) as editor:
            current = editor.profile().identity
            editor.save_identity(
                make_identity(
                    full_name=_text(form, "full_name"),
                    contact_email=_text(form, "contact_email"),
                    city=_text(form, "city"),
                    postal_code=_text(form, "postal_code"),
                    phone=current.phone,
                    links=[f"{link.label} | {link.url}" for link in current.links],
                    headline_fr=current.headline.fr,
                    headline_en=current.headline.en,
                    title_fr=current.title.fr,
                    title_en=current.title.en,
                    birth_date=current.birth_date,
                    show_age=current.show_age,
                )
            )
    except ProfileInputError as error:
        profile = profile_of(request, account)
        return _onboarding_page(request, profile, 1, form=form, error=str(error))
    return RedirectResponse(f"{ONBOARDING_PATH}?etape=2", status_code=303)


@router.post("/demarrage/competences", response_class=HTMLResponse)
def onboarding_skills(
    request: Request, account: CurrentAccount, form: Form
) -> Response:
    with _editor(request, account, writes=True) as editor:
        result = editor.add_skills(
            {
                category: _text(form, category.value).splitlines()
                for category in SkillCategory
            }
        )
        profile = editor.profile()
    if result.already_there:
        return _onboarding_page(
            request,
            profile,
            2,
            message="Déjà dans ton profil, non ajoutées : "
            + ", ".join(result.already_there)
            + ".",
        )
    return RedirectResponse(f"{ONBOARDING_PATH}?etape=3", status_code=303)


@router.post("/demarrage/piste", response_class=HTMLResponse)
def onboarding_track(request: Request, account: CurrentAccount, form: Form) -> Response:
    try:
        track = _track_from(form)
        if not track.titles or not track.locations:
            raise ProfileInputError(
                "Indique au moins un intitulé et un lieu : c'est ce que la veille cherchera."
            )
        with _editor(request, account, writes=True) as editor:
            editor.add_track(track)
    except ProfileInputError as error:
        profile = profile_of(request, account)
        return _onboarding_page(request, profile, 3, form=form, error=str(error))
    return RedirectResponse(PROFILE_PATH, status_code=303)


@router.post("/demarrage/plus-tard")
def defer_onboarding(request: Request, account: CurrentAccount) -> Response:
    with _editor(request, account, writes=True) as editor:
        editor.defer_onboarding()
    return RedirectResponse(PROFILE_PATH, status_code=303)


@router.get("/{key}", response_class=HTMLResponse)
def section(
    request: Request,
    account: CurrentAccount,
    key: str,
    langue: str = "fr",
    modifier: str | None = None,
) -> Response:
    if key not in SECTION_KEYS:
        return Response(status_code=404)
    profile = profile_of(request, account)
    state = SectionState(language="en" if langue == "en" else "fr")
    if modifier is not None:
        stored = _stored_values(profile, key, modifier)
        if stored is None:
            return Response(status_code=404)
        state.editing, state.values = modifier, Values(stored)
    return _render(request, profile, key=key, state=state)


# Writes: one form, one use case, one transaction


def _text(form: FormData, name: str) -> str:
    value = form.get(name)
    return value if isinstance(value, str) else ""


def _ids(form: FormData, name: str) -> list[int]:
    return [
        int(v)
        for v in form.getlist(name)
        if isinstance(v, str) and v.isascii() and v.isdigit()
    ]


def _track_from(form: FormData) -> Any:
    return make_track(
        name=_text(form, "name"),
        titles=_text(form, "titles"),
        keywords=_text(form, "keywords"),
        excluded_keywords=_text(form, "excluded_keywords"),
        locations=_text(form, "locations"),
    )


type Change = Callable[[ProfileEditor, FormData], bool | int]


def _write(
    request: Request,
    account: Account,
    form: FormData,
    key: str,
    editing: str,
    change: Change,
) -> Response:
    try:
        with _editor(request, account, writes=True) as editor:
            if change(editor, form) is False:
                return Response(status_code=404)
            profile = editor.profile()
    except ProfileInputError as error:
        return _refused(
            request, profile_of(request, account), key, editing, form, error
        )
    return _saved(request, profile, key)


@router.post("/pistes", response_class=HTMLResponse)
def add_track(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(
        request, account, form, "pistes", NEW, lambda e, f: e.add_track(_track_from(f))
    )


@router.post("/pistes/{track_id}", response_class=HTMLResponse)
def update_track(
    request: Request, account: CurrentAccount, form: Form, track_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "pistes",
        str(track_id),
        lambda e, f: e.update_track(track_id, _track_from(f)),
    )


TRACK_ACTIONS: dict[str, Callable[[ProfileEditor, int], bool]] = {
    "pause": ProfileEditor.pause_track,
    "reprendre": ProfileEditor.resume_track,
    "archiver": ProfileEditor.archive_track,
    "supprimer": ProfileEditor.delete_track,
}


@router.post("/pistes/{track_id}/{action}", response_class=HTMLResponse)
def track_action(
    request: Request, account: CurrentAccount, form: Form, track_id: int, action: str
) -> Response:
    act = TRACK_ACTIONS.get(action)
    if act is None:
        return Response(status_code=404)
    return _write(
        request, account, form, "pistes", str(track_id), lambda e, _: act(e, track_id)
    )


def _skill_from(form: FormData) -> Any:
    return make_skill(
        label_fr=_text(form, "label_fr"),
        label_en=_text(form, "label_en"),
        aliases=_text(form, "aliases"),
        category=_text(form, "category"),
        level=_text(form, "level") or None,
        is_key=bool(_text(form, "is_key")),
    )


@router.post("/competences", response_class=HTMLResponse)
def add_skill(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(
        request,
        account,
        form,
        "competences",
        NEW,
        lambda e, f: e.add_skill(_skill_from(f)),
    )


@router.post("/competences/{skill_id}", response_class=HTMLResponse)
def update_skill(
    request: Request, account: CurrentAccount, form: Form, skill_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "competences",
        str(skill_id),
        lambda e, f: e.update_skill(skill_id, _skill_from(f)),
    )


@router.post("/competences/{skill_id}/supprimer", response_class=HTMLResponse)
def delete_skill(
    request: Request, account: CurrentAccount, form: Form, skill_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "competences",
        str(skill_id),
        lambda e, _: e.delete_skill(skill_id),
    )


def _language_from(form: FormData) -> Any:
    return make_language(code_value=_text(form, "code"), level=_text(form, "level"))


@router.post("/langues", response_class=HTMLResponse)
def add_language(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(
        request,
        account,
        form,
        "langues",
        NEW,
        lambda e, f: e.add_language(_language_from(f)),
    )


@router.post("/langues/{language_id}", response_class=HTMLResponse)
def update_language(
    request: Request, account: CurrentAccount, form: Form, language_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "langues",
        str(language_id),
        lambda e, f: e.update_language(language_id, _language_from(f)),
    )


@router.post("/langues/{language_id}/supprimer", response_class=HTMLResponse)
def delete_language(
    request: Request, account: CurrentAccount, form: Form, language_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "langues",
        str(language_id),
        lambda e, _: e.delete_language(language_id),
    )


def _experience_from(form: FormData) -> Any:
    return make_experience(
        kind=_text(form, "kind"),
        title_fr=_text(form, "title_fr"),
        title_en=_text(form, "title_en"),
        organisation=_text(form, "organisation"),
        place=_text(form, "place"),
        start=_text(form, "start"),
        end=_text(form, "end"),
        bullets_fr=_text(form, "bullets_fr"),
        bullets_en=_text(form, "bullets_en"),
        skill_ids=_ids(form, "skills"),
    )


@router.post("/parcours", response_class=HTMLResponse)
def add_experience(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(
        request,
        account,
        form,
        "parcours",
        NEW,
        lambda e, f: e.add_experience(_experience_from(f)),
    )


@router.post("/parcours/{experience_id}", response_class=HTMLResponse)
def update_experience(
    request: Request, account: CurrentAccount, form: Form, experience_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "parcours",
        str(experience_id),
        lambda e, f: e.update_experience(experience_id, _experience_from(f)),
    )


@router.post("/parcours/{experience_id}/supprimer", response_class=HTMLResponse)
def delete_experience(
    request: Request, account: CurrentAccount, form: Form, experience_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "parcours",
        str(experience_id),
        lambda e, _: e.delete_experience(experience_id),
    )


def _project_from(form: FormData) -> Any:
    return make_project(
        name_fr=_text(form, "name_fr"),
        name_en=_text(form, "name_en"),
        problem_fr=_text(form, "problem_fr"),
        problem_en=_text(form, "problem_en"),
        work_fr=_text(form, "work_fr"),
        work_en=_text(form, "work_en"),
        results_fr=_text(form, "results_fr"),
        results_en=_text(form, "results_en"),
        stack=_text(form, "stack"),
        url=_text(form, "url"),
        skill_ids=_ids(form, "skills"),
        stack_en=_text(form, "stack_en"),
    )


@router.post("/projets", response_class=HTMLResponse)
def add_project(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(
        request,
        account,
        form,
        "projets",
        NEW,
        lambda e, f: e.add_project(_project_from(f)),
    )


@router.post("/projets/{project_id}", response_class=HTMLResponse)
def update_project(
    request: Request, account: CurrentAccount, form: Form, project_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "projets",
        str(project_id),
        lambda e, f: e.update_project(project_id, _project_from(f)),
    )


@router.post("/projets/{project_id}/supprimer", response_class=HTMLResponse)
def delete_project(
    request: Request, account: CurrentAccount, form: Form, project_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "projets",
        str(project_id),
        lambda e, _: e.delete_project(project_id),
    )


def _save_identity(editor: ProfileEditor, form: FormData) -> bool:
    editor.save_identity(
        make_identity(
            **{
                name: _text(form, name)
                for name in (
                    "full_name",
                    "contact_email",
                    "phone",
                    "city",
                    "postal_code",
                    "links",
                    "headline_fr",
                    "headline_en",
                    "title_fr",
                    "title_en",
                    "birth_date",
                )
            },
            show_age=bool(_text(form, "show_age")),
        )
    )
    return True


def _save_preferences(editor: ProfileEditor, form: FormData) -> bool:
    editor.save_preferences(
        make_preferences(
            contracts=[v for v in form.getlist("contracts") if isinstance(v, str)],
            remote_modes=[
                v for v in form.getlist("remote_modes") if isinstance(v, str)
            ],
            min_salary_eur=_text(form, "min_salary_eur"),
            min_daily_rate_eur=_text(form, "min_daily_rate_eur"),
        )
    )
    return True


@router.post("/identite", response_class=HTMLResponse)
def save_identity(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(request, account, form, "identite", "identite", _save_identity)


@router.post("/preferences", response_class=HTMLResponse)
def save_preferences(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(request, account, form, "identite", "preferences", _save_preferences)


# Master CV (section « kit », decision D2, Q7, Q9, Q10)


def _files(request: Request) -> FileStore:
    root = request.app.state.settings.storage_root
    if root is None:
        raise ProfileInputError(
            "Le stockage des fichiers n'est pas configuré (ROCKY_STORAGE_ROOT)."
        )
    return FileStore(root)


@router.post("/photo", response_class=HTMLResponse)
def upload_photo(request: Request, account: CurrentAccount, form: Form) -> Response:
    def change(editor: ProfileEditor, form: FormData) -> bool:
        upload = form.get("photo")
        content = (
            upload.file.read(PHOTO_MAX_BYTES + 1)
            if isinstance(upload, UploadFile)
            else b""
        )
        suffix = photo_suffix(content)
        # Stored before the commit: an unused file of its own hash harms nothing.
        stored = _files(request).put_file(account.id, "photos", content, suffix)
        editor.save_photo(StoredPhoto(stored.path, stored.sha256))
        return True

    return _write(request, account, form, "kit", "photo", change)


@router.post("/photo/retirer", response_class=HTMLResponse)
def remove_photo(request: Request, account: CurrentAccount, form: Form) -> Response:
    return _write(
        request, account, form, "kit", "photo", lambda e, _: _saved_photo(e, None)
    )


def _saved_photo(editor: ProfileEditor, photo: StoredPhoto | None) -> bool:
    editor.save_photo(photo)
    return True


@router.get("/cv/photo")
def photo(request: Request, account: CurrentAccount) -> Response:
    stored = profile_of(request, account).photo
    if stored is None:
        return Response(status_code=404)
    try:
        content = _files(request).read_file(stored.path, stored.sha256)
    except (FileError, ProfileInputError):
        return Response(status_code=404)
    kind = mimetypes.guess_type(stored.path)[0] or "application/octet-stream"
    return Response(content, media_type=kind, headers={"Cache-Control": "private"})


@router.post("/cv/verifier", response_class=HTMLResponse)
def check_my_cv(request: Request, account: CurrentAccount, form: Form) -> Response:
    """Render the CV, then read it back with the three PDF readers (decision D2, Q12).

    Declared before ``/cv/{gesture}``, which would take its address otherwise.
    """
    language = "en" if _text(form, "langue") == "en" else "fr"
    profile = profile_of(request, account)
    rendered = _cv_document(request, account, profile, language)
    if isinstance(rendered, Response):
        return rendered
    document, facts = rendered
    state = SectionState(language=language)
    state.check = check_cv(document.pdf, facts)
    return _render(request, profile, key="kit", state=state)


@router.post("/cv/{gesture}", response_class=HTMLResponse)
def cv_gesture(
    request: Request, account: CurrentAccount, form: Form, gesture: str
) -> Response:
    if gesture not in CV_GESTURES:
        return Response(status_code=404)

    def change(editor: ProfileEditor, form: FormData) -> bool:
        profile = editor.profile()
        editor.save_cv_layout(
            CV_GESTURES[gesture](profile, form), _slots(request, editor)
        )
        return True

    return _write(request, account, form, "kit", _cv_editing(gesture, form), change)


def _cv_editing(gesture: str, form: FormData) -> str:
    """The form to show again when a gesture is refused."""
    if gesture == "groupe-ajouter":
        return "nouveau-groupe"
    if gesture == "loisir-ajouter":
        return "nouveau-loisir"
    if gesture in ("groupe-renommer", "loisir-modifier"):
        return f"{gesture.partition('-')[0]}-{_text(form, 'index')}"
    return ""


def _int(form: FormData, name: str) -> int:
    value = _text(form, name)
    digits = value.removeprefix("-")
    return int(value) if digits.isascii() and digits.isdigit() else -1


def _name(form: FormData) -> Text:
    return Text(
        optional(_text(form, "name_fr")) or "", optional(_text(form, "name_en"))
    )


def _placement(profile: Profile, form: FormData) -> CvLayout:
    target = _text(form, "group")
    group_index = None if target in ("", "retirer") else max(_int(form, "group"), 0)
    return layout.place_skill(profile.cv, profile, _int(form, "id"), group_index)


CV_GESTURES: dict[str, Callable[[Profile, FormData], CvLayout]] = {
    "groupe-ajouter": lambda p, f: layout.add_group(p.cv, _name(f)),
    "groupe-renommer": lambda p, f: layout.rename_group(
        p.cv, _int(f, "index"), _name(f)
    ),
    "groupe-retirer": lambda p, f: layout.remove_group(p.cv, _int(f, "index")),
    "groupe-monter": lambda p, f: layout.move_group(p.cv, _int(f, "index"), -1),
    "groupe-descendre": lambda p, f: layout.move_group(p.cv, _int(f, "index"), 1),
    "competence-placer": _placement,
    "competence-monter": lambda p, f: layout.move_skill(p.cv, _int(f, "id"), -1),
    "competence-descendre": lambda p, f: layout.move_skill(p.cv, _int(f, "id"), 1),
    "projet-basculer": lambda p, f: layout.toggle_project(p.cv, _int(f, "id")),
    "projet-monter": lambda p, f: layout.move_project(p.cv, _int(f, "id"), -1),
    "projet-descendre": lambda p, f: layout.move_project(p.cv, _int(f, "id"), 1),
    "loisir-ajouter": lambda p, f: layout.add_hobby(p.cv, _name(f)),
    "loisir-modifier": lambda p, f: layout.update_hobby(
        p.cv, _int(f, "index"), _name(f)
    ),
    "loisir-basculer": lambda p, f: layout.toggle_hobby(p.cv, _int(f, "index")),
    "loisir-retirer": lambda p, f: layout.remove_hobby(p.cv, _int(f, "index")),
    "loisir-monter": lambda p, f: layout.move_hobby(p.cv, _int(f, "index"), -1),
    "loisir-descendre": lambda p, f: layout.move_hobby(p.cv, _int(f, "index"), 1),
}


# The CV as a PDF (decision D2, Q6, Q11): delivered whole or refused with its reasons, never cut.


@router.get("/cv/pdf")
def cv_pdf(
    request: Request, account: CurrentAccount, langue: str = "fr", apercu: bool = False
) -> Response:
    language = "en" if langue == "en" else "fr"
    profile = profile_of(request, account)
    rendered = _cv_document(request, account, profile, language)
    if isinstance(rendered, Response):
        return rendered
    document = rendered[0]
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


def cv_document(
    request: Request, account: Account, profile: Profile, language: str
) -> tuple[CvPdf, tuple[Fact, ...]]:
    """The rendered CV of ``profile`` and what PDF readers must find in it; raises ``CvRefusedError`` (or
    ``RenderError``) with its reasons. For the other modules too: an application renders its targeted CV by giving
    the profile its own layout (decision D3, Q1).

    The account's active template in that language renders it (Q16, Q33); without one, the neutral template does.
    """
    clock: Clock = request.app.state.auth.clock
    content = cv_content(profile, language, clock().date())
    active = _active_template(request, account, language)
    if active is None:
        document = render_neutral(content, _photo_of(request, profile))
        return document, expected_facts(content, neutral_headings(content))
    _, files = active
    return render_derived(files, content), derived_facts(files, content)


def cv_drawing(
    request: Request, account: Account, profile: Profile, language: str
) -> tuple[bytes, tuple[str, ...]]:
    """The CV of ``profile`` drawn whatever its overflows, and its problems: what a preview shows (decision D6,
    recette). Raises ``CvRefusedError`` when it cannot be drawn at all (English missing, template unreadable)."""
    clock: Clock = request.app.state.auth.clock
    content = cv_content(profile, language, clock().date())
    active = _active_template(request, account, language)
    if active is None:
        rendered, _, reasons = draw_neutral(content, _photo_of(request, profile))
        return rendered.pdf, reasons
    _, files = active
    refuse_missing_variable_texts(content)
    rendered, _, reasons = draw_derived(files, content)
    return rendered.pdf, reasons


def cv_fingerprint(
    request: Request, account: Account, profile: Profile, language: str
) -> str | None:
    """What the CV of ``profile`` is made from, without rendering it (decision D5): the HTML it renders and the
    template and photo it is drawn with. The bytes of a PDF change with each render (creation date): this tells
    whether a CV kept earlier is still the one Rocky would make. None: the CV cannot be made (its reasons are given
    by ``cv_document``)."""
    clock: Clock = request.app.state.auth.clock
    content = cv_content(profile, language, clock().date())
    try:
        active = _active_template(request, account, language)
    except CvRefusedError:
        return None
    if active is None:
        photo = profile.photo
        suffix = photo.path.rsplit(".", 1)[-1] if photo else "jpg"
        html = neutral_html(content, with_photo=photo is not None, suffix=suffix)
        parts: tuple[str, ...] = ("neutre", photo.sha256 if photo else "", html)
    else:
        record, files = active
        template = json.loads(files[TEMPLATE_FILE])
        if template.get("format") not in READABLE_FORMATS:
            return None
        parts = (record.sha256, derived_html(template, content))
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def cv_slots(request: Request, account: Account) -> Slots:
    """The room of the account's active French template, for the other modules (an application's selection)."""
    with _editor(request, account) as editor:
        return _slots(request, editor)


def _cv_document(
    request: Request, account: Account, profile: Profile, language: str
) -> tuple[CvPdf, tuple[Fact, ...]] | Response:
    """The rendered CV and its facts; or the « kit » section telling why it is refused."""
    try:
        return cv_document(request, account, profile, language)
    except (CvRefusedError, RenderError) as error:
        reasons = (
            error.reasons if isinstance(error, CvRefusedError) else (error.reason,)
        )
        state = SectionState(language=language, error=" ".join(reasons))
        return _render(
            request, profile, key="kit", state=state, status_code=_error_status(request)
        )


def _active_template(
    request: Request, account: Account, language: str
) -> tuple[CvTemplateRecord, Mapping[str, bytes]] | None:
    with _editor(request, account) as editor:
        record = editor.active_cv_template(language)
    if record is None:
        return None
    return record, _template_files(request, record)


def _template_files(request: Request, record: CvTemplateRecord) -> Mapping[str, bytes]:
    """The files of a stored template; an unreadable one refuses the CV with its reason."""
    try:
        return _files(request).read_bundle(record.path, record.sha256)
    except (FileError, ProfileInputError) as error:
        reason = error.reason if isinstance(error, FileError) else str(error)
        raise CvRefusedError(
            (f"Ton gabarit de CV est illisible : {reason}",)
        ) from error


def _slots(request: Request, editor: ProfileEditor) -> Slots:
    """The room of the active French template (Q26; the master CV is written in French); the neutral one's
    without one."""
    record = editor.active_cv_template("fr")
    if record is None:
        return NEUTRAL_SLOTS
    files = _template_files(request, record)
    return slots_of(json.loads(files[TEMPLATE_FILE]))


def _photo_of(request: Request, profile: Profile) -> Photo | None:
    if profile.photo is None:
        return None
    try:
        content = _files(request).read_file(profile.photo.path, profile.photo.sha256)
    except FileError as error:
        raise CvRefusedError((f"La photo est illisible : {error.reason}",)) from error
    except ProfileInputError as error:
        raise CvRefusedError((str(error),)) from error
    return Photo(content, profile.photo.path.rsplit(".", 1)[-1])


# Import of a CV PDF, and the account's templates (decision D2, Q2, Q14, Q16, Q20, Q24)


def _templates_of(request: Request, profile: Profile) -> tuple[CvTemplateRecord, ...]:
    engine: Engine = request.app.state.engine
    with engine.connect() as connection:
        return SqlProfileStore(connection).cv_templates(profile.id)


@router.post("/import-cv", response_class=HTMLResponse)
def import_my_cv(request: Request, account: CurrentAccount, form: Form) -> Response:
    """Read the CV (texts to the language model, never the file), derive a template, show what it proposes."""
    profile = profile_of(request, account)
    upload = form.get("fichier")
    content = (
        upload.file.read(IMPORT_MAX_BYTES + 1)
        if isinstance(upload, UploadFile)
        else b""
    )
    if not _text(form, "consentement"):
        return _kit_refused(
            request,
            profile,
            "Coche l'accord d'envoi du texte de ton CV pour l'importer.",
        )
    if not content:
        return _kit_refused(request, profile, "Choisis le PDF de ton CV.")
    clock: Clock = request.app.state.auth.clock
    try:
        imported = import_cv(
            content,
            model=request.app.state.llm_model,
            files=_files(request),
            account_id=account.id,
            today=clock().date(),
            language="en" if _text(form, "langue") == "en" else "fr",
        )
    except ImportRefusedError as error:
        return _kit_refused(request, profile, error.reason)
    except ProfileInputError as error:
        return _kit_refused(request, profile, str(error))
    template_id = None
    if imported.template is not None:
        with _editor(request, account, writes=True) as editor:
            template_id = editor.record_cv_template(
                imported.template.path,
                imported.template.sha256,
                imported.template_name,
                imported.language,
            )
    return _import_page(
        request,
        account,
        imported.proposals.sha256,
        template_id=template_id,
        refusal=imported.template_refusal,
        warnings=imported.warnings,
        preview=imported.preview,
    )


def _kit_refused(request: Request, profile: Profile, reason: str) -> Response:
    state = SectionState(error=reason)
    return _render(
        request, profile, key="kit", state=state, status_code=_error_status(request)
    )


@router.get("/import-cv/{sha256}", response_class=HTMLResponse)
def import_page(request: Request, account: CurrentAccount, sha256: str) -> Response:
    return _import_page(request, account, sha256)


def _import_page(
    request: Request,
    account: Account,
    sha256: str,
    *,
    template_id: int | None = None,
    refusal: str | None = None,
    warnings: tuple[str, ...] = (),
    preview: tuple[bytes, bytes] | None = None,
    message: str | None = None,
    error: str | None = None,
) -> Response:
    try:
        proposals, photo = read_proposals(_files(request), account.id, sha256)
        language = import_language(_files(request), account.id, sha256)
    except (FileError, ImportRefusedError, ProfileInputError):
        return Response(status_code=404)
    profile = profile_of(request, account)
    response = page(
        request,
        "profil/import.html",
        active="profile",
        status_code=400 if error and not is_htmx(request) else 200,
        context={
            "profile": profile,
            "sha256": sha256,
            # The profile is written in French first: an English CV proposes no profile content.
            "sections": {
                key: (title, proposal_items(proposals, key, profile))
                for key, title in PROPOSAL_SECTIONS.items()
            }
            if language == "fr"
            else {},
            "language": language,
            "photo_found": photo is not None,
            "template_id": template_id,
            "templates": _templates_of(request, profile),
            "refusal": refusal,
            "warnings": warnings,
            "preview": tuple(base64.b64encode(image).decode() for image in preview)
            if preview
            else None,
            "message": message,
            "error": error,
        },
    )
    if request.method == "POST":
        response.headers["HX-Replace-Url"] = f"{PROFILE_PATH}/import-cv/{sha256}"
    return response


@router.post("/import-cv/{sha256}/photo", response_class=HTMLResponse)
def take_imported_photo(
    request: Request, account: CurrentAccount, sha256: str
) -> Response:
    try:
        _, photo = read_proposals(_files(request), account.id, sha256)
    except (FileError, ImportRefusedError, ProfileInputError):
        return Response(status_code=404)
    if photo is None:
        return Response(status_code=404)
    stored = _files(request).put_file(account.id, "photos", photo, "jpg")
    with _editor(request, account, writes=True) as editor:
        editor.save_photo(StoredPhoto(stored.path, stored.sha256))
    return _import_page(request, account, sha256, message="Photo ajoutée à ton profil.")


@router.post("/import-cv/{sha256}/{section}", response_class=HTMLResponse)
def take_proposals(
    request: Request, account: CurrentAccount, form: Form, sha256: str, section: str
) -> Response:
    """Add the chosen items of one section, in one transaction (Q14): nothing already filled is overwritten."""
    if section not in PROPOSAL_SECTIONS:
        return Response(status_code=404)
    try:
        proposals, _ = read_proposals(_files(request), account.id, sha256)
    except (FileError, ImportRefusedError, ProfileInputError):
        return Response(status_code=404)
    try:
        with _editor(request, account, writes=True) as editor:
            added = apply_proposals(
                editor, proposals, section, _ids(form, "choix"), _slots(request, editor)
            )
    except ProfileInputError as error:
        return _import_page(request, account, sha256, error=str(error))
    title = PROPOSAL_SECTIONS[section]
    return _import_page(
        request,
        account,
        sha256,
        message=f"{title} : {added} élément{'s' if added > 1 else ''} ajouté{'s' if added > 1 else ''}.",
    )


@router.post("/gabarit/neutre", response_class=HTMLResponse)
def use_neutral_template(
    request: Request, account: CurrentAccount, form: Form
) -> Response:
    language = "en" if _text(form, "langue") == "en" else "fr"
    return _write(
        request,
        account,
        form,
        "kit",
        "",
        lambda e, _: e.activate_cv_template(None, language),
    )


@router.post("/gabarit/{template_id}/activer", response_class=HTMLResponse)
def use_template(
    request: Request, account: CurrentAccount, form: Form, template_id: int
) -> Response:
    return _write(
        request,
        account,
        form,
        "kit",
        "",
        lambda e, _: _activate(e, template_id),
    )


@router.post("/gabarit/{template_id}/supprimer", response_class=HTMLResponse)
def delete_template(
    request: Request, account: CurrentAccount, form: Form, template_id: int
) -> Response:
    """Remove a template no longer used (decision D6, Q8), after the confirmation of the section."""
    return _write(
        request,
        account,
        form,
        "kit",
        "",
        lambda e, _: e.delete_cv_template(template_id),
    )


def _activate(editor: ProfileEditor, template_id: int) -> bool:
    record = next((t for t in editor.cv_templates() if t.id == template_id), None)
    return record is not None and editor.activate_cv_template(
        record.id, record.language
    )
