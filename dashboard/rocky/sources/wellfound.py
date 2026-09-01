"""Connecteur des pages de rôles publiques Wellfound."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup

from ..errors import SourceError
from ..models import CandidateProfile, JobOffer
from .common import (
    BROWSER_HEADERS,
    deduplicate_offers,
    public_get,
    salary_values,
    unix_date,
    web_slug,
)


class WellfoundSource:
    """Adaptateur Wellfound qui lit les opportunités publiques pour la veille Rocky."""

    name = "Wellfound"
    base_url = "https://wellfound.com"

    @classmethod
    def _curl_html(cls, url: str) -> str:
        """Repli transport pour le CDN Wellfound qui refuse parfois requests.

        Il s'agit du même GET public, sans cookie, authentification, proxy ou
        résolution de CAPTCHA. L'appel utilise une liste d'arguments fixe et
        n'ouvre jamais de shell.
        """
        try:
            result = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--compressed",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "30",
                    "--user-agent",
                    BROWSER_HEADERS["User-Agent"],
                    "--referer",
                    f"{cls.base_url}/jobs",
                    url,
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=35,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SourceError(
                "Wellfound ne répond pas à la requête publique."
            ) from error
        if result.returncode != 0 or not result.stdout.strip():
            raise SourceError("Wellfound a refusé la requête publique.")
        return result.stdout

    @classmethod
    def _download_html(cls, url: str) -> str:
        """Essaie requests, puis le client HTTP système si le CDN le refuse."""
        try:
            return public_get(
                cls.name,
                url,
                headers={"Referer": f"{cls.base_url}/jobs"},
            ).text
        except SourceError:
            return cls._curl_html(url)

    @classmethod
    def _offer(cls, item: dict[str, Any], company_name: str) -> JobOffer:
        """Normalise une carte Wellfound avec son entreprise et ses liens de provenance."""
        external_id = str(item.get("id") or "")
        slug = str(item.get("slug") or "job")
        url = f"{cls.base_url}/jobs/{external_id}-{slug}"
        description = str(item.get("description") or "").strip()
        locations = item.get("locationNames") or []
        salary_min, salary_max, currency = salary_values(item.get("compensation"))
        remote = "Télétravail complet" if item.get("remote") else ""
        return JobOffer(
            external_id=external_id,
            source_name=cls.name,
            source_url=url,
            application_url=url,
            job_title=str(item.get("title") or "").strip(),
            company_name=company_name or "Non précisée",
            city=", ".join(str(location) for location in locations),
            country="",
            remote_policy=remote,
            contract_type=str(item.get("contractType") or ""),
            work_schedule=str(item.get("jobType") or ""),
            minimum_experience_years=item.get("yearsExperienceMin"),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            short_description=description[:600],
            description_is_full=bool(description),
            responsibilities=description,
            publication_date=unix_date(item.get("liveStartAt")),
        )

    @classmethod
    def parse_html(cls, html: str, limit: int) -> list[JobOffer]:
        """Lit le cache Apollo rendu côté serveur par la page publique."""
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            raise SourceError("Wellfound n'a pas fourni de données d'annonces.")
        try:
            payload = json.loads(script.string)
            apollo_state = payload["props"]["pageProps"]["apolloState"]
            state = apollo_state.get("data", apollo_state)
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise SourceError("Wellfound a renvoyé des données invalides.") from error

        root_query = state.get("ROOT_QUERY") or {}
        # Le cache Wellfound range actuellement les requêtes publiques sous
        # ``talent``. Le repli conserve la compatibilité avec l'ancien format.
        query_container = root_query.get("talent") or root_query
        search_result = next(
            (
                value
                for key, value in query_container.items()
                if key.startswith("seoLandingPageJobSearchResults(")
                and isinstance(value, dict)
            ),
            {},
        )
        offers: list[JobOffer] = []
        for startup_ref in search_result.get("startups", []):
            startup = state.get(str(startup_ref.get("__ref") or ""), {})
            company_name = str(startup.get("name") or "Non précisée")
            for job_ref in startup.get("highlightedJobListings", []):
                item = state.get(str(job_ref.get("__ref") or ""), {})
                if item.get("id") and item.get("title"):
                    offers.append(cls._offer(item, company_name))
                if len(offers) >= limit:
                    return offers
        return offers

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        """Recherche Wellfound selon le profil actif et renvoie les annonces à traiter."""
        queries: Iterable[str] = profile.target_job_titles or [profile.profile_name]
        collected: list[JobOffer] = []
        last_error: SourceError | None = None
        successful_query = False
        for query in queries:
            role_slug = web_slug(query)
            try:
                html = self._download_html(f"{self.base_url}/role/r/{role_slug}")
                collected.extend(self.parse_html(html, results_per_query))
                successful_query = True
            except SourceError as error:
                # Certains intitulés libres n'ont pas de page SEO Wellfound.
                # Les intitulés valides déjà récupérés restent exploitables.
                last_error = error
        if not successful_query and last_error is not None:
            raise last_error
        return deduplicate_offers(collected)
