"""Profile records, stored codes and the storage port used by the use cases.

Stored values are English codes; French labels only exist for display (``LABELS`` dictionaries).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from rocky.system.events import NewEvent


class Contract(StrEnum):
    PERMANENT = "permanent"
    FIXED_TERM = "fixed_term"
    FREELANCE = "freelance"
    INTERNATIONAL_VOLUNTEER = "international_volunteer"
    INTERNSHIP = "internship"
    APPRENTICESHIP = "apprenticeship"
    TEMPORARY = "temporary"


CONTRACT_LABELS = {
    Contract.PERMANENT: "CDI",
    Contract.FIXED_TERM: "CDD",
    Contract.FREELANCE: "Freelance",
    Contract.INTERNATIONAL_VOLUNTEER: "VIE",
    Contract.INTERNSHIP: "Stage",
    Contract.APPRENTICESHIP: "Alternance",
    Contract.TEMPORARY: "Intérim",
}


class RemoteMode(StrEnum):
    ON_SITE = "on_site"
    HYBRID = "hybrid"
    FULL_REMOTE = "full_remote"


REMOTE_LABELS = {
    RemoteMode.ON_SITE: "Sur site",
    RemoteMode.HYBRID: "Hybride",
    RemoteMode.FULL_REMOTE: "Télétravail complet",
}


class TrackStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


TRACK_STATUS_LABELS = {
    TrackStatus.ACTIVE: "Active",
    TrackStatus.PAUSED: "En pause",
    TrackStatus.ARCHIVED: "Archivée",
}


class SkillLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


SKILL_LEVEL_LABELS = {
    SkillLevel.BEGINNER: "Débutant",
    SkillLevel.INTERMEDIATE: "Intermédiaire",
    SkillLevel.ADVANCED: "Avancé",
    SkillLevel.EXPERT: "Expert",
}


class SkillCategory(StrEnum):
    TECHNICAL = "technical"
    BUSINESS = "business"
    SOFT = "soft"


SKILL_CATEGORY_LABELS = {
    SkillCategory.TECHNICAL: "Techniques",
    SkillCategory.BUSINESS: "Métier",
    SkillCategory.SOFT: "Savoir-être",
}


class LanguageLevel(StrEnum):
    A1 = "a1"
    A2 = "a2"
    B1 = "b1"
    B2 = "b2"
    C1 = "c1"
    C2 = "c2"
    NATIVE = "native"


LANGUAGE_LEVEL_LABELS = {
    **{level: level.value.upper() for level in LanguageLevel},
    LanguageLevel.NATIVE: "Langue maternelle",
}

# ISO 639-1 codes offered on screen; the order is the order of the list.
LANGUAGE_NAMES = {
    "fr": "Français",
    "en": "Anglais",
    "es": "Espagnol",
    "de": "Allemand",
    "it": "Italien",
    "pt": "Portugais",
    "nl": "Néerlandais",
    "ar": "Arabe",
    "zh": "Chinois",
    "ja": "Japonais",
    "ru": "Russe",
    "pl": "Polonais",
    "tr": "Turc",
    "hi": "Hindi",
    "ko": "Coréen",
    "sv": "Suédois",
}


class ExperienceKind(StrEnum):
    JOB = "job"
    EDUCATION = "education"


EXPERIENCE_KIND_LABELS = {
    ExperienceKind.JOB: "Expérience",
    ExperienceKind.EDUCATION: "Formation",
}


@dataclass(frozen=True)
class Text:
    """A text written in French, optionally translated into English."""

    fr: str
    en: str | None = None

    def get(self, language: str) -> str | None:
        return self.en if language == "en" else self.fr


NO_TEXT = Text("")


@dataclass(frozen=True)
class Identity:
    full_name: str = ""
    contact_email: str | None = None
    phone: str | None = None
    city: str | None = None
    postal_code: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    headline: Text = NO_TEXT


@dataclass(frozen=True)
class Preferences:
    contracts: tuple[Contract, ...] = ()
    remote_modes: tuple[RemoteMode, ...] = ()
    min_salary_eur: int | None = None
    min_daily_rate_eur: int | None = None


@dataclass(frozen=True)
class TrackDraft:
    name: str
    titles: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Track:
    id: int
    status: TrackStatus
    content: TrackDraft

    @property
    def name(self) -> str:
        return self.content.name


@dataclass(frozen=True)
class SkillDraft:
    label: Text
    category: SkillCategory
    aliases: tuple[str, ...] = ()
    level: SkillLevel | None = None
    is_key: bool = False


@dataclass(frozen=True)
class Skill:
    id: int
    content: SkillDraft

    @property
    def label(self) -> Text:
        return self.content.label


@dataclass(frozen=True)
class LanguageDraft:
    code: str
    level: LanguageLevel


@dataclass(frozen=True)
class Language:
    id: int
    content: LanguageDraft


@dataclass(frozen=True)
class ExperienceDraft:
    kind: ExperienceKind
    title: Text
    organisation: str
    start: date
    end: date | None = None
    place: str | None = None
    bullets_fr: tuple[str, ...] = ()
    bullets_en: tuple[str, ...] = ()
    skill_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class Experience:
    id: int
    content: ExperienceDraft


@dataclass(frozen=True)
class ProjectDraft:
    name: Text
    problem: Text = NO_TEXT
    work: Text = NO_TEXT
    results: Text = NO_TEXT
    stack: tuple[str, ...] = ()
    url: str | None = None
    skill_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class Project:
    id: int
    content: ProjectDraft


@dataclass(frozen=True)
class OnboardingState:
    completed_at: datetime | None = None
    deferred_at: datetime | None = None


@dataclass(frozen=True)
class Profile:
    """Everything the profile of one account holds, as read in one transaction."""

    id: int
    account_id: int
    identity: Identity
    preferences: Preferences
    onboarding: OnboardingState
    tracks: tuple[Track, ...] = ()
    skills: tuple[Skill, ...] = ()
    languages: tuple[Language, ...] = ()
    experiences: tuple[Experience, ...] = ()
    projects: tuple[Project, ...] = ()

    def skill(self, skill_id: int) -> Skill | None:
        return next((s for s in self.skills if s.id == skill_id), None)

    def track(self, track_id: int) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)


class ProfileStore(Protocol):
    """Storage of the profile aggregate, bound to one open transaction.

    Implementations never begin nor commit: the caller owns the transaction. Methods acting on one item take
    the profile id too and return False (or None) when the item does not belong to that profile.
    """

    def find_profile_id(self, account_id: int) -> int | None: ...

    def create_profile(
        self, account_id: int, contact_email: str, now: datetime
    ) -> int: ...

    def onboarding_state(self, account_id: int) -> OnboardingState | None:
        """None when the account has no profile yet."""
        ...

    def load(self, profile_id: int) -> Profile: ...

    def save_identity(
        self, profile_id: int, identity: Identity, now: datetime
    ) -> None: ...

    def save_preferences(
        self, profile_id: int, preferences: Preferences, now: datetime
    ) -> None: ...

    def mark_onboarding_completed(self, profile_id: int, now: datetime) -> None: ...

    def mark_onboarding_deferred(self, profile_id: int, now: datetime) -> None: ...

    def add_track(self, profile_id: int, track: TrackDraft, now: datetime) -> int: ...

    def update_track(
        self, profile_id: int, track_id: int, track: TrackDraft, now: datetime
    ) -> bool: ...

    def set_track_status(
        self, profile_id: int, track_id: int, status: TrackStatus, now: datetime
    ) -> bool: ...

    def delete_track(self, profile_id: int, track_id: int) -> bool: ...

    def term_owners(
        self, profile_id: int, terms: frozenset[str], except_skill: int | None
    ) -> list[str]:
        """French labels of the other skills already using one of ``terms``."""
        ...

    def add_skill(
        self, profile_id: int, skill: SkillDraft, terms: frozenset[str]
    ) -> int: ...

    def update_skill(
        self,
        profile_id: int,
        skill_id: int,
        skill: SkillDraft,
        terms: frozenset[str],
    ) -> bool: ...

    def delete_skill(self, profile_id: int, skill_id: int) -> bool: ...

    def add_language(self, profile_id: int, language: LanguageDraft) -> int: ...

    def update_language(
        self, profile_id: int, language_id: int, language: LanguageDraft
    ) -> bool: ...

    def delete_language(self, profile_id: int, language_id: int) -> bool: ...

    def add_experience(self, profile_id: int, experience: ExperienceDraft) -> int: ...

    def update_experience(
        self, profile_id: int, experience_id: int, experience: ExperienceDraft
    ) -> bool: ...

    def delete_experience(self, profile_id: int, experience_id: int) -> bool: ...

    def add_project(self, profile_id: int, project: ProjectDraft) -> int: ...

    def update_project(
        self, profile_id: int, project_id: int, project: ProjectDraft
    ) -> bool: ...

    def delete_project(self, profile_id: int, project_id: int) -> bool: ...

    def append_event(self, event: NewEvent) -> None: ...


@dataclass(frozen=True)
class ImportedExperience:
    """An experience from an import file: its skills are named, not yet identified."""

    content: ExperienceDraft
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportedProject:
    content: ProjectDraft
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportedProfile:
    """A reviewed profile file (``rocky-admin import-profil``), validated field by field."""

    identity: Identity
    preferences: Preferences = Preferences()
    skills: tuple[SkillDraft, ...] = ()
    languages: tuple[LanguageDraft, ...] = ()
    experiences: tuple[ImportedExperience, ...] = ()
    projects: tuple[ImportedProject, ...] = ()
    tracks: tuple[TrackDraft, ...] = ()
