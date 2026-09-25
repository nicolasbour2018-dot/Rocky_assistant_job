"""Profile rules: no I/O and no clock. Builders turn raw input into drafts, or refuse it.

Error messages here are shown to the user, hence in French.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import date
from enum import StrEnum

from rocky.profil.model import (
    LANGUAGE_NAMES,
    Contract,
    ExperienceDraft,
    ExperienceKind,
    Identity,
    LanguageDraft,
    LanguageLevel,
    OnboardingState,
    Preferences,
    Profile,
    ProjectDraft,
    RemoteMode,
    SkillCategory,
    SkillDraft,
    SkillLevel,
    Text,
    Track,
    TrackDraft,
    TrackStatus,
)

NAME_MAX_LENGTH = 80
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")
_NOT_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")


class ProfileInputError(ValueError):
    """Input that cannot become part of a profile; the message is shown as is."""


def normalize_term(value: str) -> str:
    """Comparison form of a skill name: no case, no accent, no punctuation.

    "Traitement du langage naturel (NLP)" and "traitement du langage naturel nlp" are the same term.
    """
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NOT_ALPHANUMERIC.sub(" ", without_accents).strip()


def clean_lines(values: str | Iterable[str]) -> tuple[str, ...]:
    """Non-empty trimmed entries, one per line, without repeats (compared as terms)."""
    lines = values.splitlines() if isinstance(values, str) else values
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        entry = " ".join(line.split())
        term = normalize_term(entry)
        if entry and term not in seen:
            seen.add(term)
            kept.append(entry)
    return tuple(kept)


def optional(value: str | None) -> str | None:
    """Trimmed text, or None when nothing is left."""
    text = " ".join((value or "").split())
    return text or None


def optional_block(value: str | None) -> str | None:
    """Trimmed multi-line text (paragraphs kept), or None when nothing is left."""
    lines = [line.rstrip() for line in (value or "").strip().splitlines()]
    return "\n".join(lines) or None


def code[C: StrEnum](kind: type[C], value: str, message: str) -> C:
    try:
        return kind(value)
    except ValueError:
        raise ProfileInputError(message) from None


def codes[C: StrEnum](
    kind: type[C], values: Iterable[str], message: str
) -> tuple[C, ...]:
    """Codes in the order of the enumeration, each once."""
    chosen = {code(kind, value, message) for value in values if value}
    return tuple(member for member in kind if member in chosen)


def make_identity(
    *,
    full_name: str,
    contact_email: str | None = None,
    phone: str | None = None,
    city: str | None = None,
    postal_code: str | None = None,
    linkedin_url: str | None = None,
    github_url: str | None = None,
    portfolio_url: str | None = None,
    headline_fr: str | None = None,
    headline_en: str | None = None,
) -> Identity:
    name = optional(full_name)
    if name is None:
        raise ProfileInputError("Indique ton nom.")
    email = optional(contact_email)
    if email is not None and not EMAIL_PATTERN.fullmatch(email):
        raise ProfileInputError("L'e-mail de contact n'est pas une adresse valide.")
    return Identity(
        full_name=name,
        contact_email=email,
        phone=optional(phone),
        city=optional(city),
        postal_code=optional(postal_code),
        linkedin_url=_url(linkedin_url, "LinkedIn"),
        github_url=_url(github_url, "GitHub"),
        portfolio_url=_url(portfolio_url, "portfolio"),
        headline=Text(optional_block(headline_fr) or "", optional_block(headline_en)),
    )


def _url(value: str | None, name: str) -> str | None:
    url = optional(value)
    if url is not None and not url.startswith(("https://", "http://")):
        raise ProfileInputError(f"Le lien {name} doit commencer par https://.")
    return url


def make_preferences(
    *,
    contracts: Iterable[str] = (),
    remote_modes: Iterable[str] = (),
    min_salary_eur: str | int | None = None,
    min_daily_rate_eur: str | int | None = None,
) -> Preferences:
    return Preferences(
        contracts=codes(Contract, contracts, "Type de contrat inconnu."),
        remote_modes=codes(RemoteMode, remote_modes, "Mode de télétravail inconnu."),
        min_salary_eur=_amount(min_salary_eur, "Le salaire minimal"),
        min_daily_rate_eur=_amount(min_daily_rate_eur, "Le TJM minimal"),
    )


def _amount(value: str | int | None, name: str) -> int | None:
    if value is None or isinstance(value, int):
        amount = value
    else:
        digits = "".join(value.split()).removesuffix("€")
        if not digits:
            return None
        if not digits.isdigit():
            raise ProfileInputError(f"{name} doit être un nombre entier d'euros.")
        amount = int(digits)
    if amount is not None and amount <= 0:
        raise ProfileInputError(f"{name} doit être positif.")
    return amount


def make_track(
    *,
    name: str,
    titles: str | Iterable[str] = (),
    keywords: str | Iterable[str] = (),
    excluded_keywords: str | Iterable[str] = (),
    locations: str | Iterable[str] = (),
) -> TrackDraft:
    track_name = optional(name)
    if track_name is None:
        raise ProfileInputError("Donne un nom à la piste.")
    if len(track_name) > NAME_MAX_LENGTH:
        raise ProfileInputError(
            f"Le nom de la piste dépasse {NAME_MAX_LENGTH} caractères."
        )
    wanted = clean_lines(keywords)
    excluded = clean_lines(excluded_keywords)
    both = {normalize_term(k) for k in wanted} & {normalize_term(k) for k in excluded}
    if both:
        clash = next(k for k in wanted if normalize_term(k) in both)
        raise ProfileInputError(
            f"« {clash} » est à la fois un mot-clé et un mot exclu."
        )
    return TrackDraft(
        name=track_name,
        titles=clean_lines(titles),
        keywords=wanted,
        excluded_keywords=excluded,
        locations=clean_lines(locations),
    )


def track_is_ready(track: Track) -> bool:
    """A track the watch can run: active, with a title to search and a place."""
    return (
        track.status is TrackStatus.ACTIVE
        and bool(track.content.titles)
        and bool(track.content.locations)
    )


def is_ready(tracks: Sequence[Track]) -> bool:
    return any(track_is_ready(track) for track in tracks)


def needs_onboarding(state: OnboardingState | None) -> bool:
    """Main pages lead to the onboarding until it is completed or put off."""
    return state is None or (state.completed_at is None and state.deferred_at is None)


def missing_for_ready(profile: Profile) -> list[str]:
    """What the profile still lacks before the watch can run, in the user's words."""
    missing = []
    if not profile.identity.full_name:
        missing.append("ton nom")
    if not profile.skills:
        missing.append("tes compétences")
    if not is_ready(profile.tracks):
        missing.append("une piste active avec au moins un intitulé et un lieu")
    return missing


