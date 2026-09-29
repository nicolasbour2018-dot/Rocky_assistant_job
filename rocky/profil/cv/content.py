"""What a CV shows, in one language: the profile and its master CV layout, resolved to texts (pure, no I/O).

Decision ``docs/decisions/D2-cv-rendu.md``:
- Q10: only what the layout holds, in its order; experiences and education always, most recent first;
- Q11: in English, a shown text without its English version is listed in ``missing`` and the CV is refused;
  a French text never stands in for an English one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from rocky.profil.model import (
    LANGUAGE_LEVEL_LABELS,
    LANGUAGE_NAMES,
    ExperienceDraft,
    ExperienceKind,
    LanguageLevel,
    Profile,
    Project,
    Text,
)
from rocky.profil.rules import age_on, link_icon

LANGUAGES = ("fr", "en")

LANGUAGE_NAMES_EN = {
    "fr": "French",
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "ru": "Russian",
    "pl": "Polish",
    "tr": "Turkish",
    "hi": "Hindi",
    "ko": "Korean",
    "sv": "Swedish",
}
LEVEL_LABELS_EN = {
    **{level: level.value.upper() for level in LanguageLevel},
    LanguageLevel.NATIVE: "Native",
}
_BOLD = re.compile(r"\*\*(.+?)\*\*")

# A text of the profile in the CV language; a missing English text is recorded under the given place.
type Translate = Callable[[Text, str], str]


@dataclass(frozen=True)
class Span:
    """A piece of text, bold or not (``**mot**`` in the profile)."""

    text: str
    bold: bool = False


@dataclass(frozen=True)
class CvLink:
    label: str
    url: str
    icon: str | None  # linkedin, github, huggingface


@dataclass(frozen=True)
class CvGroup:
    name: str
    skills: tuple[str, ...]


@dataclass(frozen=True)
class CvProject:
    name: str
    problem: str
    work: str
    results: str
    stack: tuple[str, ...]


@dataclass(frozen=True)
class CvEntry:
    """One experience or one education line."""

    period: str
    title: str
    organisation: str
    place: str | None
    bullets: tuple[str, ...]


@dataclass(frozen=True)
class CvContent:
    language: str
    full_name: str
    title: str
    age: str | None
    headline: tuple[tuple[Span, ...], ...]  # paragraphs
    email: str | None
    phone: str | None
    city: str | None
    links: tuple[CvLink, ...]
    groups: tuple[CvGroup, ...]
    transversal: tuple[str, ...]
    languages: tuple[tuple[str, str], ...]  # (language, level)
    projects: tuple[CvProject, ...]
    experiences: tuple[CvEntry, ...]
    education: tuple[CvEntry, ...]
    hobbies: tuple[str, ...]
    has_photo: bool
    missing: tuple[str, ...]  # English texts to write before an English CV (Q11)


def cv_content(profile: Profile, language: str, today: date) -> CvContent:
    if language not in LANGUAGES:
        raise ValueError(f"unknown language {language!r}")
    missing: list[str] = []

    def text(value: Text, where: str) -> str:
        if language == "en" and value.fr and not value.en:
            missing.append(where)
            return value.fr
        return value.get(language) or ""

    identity = profile.identity
    skills = {skill.id: skill for skill in profile.skills}
    projects = {project.id: project for project in profile.projects}
    groups = tuple(
        CvGroup(
            name=text(group.name, f"Groupe « {group.name.fr} » : nom"),
            skills=tuple(
                text(skills[s].label, f"Compétence « {skills[s].label.fr} »")
                for s in group.skill_ids
            ),
        )
        for group in profile.cv.groups
    )
    transversal = tuple(
        text(skills[s].label, f"Compétence « {skills[s].label.fr} »")
        for s in profile.cv.transversal
    )
    cv_projects = tuple(_project(projects[p], text) for p in profile.cv.projects)
    entries = {
        kind: tuple(
            _entry(experience.content, language, text)
            for experience in profile.experiences
            if experience.content.kind is kind
        )
        for kind in ExperienceKind
    }
    hobbies = tuple(
        text(hobby.label, f"Loisir « {hobby.label.fr} »")
        for hobby in profile.cv.hobbies
        if hobby.in_cv
    )
    title = text(identity.title, "Identité : titre du CV")
    headline = text(identity.headline, "Identité : accroche")
    return CvContent(
        language=language,
        full_name=identity.full_name,
        title=title,
        age=_age(identity.birth_date, identity.show_age, language, today),
        headline=paragraphs(headline),
        email=identity.contact_email,
        phone=identity.phone,
        city=identity.city,
        links=tuple(
            CvLink(link.label, link.url, link_icon(link.url)) for link in identity.links
        ),
        groups=groups,
        transversal=transversal,
        languages=tuple(
            _language(item.content.code, item.content.level, language)
            for item in profile.languages
        ),
        projects=cv_projects,
        experiences=entries[ExperienceKind.JOB],
        education=entries[ExperienceKind.EDUCATION],
        hobbies=hobbies,
        has_photo=profile.photo is not None,
        missing=tuple(dict.fromkeys(missing)),
    )


def paragraphs(value: str) -> tuple[tuple[Span, ...], ...]:
    """Paragraphs separated by a blank line; ``**…**`` marks bold words."""
    blocks = [" ".join(block.split()) for block in re.split(r"\n\s*\n", value)]
    return tuple(_spans(block) for block in blocks if block)


def _spans(block: str) -> tuple[Span, ...]:
    spans: list[Span] = []
    position = 0
    for match in _BOLD.finditer(block):
        if match.start() > position:
            spans.append(Span(block[position : match.start()]))
        spans.append(Span(match.group(1), bold=True))
        position = match.end()
    if position < len(block):
        spans.append(Span(block[position:]))
    return tuple(spans)


def _age(born: date | None, shown: bool, language: str, today: date) -> str | None:
    if born is None or not shown:
        return None
    years = age_on(born, today)
    return f"{years} ans" if language == "fr" else f"{years} years old"


def _language(code: str, level: LanguageLevel, language: str) -> tuple[str, str]:
    if language == "en":
        return LANGUAGE_NAMES_EN.get(code, code), LEVEL_LABELS_EN[level]
    return LANGUAGE_NAMES.get(code, code), LANGUAGE_LEVEL_LABELS[level]


def _period(start: date, end: date | None, language: str) -> str:
    """Years only: the months of the reimported profile are approximate (B5)."""
    if end is None:
        return f"{start.year} – {'aujourd’hui' if language == 'fr' else 'present'}"
    if end.year == start.year:
        return str(start.year)
    return f"{start.year} – {end.year}"


def _entry(content: ExperienceDraft, language: str, text: Translate) -> CvEntry:
    what = "Expérience" if content.kind is ExperienceKind.JOB else "Formation"
    where = f"{what} « {content.title.fr} »"
    bullets = content.bullets_fr
    if language == "en":
        # The bullets as one text, so that missing English bullets are recorded like any other text.
        both = Text(
            "\n".join(content.bullets_fr), "\n".join(content.bullets_en) or None
        )
        text(both, f"{where} : puces")
        bullets = content.bullets_en or content.bullets_fr
    return CvEntry(
        period=_period(content.start, content.end, language),
        title=text(content.title, f"{where} : intitulé"),
        organisation=content.organisation,
        place=content.place,
        bullets=bullets,
    )


def _project(project: Project, text: Translate) -> CvProject:
    content = project.content
    where = f"Projet « {content.name.fr} »"
    return CvProject(
        name=text(content.name, f"{where} : nom"),
        problem=text(content.problem, f"{where} : problème"),
        work=text(content.work, f"{where} : réalisation"),
        results=text(content.results, f"{where} : résultats"),
        stack=content.stack,
    )
