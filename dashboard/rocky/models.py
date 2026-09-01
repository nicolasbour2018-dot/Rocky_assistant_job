"""Objets métier simples échangés entre les modules de Rocky."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

Locale = Literal["fr", "en"]
DocumentKind = Literal["cv", "letter"]


@dataclass(frozen=True)
class AuthenticatedUser:
    """Compte vérifié autorisé à ouvrir un espace personnel Rocky."""

    id: int
    email: str
    status: str = "ACTIVE"
    email_verified_at: datetime | None = None


@dataclass(frozen=True)
class ProfileLocalization:
    """Texte métier d'un profil dans une langue d'affichage et de matching."""

    profile_id: int
    locale: Locale
    summary: str = ""
    target_job_titles: tuple[str, ...] = ()
    target_domains: tuple[str, ...] = ()
    translation_status: str = "ready"
    source_hash: str = ""


@dataclass(frozen=True)
class ProfileDocument:
    """Document privé versionné d'un profil et son aperçu éventuel."""

    id: int
    profile_id: int
    locale: Locale
    kind: DocumentKind
    source_path: str
    preview_pdf_path: str = ""
    origin: str = "uploaded"
    status: str = "ready"
    sha256: str = ""
    source_hash: str = ""
    version: int = 1
    is_current: bool = True


@dataclass(frozen=True)
class ProfileAnalysis:
    """Préremplissage prudent extrait des documents fournis par l'utilisateur."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    target_job_titles: tuple[str, ...] = ()
    target_domains: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    skill_levels: tuple[tuple[str, str], ...] = ()
    career_items: tuple[str, ...] = ()
    project_evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


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
    detected_language: str = ""
    language_confidence: float | None = None
    language_override: str = ""

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
        """Sérialise l'offre pour les services d'analyse sans modifier son contenu."""
        return asdict(self)


@dataclass
class CandidateProfile:
    """Préférences et informations utiles au matching."""

    id: int
    profile_name: str
    user_id: int | None = None
    summary: str = ""
    target_job_titles: list[str] = field(default_factory=list)
    preferred_contracts: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    remote_preferences: list[str] = field(default_factory=list)
    minimum_salary: float | None = None
    cv_path: str = ""
    is_active: bool = False
    full_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    postal_code: str = ""
    home_city: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    target_domains: list[str] = field(default_factory=list)
    locale: Locale = "fr"
    onboarding_status: str = "COMPLETE"


@dataclass(frozen=True)
class CandidateIdentity:
    """Coordonnées explicitement autorisées pour un préremplissage."""

    full_name: str
    email: str
    phone: str
    address: str = ""
    postal_code: str = ""
    city: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""


@dataclass(frozen=True)
class ProfileProject:
    """Projet validé pouvant alimenter l'un des trois cadres du CV."""

    slug: str
    name: str
    problem: str
    stack: tuple[str, ...] = ()
    deliverable: str = ""
    details: str = ""
    skills: tuple[str, ...] = ()
    results: str = ""
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class TailoredProject:
    """Texte borné destiné à un cadre projet du CV Canva."""

    slug: str
    title: str
    problem: str
    stack: str
    deliverable: str


@dataclass(frozen=True)
class TailoredCvPlan:
    """Contenu autorisé à remplacer dans le PDF source immuable."""

    technical_groups: tuple[tuple[str, tuple[str, ...]], ...]
    transversal_skills: tuple[str, ...]
    projects: tuple[TailoredProject, ...]


@dataclass(frozen=True)
class ApplicationPackage:
    """Les deux PDF courants créés pour une candidature."""

    directory: str
    cv_pdf_path: str
    letter_pdf_path: str
    application_id: int | None = None
    locale: Locale = "fr"


@dataclass(frozen=True)
class EmailDecision:
    """Décision auditable issue d'un e-mail lu sans modifier Gmail."""

    classification: str
    confidence: float
    proposed_status: str | None
    reason: str


@dataclass(frozen=True)
class BrowserPrefillReport:
    """Bilan local d'un préremplissage, sans soumission finale."""

    application_id: int
    target_url: str
    status: str
    filled_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    started_at: datetime | None = None


@dataclass(frozen=True)
class ProposedAction:
    """Action Rocky lisible et confirmable avant toute écriture."""

    action: str
    summary: str
    entity_id: int | None = None
    value: str | None = None
    field: str | None = None
    requires_confirmation: bool = False


@dataclass
class MatchResult:
    """Résultat auditable du calcul de correspondance.

    ``scoring_version`` permet de comparer les résultats produits par des
    règles de matching différentes dans l'historique persistant.
    """

    score: float
    breakdown: dict[str, dict[str, Any]]
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    detected_job_skills: list[str] = field(default_factory=list)
    profile_locale: Locale = "fr"
    scoring_version: str = "matching-v1"
