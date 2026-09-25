"""👤 Profil & kit screen and the guided onboarding.

The page is a list of sections; each section is read first and edited in place. HTMX replaces one section at
a time (``#section-<key>``); without HTMX, every route answers a whole page or a redirection.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData

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
    Experience,
    ExperienceKind,
    Language,
    LanguageLevel,
    Profile,
    Project,
    RemoteMode,
    Skill,
    SkillCategory,
    SkillDraft,
    SkillLevel,
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
)
from rocky.profil.sql import SqlProfileStore
from rocky.profil.usecases import Clock, ProfileEditor
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.shell import NAVIGATION, is_htmx, page, wants_fragment

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
    Section("kit", "Kit de candidature"),
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
    app.include_router(router)


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
def _editor(request: Request, account: Account) -> Iterator[ProfileEditor]:
    """One use case, one transaction: committed on exit, rolled back on error."""
    engine: Engine = request.app.state.engine
    clock: Clock = request.app.state.auth.clock
    with engine.begin() as connection:
        yield ProfileEditor(
            SqlProfileStore(connection),
            clock=clock,
            account_id=account.id,
            email=account.email,
        )


def skills_of(request: Request, account: Account) -> tuple[SkillDraft, ...]:
    """The account's skills, for the screens of the other modules (read through the profile use case)."""
    with _editor(request, account) as editor:
        return tuple(skill.content for skill in editor.profile().skills)


def _error_status(request: Request) -> int:
    # HTMX does not swap 4xx answers: a form error it asked for comes back as 200.
    return 200 if is_htmx(request) else 400


async def _form(request: Request) -> FormData:
    return await request.form()


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


def _read_profile(request: Request, account: Account) -> Profile:
    with _editor(request, account) as editor:
        return editor.profile()


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
        "linkedin_url": identity.linkedin_url,
        "github_url": identity.github_url,
        "portfolio_url": identity.portfolio_url,
        "headline_fr": identity.headline.fr,
        "headline_en": identity.headline.en,
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
    item_id = int(editing) if editing.isdigit() else None
    if editing != NEW and item_id is None and key != "identite":
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
    }
    finder = finders.get(key)
    return None if finder is None else finder()


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
    return _render(request, _read_profile(request, account))


@router.get("/demarrage", response_class=HTMLResponse)
def onboarding(
    request: Request, account: CurrentAccount, etape: int = 1
) -> HTMLResponse:
    profile = _read_profile(request, account)
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
        with _editor(request, account) as editor:
            current = editor.profile().identity
            editor.save_identity(
                make_identity(
                    full_name=_text(form, "full_name"),
                    contact_email=_text(form, "contact_email"),
                    city=_text(form, "city"),
                    postal_code=_text(form, "postal_code"),
                    phone=current.phone,
                    linkedin_url=current.linkedin_url,
                    github_url=current.github_url,
                    portfolio_url=current.portfolio_url,
                    headline_fr=current.headline.fr,
                    headline_en=current.headline.en,
                )
            )
    except ProfileInputError as error:
        profile = _read_profile(request, account)
        return _onboarding_page(request, profile, 1, form=form, error=str(error))
    return RedirectResponse(f"{ONBOARDING_PATH}?etape=2", status_code=303)


@router.post("/demarrage/competences", response_class=HTMLResponse)
def onboarding_skills(
    request: Request, account: CurrentAccount, form: Form
) -> Response:
    with _editor(request, account) as editor:
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
        with _editor(request, account) as editor:
            editor.add_track(track)
    except ProfileInputError as error:
        profile = _read_profile(request, account)
        return _onboarding_page(request, profile, 3, form=form, error=str(error))
    return RedirectResponse(PROFILE_PATH, status_code=303)


@router.post("/demarrage/plus-tard")
def defer_onboarding(request: Request, account: CurrentAccount) -> Response:
    with _editor(request, account) as editor:
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
    profile = _read_profile(request, account)
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
    return [int(v) for v in form.getlist(name) if isinstance(v, str) and v.isdigit()]


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
        with _editor(request, account) as editor:
            if change(editor, form) is False:
                return Response(status_code=404)
            profile = editor.profile()
    except ProfileInputError as error:
        return _refused(
            request, _read_profile(request, account), key, editing, form, error
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
                    "linkedin_url",
                    "github_url",
                    "portfolio_url",
                    "headline_fr",
                    "headline_en",
                )
            }
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
