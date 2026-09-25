"""Analysis of a posting: what it asks and offers, in the vocabulary of the profile, each fact with its evidence.

Decision ``docs/decisions/C3-analyse.md``. Every fact comes from deterministic rules (Q1); the language model only
summarises. Codes are English, labels French and shown only on screen. Nothing here is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from rocky.profil.model import Contract, LanguageLevel, RemoteMode

# Changes whenever a rule changes: kept with every analysis, as the scoring keeps its rules version (D14).
RULES_VERSION = "analyse-2026-09-25.2"


class Importance(StrEnum):
    """How a posting asks for something: required, welcome, or only mentioned."""

    ELIMINATORY = "eliminatory"
    PREFERRED = "preferred"
    DETECTED = "detected"


IMPORTANCE_LABELS = {
    Importance.ELIMINATORY: "Éliminatoire",
    Importance.PREFERRED: "Un plus",
    Importance.DETECTED: "Mentionnée",
}


class ConditionKind(StrEnum):
    """Conditions that nothing else makes up for (Q2)."""

    NATIONALITY = "nationality"
    CLEARANCE = "clearance"
    DRIVING_LICENCE = "driving_licence"


CONDITION_LABELS = {
    ConditionKind.NATIONALITY: "Nationalité ou droit au travail",
    ConditionKind.CLEARANCE: "Habilitation",
    ConditionKind.DRIVING_LICENCE: "Permis de conduire",
}


class SalaryPeriod(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"


SALARY_PERIOD_LABELS = {
    SalaryPeriod.HOURLY: "par heure",
    SalaryPeriod.DAILY: "par jour (TJM)",
    SalaryPeriod.MONTHLY: "par mois",
    SalaryPeriod.YEARLY: "par an",
}


@dataclass(frozen=True)
class SkillMatch:
    """A skill of the account named by the posting: the name found, and the sentence that decides its importance."""

    skill: str
    term: str
    importance: Importance
    evidence: str


@dataclass(frozen=True)
class Condition:
    kind: ConditionKind
    evidence: str


@dataclass(frozen=True)
class Salary:
    """The employer's figure. ``period_deduced``: no period is written, it comes from the amount (Q5)."""

    minimum: float
    maximum: float
    currency: str | None
    period: SalaryPeriod
    period_deduced: bool
    evidence: str | None = None


@dataclass(frozen=True)
class ExperienceNeed:
    years: int
    evidence: str


@dataclass(frozen=True)
class LanguageNeed:
    code: str
    level: LanguageLevel | None
    evidence: str


@dataclass(frozen=True)
class PostingAnalysis:
    rules_version: str
    description: str
    skills: tuple[SkillMatch, ...] = ()
    conditions: tuple[Condition, ...] = ()
    # Sentences that require something outside the account's skills ("Expérience impérative sur Informatica").
    requirements: tuple[str, ...] = ()
    contracts: tuple[Contract, ...] = ()
    remote: RemoteMode | None = None
    salary: Salary | None = None
    deadline: date | None = None
    experience: ExperienceNeed | None = None
    languages: tuple[LanguageNeed, ...] = ()

    def skills_of(self, importance: Importance) -> tuple[SkillMatch, ...]:
        return tuple(match for match in self.skills if match.importance == importance)


@dataclass(frozen=True)
class AccountSkill:
    """A skill of the account and every name it answers to in a posting (comparison forms, see ``normalize_term``)."""

    label: str
    terms: frozenset[str]
