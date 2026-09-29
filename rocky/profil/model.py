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
class Link:
    """A public link of the profile (LinkedIn, GitHub, Hugging Face, portfolio…), in the order of the list."""

    label: str
    url: str


@dataclass(frozen=True)
class Identity:
    full_name: str = ""
    contact_email: str | None = None
    phone: str | None = None
    city: str | None = None
    postal_code: str | None = None
    links: tuple[Link, ...] = ()
    # The profile paragraph at the top of the CV (written by the B5 import), and the short title (decision D2, Q8).
    headline: Text = NO_TEXT
    title: Text = NO_TEXT
    birth_date: date | None = None
    show_age: bool = False


@dataclass(frozen=True)
class StoredPhoto:
    """The photo of the CV, stored under the files root (decision D2, Q7)."""

    path: str
    sha256: str


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
class Hobby:
    label: Text
    in_cv: bool = True


@dataclass(frozen=True)
class SkillGroup:
    """A group of technical skills of the CV (« Langages et Data »), holding its skills in CV order (Q9)."""

    name: Text
    skill_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CvLayout:
    """Choice and order of the master CV (decision D2, Q9, Q10): what is not listed stays out of the CV.

    Technical skills appear through their group; soft and business skills in ``transversal``; experiences and
    education are always shown, by date.
    """

    groups: tuple[SkillGroup, ...] = ()
    transversal: tuple[int, ...] = ()
    projects: tuple[int, ...] = ()
    hobbies: tuple[Hobby, ...] = ()


@dataclass(frozen=True)
class CvTemplateRecord:
    """A CV template of the profile: an immutable bundle of the files root (decision D2, Q24)."""

    id: int
    path: str
    sha256: str
    name: str
    active: bool
    created_at: datetime


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
    photo: StoredPhoto | None = None
    cv: CvLayout = CvLayout()

    def skill(self, skill_id: int) -> Skill | None:
        return next((s for s in self.skills if s.id == skill_id), None)

    def track(self, track_id: int) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)


class TrackInUseError(Exception):
    """An offer is linked to the track: it can be archived, never deleted (decision B5, Q21)."""


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

    def save_photo(
        self, profile_id: int, photo: StoredPhoto | None, now: datetime
    ) -> None: ...

    def save_cv_layout(self, profile_id: int, layout: CvLayout) -> None:
        """Replace the whole layout; the caller has checked it against the profile."""
        ...

    def add_cv_template(
        self, profile_id: int, path: str, sha256: str, name: str, now: datetime
    ) -> tuple[int, bool]:
        """The template's id, and whether it is new (the same bundle is recorded once)."""
        ...

    def cv_templates(self, profile_id: int) -> tuple[CvTemplateRecord, ...]:
        """Newest first."""
        ...

    def activate_cv_template(self, profile_id: int, template_id: int | None) -> bool:
        """Only ``template_id`` active (None: the neutral template); False when it is not of this profile."""
        ...

    def mark_onboarding_completed(self, profile_id: int, now: datetime) -> None: ...

    def mark_onboarding_deferred(self, profile_id: int, now: datetime) -> None: ...

    def add_track(self, profile_id: int, track: TrackDraft, now: datetime) -> int: ...

    def update_track(
        self, profile_id: int, track_id: int, track: TrackDraft, now: datetime
    ) -> bool: ...

    def set_track_status(
        self, profile_id: int, track_id: int, status: TrackStatus, now: datetime
    ) -> bool: ...

    def delete_track(self, profile_id: int, track_id: int) -> bool:
        """Raises ``TrackInUseError`` when an offer is linked to the track (the database refuses, step C6)."""
        ...

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
    cv: ImportedCv | None = None


@dataclass(frozen=True)
class ImportedSkillGroup:
    name: Text
    skills: tuple[str, ...] = ()  # names of technical skills of the file, in CV order


@dataclass(frozen=True)
class ImportedCv:
    """The master CV of an import file: skills and projects named, not yet identified."""

    groups: tuple[ImportedSkillGroup, ...] = ()
    transversal: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()  # French names of projects of the file
    hobbies: tuple[Hobby, ...] = ()
