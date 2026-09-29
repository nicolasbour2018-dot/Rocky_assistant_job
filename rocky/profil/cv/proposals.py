"""Profile proposals read from an imported CV (decision D2, Q14): section by section, never overwriting.

The model copied the CV into ``profile`` (``semantics.SCHEMA``); this module reads that copy defensively, tells
which items the profile already holds, and adds the chosen ones through the profile use cases. An identity field
already filled is kept; a skill, a language, an experience or a project already there is not added twice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from rocky.profil.cv.layout import add_group, add_hobby, place_skill
from rocky.profil.cv.template import Slots
from rocky.profil.model import (
    LANGUAGE_NAMES,
    CvLayout,
    Experience,
    ExperienceDraft,
    Hobby,
    Identity,
    Language,
    LanguageLevel,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    Skill,
    SkillCategory,
    SkillDraft,
    SkillGroup,
    Text,
)
from rocky.profil.rules import (
    ProfileInputError,
    make_experience,
    make_identity,
    make_language,
    make_project,
    make_skill,
    normalize_term,
    skill_terms,
)
from rocky.profil.usecases import ProfileEditor

SECTIONS = {
    "identite": "Identité",
    "competences": "Compétences techniques",
    "transversales": "Compétences transversales",
    "langues": "Langues",
    "parcours": "Expériences et formations",
    "projets": "Projets",
    "loisirs": "Loisirs",
}
IDENTITY_FIELDS = {
    "full_name": "Nom",
    "title": "Titre",
    "headline": "Accroche",
    "email": "E-mail",
    "phone": "Téléphone",
    "city": "Ville",
}
LANGUAGE_CODES = {
    **{normalize_term(name): code for code, name in LANGUAGE_NAMES.items()},
    "english": "en",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "italian": "it",
}


@dataclass(frozen=True)
class Item:
    """One proposal as shown: its text, and whether the profile already has it."""

    index: int
    text: str
    present: bool


def items(
    proposals: Mapping[str, Any], section: str, profile: Profile
) -> tuple[Item, ...]:
    """What ``section`` proposes, each with its place in the proposals (the check boxes send it back)."""
    if section == "identite":
        current = _identity_values(profile)
        return tuple(
            Item(i, f"{label} : {value}", bool(current[key]))
            for i, (key, label) in enumerate(IDENTITY_FIELDS.items())
            if (value := _text(proposals.get(key)))
        )
    if section == "competences":
        return tuple(
            Item(
                i,
                f"{_text(g.get('name'))} : {', '.join(_texts(g.get('skills')))}",
                False,
            )
            for i, g in enumerate(_list(proposals.get("skill_groups")))
        )
    if section == "transversales":
        known = _terms(profile)
        return tuple(
            Item(
                i,
                name,
                bool(skill_terms(make_skill(label_fr=name, category="soft")) & known),
            )
            for i, name in enumerate(_texts(proposals.get("transversal")))
        )
    if section == "langues":
        codes = {item.content.code for item in profile.languages}
        return tuple(
            Item(
                i,
                f"{_text(item.get('name'))} ({_text(item.get('level')).upper()})",
                _code(item) in codes,
            )
            for i, item in enumerate(_list(proposals.get("languages")))
        )
    if section == "parcours":
        held = {_experience_key(e.content) for e in profile.experiences}
        return tuple(
            Item(
                i,
                f"{_text(e.get('title'))} — {_text(e.get('organisation'))} ({e.get('start_year')})",
                _raw_experience_key(e) in held,
            )
            for i, e in enumerate(_list(proposals.get("experiences")))
        )
    if section == "projets":
        names = {normalize_term(p.content.name.fr) for p in profile.projects}
        return tuple(
            Item(i, _text(p.get("name")), normalize_term(_text(p.get("name"))) in names)
            for i, p in enumerate(_list(proposals.get("projects")))
        )
    if section == "loisirs":
        hobbies = {normalize_term(h.label.fr) for h in profile.cv.hobbies}
        return tuple(
            Item(i, name, normalize_term(name) in hobbies)
            for i, name in enumerate(_texts(proposals.get("hobbies")))
        )
    raise ValueError(f"unknown section {section!r}")


def apply(
    editor: ProfileEditor,
    proposals: Mapping[str, Any],
    section: str,
    chosen: Sequence[int],
    slots: Slots,
) -> int:
    """Add the chosen items of one section, in the caller's transaction; the number of items added."""
    profile = editor.profile()
    wanted = set(chosen)
    present = {
        item.index for item in items(proposals, section, profile) if item.present
    }
    selected = sorted(wanted - present)
    if section == "identite":
        return _apply_identity(editor, proposals, profile, selected)
    if section == "competences":
        return _apply_groups(editor, proposals, selected, slots)
    if section == "transversales":
        return _apply_transversal(editor, proposals, selected, slots)
    if section == "langues":
        languages = _list(proposals.get("languages"))
        for index in selected:
            item = languages[index]
            code = _code(item)
            if code is None:
                raise ProfileInputError(
                    f"Langue non reconnue : « {_text(item.get('name'))} »."
                )
            editor.add_language(
                make_language(code_value=code, level=_text(item.get("level")))
            )
        return len(selected)
    if section == "parcours":
        experiences = _list(proposals.get("experiences"))
        for index in selected:
            editor.add_experience(_experience(experiences[index]))
        return len(selected)
    if section == "projets":
        projects = _list(proposals.get("projects"))
        added = [editor.add_project(_project(projects[index])) for index in selected]
        layout = editor.profile().cv
        room = max(slots.projects - len(layout.projects), 0)
        editor.save_cv_layout(
            replace(layout, projects=(*layout.projects, *added[:room])), slots
        )
        return len(added)
    if section == "loisirs":
        names = _texts(proposals.get("hobbies"))
        layout = editor.profile().cv
        for index in selected:
            layout = add_hobby(layout, Text(names[index]))
        in_cv = [hobby for hobby in layout.hobbies if hobby.in_cv]
        if len(in_cv) > slots.hobbies:
            # Beyond the template's room, the extra hobbies stay in the profile, out of the CV.
            kept = {id(hobby) for hobby in in_cv[: slots.hobbies]}
            layout = replace(
                layout,
                hobbies=tuple(
                    hobby
                    if not hobby.in_cv or id(hobby) in kept
                    else Hobby(hobby.label, in_cv=False)
                    for hobby in layout.hobbies
                ),
            )
        editor.save_cv_layout(layout, slots)
        return len(selected)
    raise ValueError(f"unknown section {section!r}")


