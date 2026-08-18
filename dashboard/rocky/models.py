"""Objets métier simples échangés entre les modules de Rocky."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass
class JobOffer:
    """Annonce normalisée, quelle que soit sa source."""

    job_title: str
    company_name: str
    responsibilities: str
    source_name: str = "URL"
    collector_name: str = ""
    source_url: str = ""
    application_url: str = ""
    external_id: str = ""
    city: str = ""
    country: str = "France"
    remote_policy: str = ""
    contract_type: str = ""
    work_schedule: str = ""
    experience_level: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "EUR"
    short_description: str = ""
    description_is_full: bool = False
    description_enrichment_source: str = ""
    description_enrichment_external_id: str = ""
    required_education: str = ""
    minimum_experience_years: float | None = None
    main_domain: str = ""
    publication_date: date | str | None = None
    application_deadline: date | str | None = None
    status: str = "NOUVELLE"
    detected_skills: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Garantit que contrat et temps de travail ne sont jamais mélangés."""
        from .contracts import normalize_contract_details

        self.contract_type, self.work_schedule = normalize_contract_details(
            self.contract_type,
            self.work_schedule,
            self.responsibilities,
            self.short_description,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateProfile:
    """Préférences et informations utiles au matching."""

    id: int
    profile_name: str
    summary: str = ""
    target_job_titles: list[str] = field(default_factory=list)
    preferred_contracts: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    remote_preferences: list[str] = field(default_factory=list)
    minimum_salary: float | None = None
    cv_path: str = ""
    is_active: bool = False


@dataclass
class MatchResult:
    """Résultat auditable du calcul de correspondance."""

    score: float
    breakdown: dict[str, dict[str, Any]]
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    detected_job_skills: list[str] = field(default_factory=list)