def has_content(profile: Profile) -> bool:
    """Anything written in the profile beyond its creation (an import is refused then)."""
    return bool(
        profile.identity.full_name
        or profile.tracks
        or profile.skills
        or profile.languages
        or profile.experiences
        or profile.projects
    )


def make_skill(
    *,
    label_fr: str,
    category: str,
    label_en: str | None = None,
    aliases: str | Iterable[str] = (),
    level: str | None = None,
    is_key: bool = False,
) -> SkillDraft:
    label = optional(label_fr)
    if label is None:
        raise ProfileInputError("Donne un nom à la compétence.")
    return SkillDraft(
        label=Text(label, optional(label_en)),
        category=code(SkillCategory, category, "Catégorie de compétence inconnue."),
        aliases=clean_lines(aliases),
        level=code(SkillLevel, level, "Niveau inconnu.") if level else None,
        is_key=is_key,
    )


def skill_terms(skill: SkillDraft) -> frozenset[str]:
    """Every name the skill answers to; two skills of a profile never share one."""
    names = [skill.label.fr, skill.label.en or "", *skill.aliases]
    return frozenset(term for name in names if (term := normalize_term(name)))


def make_language(*, code_value: str, level: str) -> LanguageDraft:
    if code_value not in LANGUAGE_NAMES:
        raise ProfileInputError("Langue inconnue.")
    return LanguageDraft(
        code=code_value, level=code(LanguageLevel, level, "Niveau de langue inconnu.")
    )


def parse_month(value: str, name: str) -> date:
    """ "2024-09" → 1 September 2024."""
    match = MONTH_PATTERN.fullmatch(value.strip())
    month = int(match["month"]) if match else 0
    if match is None or not 1 <= month <= 12:
        raise ProfileInputError(f"{name} doit être un mois (AAAA-MM).")
    return date(int(match["year"]), month, 1)


def make_experience(
    *,
    kind: str,
    title_fr: str,
    organisation: str,
    start: str,
    end: str | None = None,
    title_en: str | None = None,
    place: str | None = None,
    bullets_fr: str | Iterable[str] = (),
    bullets_en: str | Iterable[str] = (),
    skill_ids: Iterable[int] = (),
) -> ExperienceDraft:
    title = optional(title_fr)
    if title is None:
        raise ProfileInputError("Indique l'intitulé du poste ou du diplôme.")
    where = optional(organisation)
    if where is None:
        raise ProfileInputError("Indique l'organisme (entreprise, école…).")
    begins = parse_month(start, "Le début")
    ends = parse_month(end, "La fin") if end and optional(end) else None
    if ends is not None and ends < begins:
        raise ProfileInputError("La fin précède le début.")
    return ExperienceDraft(
        kind=code(ExperienceKind, kind, "Type de parcours inconnu."),
        title=Text(title, optional(title_en)),
        organisation=where,
        start=begins,
        end=ends,
        place=optional(place),
        bullets_fr=_bullets(bullets_fr),
        bullets_en=_bullets(bullets_en),
        skill_ids=tuple(dict.fromkeys(skill_ids)),
    )


def _bullets(values: str | Iterable[str]) -> tuple[str, ...]:
    """Bullets keep their order and may repeat words; only blank lines go."""
    lines = values.splitlines() if isinstance(values, str) else values
    return tuple(text for line in lines if (text := " ".join(line.split())))


def make_project(
    *,
    name_fr: str,
    name_en: str | None = None,
    problem_fr: str | None = None,
    problem_en: str | None = None,
    work_fr: str | None = None,
    work_en: str | None = None,
    results_fr: str | None = None,
    results_en: str | None = None,
    stack: str | Iterable[str] = (),
    url: str | None = None,
    skill_ids: Iterable[int] = (),
) -> ProjectDraft:
    name = optional(name_fr)
    if name is None:
        raise ProfileInputError("Donne un nom au projet.")
    return ProjectDraft(
        name=Text(name, optional(name_en)),
        problem=Text(optional_block(problem_fr) or "", optional_block(problem_en)),
        work=Text(optional_block(work_fr) or "", optional_block(work_en)),
        results=Text(optional_block(results_fr) or "", optional_block(results_en)),
        stack=clean_lines(stack),
        url=_url(url, "du projet"),
        skill_ids=tuple(dict.fromkeys(skill_ids)),
    )