def _apply_identity(
    editor: ProfileEditor,
    proposals: Mapping[str, Any],
    profile: Profile,
    selected: Sequence[int],
) -> int:
    keys = list(IDENTITY_FIELDS)
    chosen = {
        keys[index]
        for index in selected
        if index < len(keys) and _text(proposals.get(keys[index]))
    }
    identity = profile.identity
    values = _identity_values(profile)
    for key in chosen:
        values[key] = (
            _text(proposals.get(key))
            if key != "headline"
            else _block(proposals.get(key))
        )
    editor.save_identity(
        make_identity(
            full_name=values["full_name"] or "",
            contact_email=values["email"],
            phone=values["phone"],
            city=values["city"],
            postal_code=identity.postal_code,
            links=[f"{link.label} | {link.url}" for link in identity.links],
            headline_fr=values["headline"],
            headline_en=identity.headline.en,
            title_fr=values["title"],
            title_en=identity.title.en,
            birth_date=identity.birth_date,
            show_age=identity.show_age,
        )
    )
    return len(chosen)


def _apply_groups(
    editor: ProfileEditor,
    proposals: Mapping[str, Any],
    selected: Sequence[int],
    slots: Slots,
) -> int:
    groups = _list(proposals.get("skill_groups"))
    for index in selected:
        group = groups[index]
        ids = [
            _skill_id(editor, name, SkillCategory.TECHNICAL)
            for name in _texts(group.get("skills"))
        ]
        profile = editor.profile()
        layout = profile.cv
        name = _text(group.get("name")).rstrip(" :") or "Compétences"
        position = next(
            (
                i
                for i, g in enumerate(layout.groups)
                if normalize_term(g.name.fr) == normalize_term(name)
            ),
            None,
        )
        if position is None:
            layout = add_group(layout, Text(name))
            position = len(layout.groups) - 1
        for skill_id in ids:
            if skill_id is not None:
                layout = place_skill(layout, profile, skill_id, position)
        editor.save_cv_layout(layout, slots)
    return len(selected)


def _apply_transversal(
    editor: ProfileEditor,
    proposals: Mapping[str, Any],
    selected: Sequence[int],
    slots: Slots,
) -> int:
    names = _texts(proposals.get("transversal"))
    ids = [_skill_id(editor, names[index], SkillCategory.SOFT) for index in selected]
    profile = editor.profile()
    layout = profile.cv
    for skill_id in ids:
        if skill_id is not None and len(layout.transversal) < slots.transversal:
            layout = place_skill(layout, profile, skill_id, 0)
    editor.save_cv_layout(layout, slots)
    return len(selected)


def _skill_id(editor: ProfileEditor, name: str, category: SkillCategory) -> int | None:
    """The skill of that name, added when the profile has none; None when it exists in another category."""
    draft = make_skill(label_fr=name, category=category.value)
    wanted = skill_terms(draft)
    for skill in editor.profile().skills:
        if skill_terms(skill.content) & wanted:
            fits = (skill.content.category is SkillCategory.TECHNICAL) == (
                category is SkillCategory.TECHNICAL
            )
            return skill.id if fits else None
    return editor.add_skill(draft)


