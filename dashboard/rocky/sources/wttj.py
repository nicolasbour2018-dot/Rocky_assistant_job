"""Connecteur de l'endpoint public Welcome to the Jungle."""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from ..errors import SourceError
from ..models import CandidateProfile, JobOffer
from .common import deduplicate_offers, iso_date, public_get


class WelcomeToTheJungleSource:
    name = "Welcome to the Jungle"
    search_url = "https://api.welcometothejungle.com/api/v3/public/jobs"
    website_url = "https://www.welcometothejungle.com"

    @classmethod
    def _offer(cls, item: dict[str, Any]) -> JobOffer:
        organization = item.get("organization") or {}
        office = item.get("office") or {}
        organization_slug = str(organization.get("slug") or "")
        job_slug = str(item.get("slug") or item.get("reference") or "")
        url = f"{cls.website_url}/fr/companies/{organization_slug}/jobs/{job_slug}"
        sectors = organization.get("sectors") or []
        domain = ", ".join(
            str(sector.get("name") or "")
            for sector in sectors
            if sector.get("name")
        )
        summary = str(item.get("company_summary") or "").strip()
        context = ". ".join(
            value
            for value in (
                str(item.get("name") or "").strip(),
                summary,
                domain,
            )
            if value
        )
        return JobOffer(
            external_id=str(item.get("reference") or job_slug),
            source_name=cls.name,
            source_url=url,
            application_url=url,
            job_title=str(item.get("name") or "").strip(),
            company_name=str(organization.get("name") or "Non précisée").strip(),
            city=str(office.get("city") or "").strip(),
            country=str(office.get("country_code") or ""),
            remote_policy=str(item.get("remote") or ""),
            contract_type=str(
                item.get("contract_kind")
                or item.get("employment_type")
                or item.get("contract_type")
                or ""
            ),
            work_schedule=str(
                item.get("work_schedule")
                or item.get("contract_time")
                or item.get("contract_type")
                or ""
            ),
            minimum_experience_years=item.get("experience_min"),
            salary_min=item.get("salary_min"),
            salary_max=item.get("salary_max"),
            salary_currency=str(item.get("salary_currency") or "EUR"),
            short_description=context[:600],
            responsibilities=context,
            main_domain=domain,
            publication_date=iso_date(item.get("published_at")),
        )

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        queries: Iterable[str] = profile.target_job_titles or [profile.profile_name]
        collected: list[JobOffer] = []
        for query in queries:
            response = public_get(
                self.name,
                self.search_url,
                params={
                    "job_title": query,
                    "page": 1,
                    "query_id": str(uuid.uuid4()),
                },
                headers={
                    "Accept": "application/json",
                    "Origin": self.website_url,
                    "Referer": f"{self.website_url}/fr/jobs",
                    "wttj-user-language": "fr",
                },
            )
            try:
                items = response.json().get("data", [])
            except (ValueError, AttributeError) as error:
                raise SourceError(
                    "Welcome to the Jungle a renvoyé une réponse invalide."
                ) from error
            collected.extend(
                self._offer(item) for item in items[:results_per_query]
            )
        return deduplicate_offers(collected)
