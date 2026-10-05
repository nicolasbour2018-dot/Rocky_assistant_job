"""Connecteur des cartes d'emploi publiques LinkedIn.

LinkedIn ne fournit pas ici d'API privée ni de session utilisateur. Rocky lit
uniquement la liste publique destinée aux visiteurs non connectés. Si cet
accès est désactivé par LinkedIn, la source passe en erreur isolée.
"""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

from ..models import CandidateProfile, JobOffer
from .common import deduplicate_offers, iso_date, public_get


class LinkedInSource:
    """Source HTML LinkedIn de lecture seule, sans action sur le portail tiers."""
    name = "LinkedIn"
    search_url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/"
        "seeMoreJobPostings/search"
    )

    @classmethod
    def parse_html(cls, html: str, limit: int) -> list[JobOffer]:
        """Convertit les cartes publiques, sans dépendre de leur CSS visuel."""
        soup = BeautifulSoup(html, "html.parser")
        offers: list[JobOffer] = []
        for card in soup.select("div.base-search-card"):
            link = card.select_one("a.base-card__full-link")
            title = card.select_one(".base-search-card__title")
            company = card.select_one(".base-search-card__subtitle")
            location = card.select_one(".job-search-card__location")
            published = card.select_one("time[datetime]")
            if not link or not title:
                continue
            url = str(link.get("href") or "").split("?", 1)[0]
            urn = str(card.get("data-entity-urn") or "")
            external_id = urn.rsplit(":", 1)[-1]
            if not external_id:
                match = re.search(r"-(\d+)$", url)
                external_id = match.group(1) if match else url
            title_text = title.get_text(" ", strip=True)
            company_text = (
                company.get_text(" ", strip=True)
                if company
                else "Non précisée"
            )
            city = location.get_text(" ", strip=True) if location else ""
            context = f"{title_text}. {company_text}. {city}."
            offers.append(
                JobOffer(
                    external_id=external_id,
                    source_name=cls.name,
                    source_url=url,
                    application_url=url,
                    job_title=title_text,
                    company_name=company_text,
                    city=city,
                    country="France" if "France" in city else "",
                    short_description=context,
                    responsibilities=context,
                    publication_date=iso_date(
                        published.get("datetime") if published else None
                    ),
                )
            )
            if len(offers) >= limit:
                break
        return offers

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        """Construit les recherches LinkedIn du profil et retourne les offres collectées."""
        queries: Iterable[str] = profile.target_job_titles or [profile.profile_name]
        location = profile.preferred_locations[0] if profile.preferred_locations else "France"
        collected: list[JobOffer] = []
        for query in queries:
            response = public_get(
                self.name,
                self.search_url,
                params={
                    "keywords": query,
                    "location": location,
                    "f_TPR": "r2592000",
                    "sortBy": "DD",
                    "start": 0,
                },
                headers={"Referer": "https://www.linkedin.com/jobs/search/"},
            )
            collected.extend(self.parse_html(response.text, results_per_query))
        return deduplicate_offers(collected)