def _identity_values(profile: Profile) -> dict[str, str | None]:
    identity = profile.identity
    return {
        "full_name": identity.full_name or None,
        "title": identity.title.fr or None,
        "headline": identity.headline.fr or None,
        "email": identity.contact_email,
        "phone": identity.phone,
        "city": identity.city,
    }


def _experience(raw: Mapping[str, Any]) -> ExperienceDraft:
    start, end = raw.get("start_year"), raw.get("end_year")
    return make_experience(
        kind=_text(raw.get("kind")) or "job",
        title_fr=_text(raw.get("title")),
        organisation=_text(raw.get("organisation")),
        place=_text(raw.get("place")) or None,
        start=f"{start}-01" if isinstance(start, int) else "",
        end=f"{end}-12" if isinstance(end, int) else None,
        bullets_fr=_texts(raw.get("bullets")),
    )


def _project(raw: Mapping[str, Any]) -> ProjectDraft:
    return make_project(
        name_fr=_text(raw.get("name")),
        problem_fr=_text(raw.get("problem")),
        work_fr=_text(raw.get("work")),
        results_fr=_text(raw.get("results")),
        stack=_texts(raw.get("stack")),
    )


def _experience_key(content: ExperienceDraft) -> tuple[str, str, str]:
    return (
        content.kind.value,
        normalize_term(content.title.fr),
        normalize_term(content.organisation),
    )


def _raw_experience_key(raw: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _text(raw.get("kind")) or "job",
        normalize_term(_text(raw.get("title"))),
        normalize_term(_text(raw.get("organisation"))),
    )


def _code(item: Mapping[str, Any]) -> str | None:
    name = normalize_term(_text(item.get("name")))
    for known, code in LANGUAGE_CODES.items():
        if name == known or name.startswith(known + " "):
            return code
    return None


def _terms(profile: Profile) -> frozenset[str]:
    return frozenset(
        term for skill in profile.skills for term in skill_terms(skill.content)
    )


def _list(value: Any) -> list[Mapping[str, Any]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _texts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _block(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def preview_profile(proposals: Mapping[str, Any]) -> Profile:
    """The CV's own content as a profile, in memory only: what the side-by-side preview shows (Q17)."""
    ids = iter(range(1, 10_000))
    skills: list[Skill] = []
    groups: list[SkillGroup] = []
    for group in _list(proposals.get("skill_groups")):
        members = []
        for name in _texts(group.get("skills")):
            skill = Skill(next(ids), SkillDraft(Text(name), SkillCategory.TECHNICAL))
            skills.append(skill)
            members.append(skill.id)
        groups.append(
            SkillGroup(
                Text(_text(group.get("name")).rstrip(" :") or "—"), tuple(members)
            )
        )
    transversal = []
    for name in _texts(proposals.get("transversal")):
        skill = Skill(next(ids), SkillDraft(Text(name), SkillCategory.SOFT))
        skills.append(skill)
        transversal.append(skill.id)
    languages = tuple(
        Language(
            next(ids), make_language(code_value=code, level=_text(item.get("level")))
        )
        for item in _list(proposals.get("languages"))
        if (code := _code(item)) is not None and _text(item.get("level")) in _LEVELS
    )
    experiences = tuple(
        Experience(next(ids), draft)
        for raw in _list(proposals.get("experiences"))
        if (draft := _safely(_experience, raw)) is not None
    )
    projects = tuple(
        Project(next(ids), project)
        for raw in _list(proposals.get("projects"))
        if (project := _safely(_project, raw)) is not None
    )
    return Profile(
        id=0,
        account_id=0,
        identity=Identity(
            full_name=_text(proposals.get("full_name")),
            contact_email=_text(proposals.get("email")) or None,
            phone=_text(proposals.get("phone")) or None,
            city=_text(proposals.get("city")) or None,
            headline=Text(_block(proposals.get("headline"))),
            title=Text(_text(proposals.get("title"))),
        ),
        preferences=Preferences(),
        onboarding=OnboardingState(),
        skills=tuple(skills),
        languages=languages,
        experiences=experiences,
        projects=projects,
        cv=CvLayout(
            groups=tuple(groups),
            transversal=tuple(transversal),
            projects=tuple(project.id for project in projects),
            hobbies=tuple(
                Hobby(Text(name)) for name in _texts(proposals.get("hobbies"))
            ),
        ),
    )


_LEVELS = frozenset(level.value for level in LanguageLevel)


def _safely[T](
    build: Callable[[Mapping[str, Any]], T], raw: Mapping[str, Any]
) -> T | None:
    """A proposal the rules refuse (no start year…) is left out of the preview; it is refused when chosen."""
    try:
        return build(raw)
    except ProfileInputError:
        return None
