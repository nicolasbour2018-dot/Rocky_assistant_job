"""Collecte des annonces Indeed via l'API officielle TheirStack."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dashboard.rocky.config import Settings
from dashboard.rocky.errors import ConfigurationError
from dashboard.rocky.job_importer import description_is_probably_truncated
from dashboard.rocky.models import CandidateProfile, JobOffer
from dashboard.rocky.text_utils import normalize_text
from dashboard.rocky.theirstack import TheirStackClient

from .common import deduplicate_offers

INDEED_DOMAIN = "indeed.com"


def _date_value(value: Any) -> date | None:
    """Convertit la date Indeed/TheirStack au format métier sans supposer de fuseau."""
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _company_name(item: dict[str, Any]) -> str:
    """Extrait le nom employeur le plus fiable de la charge Indeed."""
    company = item.get("company_object")
    if isinstance(company, dict) and company.get("name"):
        return str(company["name"]).strip()
    return str(
        item.get("company") or item.get("company_name") or "Non précisée"
    ).strip()


def _company_industry(item: dict[str, Any]) -> str:
    """Récupère le secteur employeur lorsqu'il est fourni par le collecteur."""
    company = item.get("company_object")
    if not isinstance(company, dict):
        return ""
    return str(company.get("industry") or "").strip()


def _indeed_url(item: dict[str, Any]) -> str:
    """Choisit l'URL Indeed officielle à conserver pour l'audit et la candidature."""
    for key in ("source_url", "url", "final_url"):
        value = str(item.get(key) or "").strip()
        if INDEED_DOMAIN in urlsplit(value).netloc.lower():
            return value
    return ""


def _external_id(item: dict[str, Any], source_url: str) -> str:
    """Construit l'identifiant externe stable utile à la déduplication des offres."""
    query = parse_qs(urlsplit(source_url).query)
    for key in ("jk", "vjk"):
        value = str(query.get(key, [""])[0]).strip()
        if value:
            return value
    theirstack_id = str(item.get("id") or "").strip()
    return f"theirstack:{theirstack_id}" if theirstack_id else source_url


def _remote_policy(item: dict[str, Any]) -> str:
    """Normalise l'indication télétravail fournie par Indeed/TheirStack."""
    workplace_types = {
        normalize_text(value) for value in item.get("workplace_types", [])
    }
    if bool(item.get("hybrid")) or "hybrid" in workplace_types:
        return "Hybride"
    if bool(item.get("remote")) or "remote" in workplace_types:
        return "Télétravail complet"
    if "on site" in workplace_types or "on_site" in workplace_types:
        return "Sur site"
    return ""


def _filter_values(values: list[str], mapping: dict[str, tuple[str, ...]]) -> list[str]:
    """Prépare les filtres d'intitulés pour l'API sans transmettre de valeurs vides."""
    selected: list[str] = []
    for value in values:
        normalized = normalize_text(value).replace("_", " ")
        for marker, mapped_values in mapping.items():
            if marker in normalized:
                for mapped in mapped_values:
                    if mapped not in selected:
                        selected.append(mapped)
    return selected


class IndeedSource:
    """Source Indeed via TheirStack, sans scraping direct ni contournement de portail."""

    """Source fonctionnelle Indeed, collectée techniquement par TheirStack."""

    name = "Indeed"
    collector_name = "TheirStack"

    def __init__(
        self,
        settings: Settings,
        client: TheirStackClient | None = None,
    ):
        """Injecte le client TheirStack et la limite de fraîcheur appliquée aux résultats."""
        self.settings = settings
        self.client = client or TheirStackClient(settings.theirstack_api_key)

    @staticmethod
    def _offer(item: dict[str, Any]) -> JobOffer | None:
        """Convertit un résultat Indeed enrichi, ou l'écarte si son identité est incomplète."""
        source_url = _indeed_url(item)
        if not source_url:
            return None
        description = str(item.get("description") or "").strip()
        application_url = str(
            item.get("final_url") or item.get("url") or source_url
        ).strip()
        employment = [
            str(value)
            for value in item.get("employment_statuses", [])
            if str(value).strip()
        ]
        technologies = [
            str(value).replace("-", " ").strip()
            for value in item.get("technology_slugs", [])
            if str(value).strip()
        ]
        description_is_full = bool(description) and not (
            description_is_probably_truncated(description)
        )
        return JobOffer(
            external_id=_external_id(item, source_url),
            source_name="Indeed",
            collector_name="TheirStack",
            source_url=source_url,
            application_url=application_url,
            job_title=str(item.get("job_title") or "").strip(),
            company_name=_company_name(item),
            city=str(
                item.get("short_location")
                or item.get("location")
                or item.get("long_location")
                or ""
            ).strip(),
            country=str(item.get("country") or "France").strip(),
            remote_policy=_remote_policy(item),
            contract_type=" ".join(employment),
            work_schedule=" ".join(employment),
            experience_level=str(item.get("seniority") or "").strip(),
            salary_min=item.get("min_annual_salary"),
            salary_max=item.get("max_annual_salary"),
            salary_currency=str(item.get("salary_currency") or "EUR"),
            short_description=description[:500],
            responsibilities=description,
            description_is_full=description_is_full,
            main_domain=_company_industry(item),
            publication_date=_date_value(item.get("date_posted")),
            detected_skills=technologies,
        )

    def _payload(
        self,
        profile: CandidateProfile,
        results_per_query: int,
        location_ids: list[int],
    ) -> dict[str, Any]:
        """Construit la requête TheirStack correspondant aux postes et zones du profil."""
        titles = profile.target_job_titles or [profile.profile_name]
        payload: dict[str, Any] = {
            "job_title_or": titles,
            "job_country_code_or": ["FR"],
            "url_domain_or": [INDEED_DOMAIN],
            "posted_at_max_age_days": (self.settings.theirstack_indeed_max_age_days),
            "is_closed": False,
            "limit": max(1, int(results_per_query)),
            "offset": 0,
        }
        if location_ids:
            payload["job_location_or"] = [
                {"id": location_id} for location_id in location_ids
            ]
        employment = _filter_values(
            profile.preferred_contracts,
            {
                "cdi": ("full_time",),
                "permanent": ("full_time",),
                "cdd": ("temporary", "contract"),
                "temporaire": ("temporary",),
                "stage": ("internship",),
                "internship": ("internship",),
                "apprentissage": ("apprenticeship",),
                "temps partiel": ("part_time",),
                "part time": ("part_time",),
            },
        )
        if employment:
            payload["employment_statuses_or"] = employment
        workplaces = _filter_values(
            profile.remote_preferences,
            {
                "hybride": ("hybrid",),
                "hybrid": ("hybrid",),
                "teletravail": ("remote",),
                "remote": ("remote",),
                "sur site": ("on_site",),
                "presentiel": ("on_site",),
            },
        )
        if workplaces:
            payload["workplace_types_or"] = workplaces
        return payload

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        """Collecte les annonces Indeed récentes via TheirStack pour le cycle de veille."""
        if not self.settings.theirstack_api_key:
            raise ConfigurationError(
                "TheirStack est requis pour collecter les annonces Indeed."
            )
        precise_locations = [
            location
            for location in profile.preferred_locations
            if normalize_text(location) not in {"france", "fr"}
        ]
        location_ids = self.client.resolve_location_ids(
            precise_locations, country_code="FR"
        )
        items = self.client.search_jobs(
            self._payload(profile, results_per_query, location_ids)
        )
        offers = [self._offer(item) for item in items]
        return deduplicate_offers([offer for offer in offers if offer is not None])
