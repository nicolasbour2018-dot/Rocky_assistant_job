"""Score of a posting for one account: one score per (posting, track), each component with its detail and evidence.

Decision ``docs/decisions/C4-scoring.md``. Every value below is a rule parameter, calibrated in C5: changing one
changes ``RULES_VERSION``, kept with every score (D14). Codes are English; French labels are shown only on screen.
Nothing here is persisted (the score is stored with the offer in C6, in the form of ``Score.to_json``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from rocky.offres.analysis.model import Importance
from rocky.profil.model import LanguageLevel, Preferences, SkillLevel

RULES_VERSION = "score-2026-09-25.1"


class ComponentCode(StrEnum):
    SKILLS = "skills"
    TITLE = "title"
    CONTRACT = "contract"
    LOCATION = "location"
    REMOTE = "remote"
    SALARY = "salary"
    EXPERIENCE = "experience"
    LANGUAGES = "languages"


COMPONENT_LABELS = {
    ComponentCode.SKILLS: "Compétences",
    ComponentCode.TITLE: "Intitulé",
    ComponentCode.CONTRACT: "Contrat",
    ComponentCode.LOCATION: "Lieu",
    ComponentCode.REMOTE: "Télétravail",
    ComponentCode.SALARY: "Salaire",
    ComponentCode.EXPERIENCE: "Expérience",
    ComponentCode.LANGUAGES: "Langues",
}

# Weights (Q16). Skills and title always count, even at 0 (Q17); an optional component without information is left
# out and the others are renormalised.
WEIGHTS = {
    ComponentCode.SKILLS: 40.0,
    ComponentCode.TITLE: 25.0,
    ComponentCode.CONTRACT: 10.0,
    ComponentCode.LOCATION: 10.0,
    ComponentCode.REMOTE: 5.0,
    ComponentCode.SALARY: 5.0,
    ComponentCode.EXPERIENCE: 3.0,
    ComponentCode.LANGUAGES: 2.0,
}
OPTIONAL_COMPONENTS = (
    ComponentCode.CONTRACT,
    ComponentCode.LOCATION,
    ComponentCode.REMOTE,
    ComponentCode.SALARY,
    ComponentCode.EXPERIENCE,
    ComponentCode.LANGUAGES,
)

# Skills: evidence points (Q2, Q3, Q26).
IMPORTANCE_POINTS = {
    Importance.ELIMINATORY: 1.0,
    Importance.PREFERRED: 0.6,
    Importance.DETECTED: 0.3,
}
KEY_SKILL_FACTOR = 1.5
UNPROVEN_SKILL_FACTOR = 0.7
FULL_EVIDENCE = 4.0
REQUIREMENT_PENALTY = 1.0

# Title (Q4): the track title as written scores 1, all its words apart score this, some of its words this share.
SCATTERED_TITLE = 0.5
PARTIAL_TITLE_FACTOR = 0.5

# Location (Q9, Q15).
IN_ZONE = 1.0
OUT_OF_ZONE = 0.3
OUT_OF_ZONE_HYBRID = 0.5
ABROAD = 0.0
ABROAD_FULL_REMOTE = 0.5
FRANCE_NAMES = frozenset({"france", "fr", "fra"})

# Salary (Q8): a period deduced from the amount weighs this share of the weight.
DEDUCED_PERIOD_FACTOR = 0.5
EURO = "EUR"

# Languages (Q23): a language of the profile at a lower level than asked.
LOWER_LANGUAGE_LEVEL = 0.5

# Caps and threshold (Q5, Q6, Q14, Q18).
CAP = 30.0
THRESHOLD = 50

# Confidence (Q25).
LOW_EVIDENCE = 2.0
MANY_ABSENT = 3


class CapKind(StrEnum):
    EXCLUDED_WORD = "excluded_word"
    CONDITION = "condition"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CONFIDENCE_LABELS = {
    ConfidenceLevel.HIGH: "Confiance haute",
    ConfidenceLevel.MEDIUM: "Confiance moyenne",
    ConfidenceLevel.LOW: "Confiance faible",
}


# What the score reads of the profile.


@dataclass(frozen=True)
class ProfileSkill:
    """A skill of the profile, by its French label (the name the posting analysis gives, ``SkillMatch.skill``)."""

    label: str
    is_key: bool = False
    proven: bool = False
    level: SkillLevel | None = None


@dataclass(frozen=True)
class ScoringTrack:
    id: int
    name: str
    titles: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Job:
    """A job of the profile (never a training), with the labels of the skills it is linked to."""

    start: date
    end: date | None
    skills: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ScoringProfile:
    """The part of a profile the score reads; only active tracks."""

    skills: tuple[ProfileSkill, ...] = ()
    tracks: tuple[ScoringTrack, ...] = ()
    preferences: Preferences = field(default_factory=Preferences)
    languages: tuple[tuple[str, LanguageLevel], ...] = ()
    jobs: tuple[Job, ...] = ()


# The score.


@dataclass(frozen=True)
class Component:
    """One component. ``value`` in [0, 1], or None when it is left out (no information, or ``neutral``: full remote
    work makes the place irrelevant). ``weight`` is the weight actually used (a deduced salary period halves it)."""

    code: ComponentCode
    value: float | None
    weight: float
    detail: str
    evidence: tuple[str, ...] = ()
    neutral: bool = False

    @property
    def counted(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Cap:
    kind: CapKind
    label: str
    evidence: str | None = None


@dataclass(frozen=True)
class Confidence:
    level: ConfidenceLevel
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackScore:
    """The score of the posting for one track (``track_id`` None: the account has no active track, Q20).

    ``features`` are the facts behind the score, kept as training data (D14): JSON values only.
    """

    track_id: int | None
    track_name: str | None
    value: float
    uncapped: float
    components: tuple[Component, ...]
    confidence: Confidence
    caps: tuple[Cap, ...] = ()
    gaps: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    features: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> int:
        """Whole number shown on screen (Q21): the rules are not precise to the decimal."""
        return math.floor(self.value + 0.5)

    def component(self, code: ComponentCode) -> Component:
        return next(item for item in self.components if item.code == code)


@dataclass(frozen=True)
class Score:
    """The scores of one posting for every active track of the account; the best one is the score of the posting."""

    rules_version: str
    analysis_rules_version: str
    tracks: tuple[TrackScore, ...]

    @property
    def best(self) -> TrackScore:
        # The first of the best: tracks keep the order of the profile.
        return max(self.tracks, key=lambda track: track.value)

    @property
    def below_threshold(self) -> bool:
        return self.best.display < THRESHOLD

    @property
    def threshold_reason(self) -> str | None:
        """The reason an offer is kept under the threshold (C6), or None."""
        if not self.below_threshold:
            return None
        return f"Score sous le seuil ({self.best.display} < {THRESHOLD})"

    def to_json(self) -> dict[str, Any]:
        """The stored form (C6): JSON values only, read back by ``from_json``."""
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Score:
        return cls(
            rules_version=data["rules_version"],
            analysis_rules_version=data["analysis_rules_version"],
            tracks=tuple(_track_score(item) for item in data["tracks"]),
        )


def _track_score(data: dict[str, Any]) -> TrackScore:
    return TrackScore(
        track_id=data["track_id"],
        track_name=data["track_name"],
        value=data["value"],
        uncapped=data["uncapped"],
        components=tuple(
            Component(
                code=ComponentCode(item["code"]),
                value=item["value"],
                weight=item["weight"],
                detail=item["detail"],
                evidence=tuple(item["evidence"]),
                neutral=item["neutral"],
            )
            for item in data["components"]
        ),
        confidence=Confidence(
            ConfidenceLevel(data["confidence"]["level"]),
            tuple(data["confidence"]["reasons"]),
        ),
        caps=tuple(
            Cap(CapKind(item["kind"]), item["label"], item["evidence"])
            for item in data["caps"]
        ),
        gaps=tuple(data["gaps"]),
        notes=tuple(data["notes"]),
        features=data["features"],
    )
