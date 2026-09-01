"""Connecteur de recherche Adzuna."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..config import Settings
from ..errors import ConfigurationError, SourceError
from ..models import CandidateProfile, JobOffer


class AdzunaSource:
    """Adaptateur Adzuna qui convertit les résultats API en annonces Rocky auditables."""
    name = "Adzuna"
    base_url = "https://api.adzuna.com/v1/api/jobs"

    def __init__(self, settings: Settings):
        """Retient la configuration API nécessaire aux recherches du profil."""
        self.settings = settings

    @staticmethod
    def _offer(item: dict[str, Any]) -> JobOffer:
        """Traduit une réponse Adzuna en modèle métier homogène."""
        location = item.get("location") or {}
        company = item.get("company") or {}
        category = item.get("category") or {}
        created = item.get("created")
        publication_date = None
        if created:
            try:
                publication_date = datetime.fromisoformat(
                    str(created).replace("Z", "+00:00")
                ).date()
            except ValueError:
                publication_date = None
        return JobOffer(
            external_id=str(item.get("id") or ""),
            source_name="Adzuna",
            source_url=str(item.get("redirect_url") or ""),
            application_url=str(item.get("redirect_url") or ""),
            job_title=str(item.get("title") or "").strip(),
            company_name=str(company.get("display_name") or "Non précisée").strip(),
            city=str(location.get("display_name") or "").strip(),
            country="France",
            contract_type=str(item.get("contract_type") or ""),
            work_schedule=str(item.get("contract_time") or ""),
            salary_min=item.get("salary_min"),
            salary_max=item.get("salary_max"),
            salary_currency="EUR",
            short_description=str(item.get("description") or "").strip(),
            responsibilities=str(item.get("description") or "").strip(),
            main_domain=str(category.get("label") or "").strip(),
            publication_date=publication_date,
        )

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        """Interroge Adzuna pour les intitulés du profil sans persister directement les résultats."""
        if not self.settings.adzuna_app_id or not self.settings.adzuna_app_key:
            raise ConfigurationError("Les credentials Adzuna sont absents.")
        queries = profile.target_job_titles or [profile.profile_name]
        location = profile.preferred_locations[0] if profile.preferred_locations else ""
        collected: list[JobOffer] = []
        for query in queries:
            params = {
                "app_id": self.settings.adzuna_app_id,
                "app_key": self.settings.adzuna_app_key,
                "results_per_page": results_per_query,
                "what": query,
                "where": location,
                "sort_by": "date",
                "content-type": "application/json",
            }
            try:
                response = requests.get(
                    f"{self.base_url}/{self.settings.adzuna_country}/search/1",
                    params=params,
                    headers={"Accept": "application/json"},
                    timeout=20,
                )
                response.raise_for_status()
                items = response.json().get("results", [])
            except requests.HTTPError as error:
                status = (
                    error.response.status_code
                    if error.response is not None
                    else "inconnu"
                )
                raise SourceError(
                    f"Adzuna a refusé la requête (HTTP {status})."
                ) from error
            except (requests.RequestException, ValueError) as error:
                raise SourceError(
                    "Adzuna ne répond pas ou sa réponse est invalide."
                ) from error
            collected.extend(self._offer(item) for item in items)
        return collected
