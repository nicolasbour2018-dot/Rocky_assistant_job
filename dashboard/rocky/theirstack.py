"""Accès partagé à TheirStack pour la collecte et le réenrichissement."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

import requests

from .errors import ConfigurationError, SourceError
from .job_importer import (
    DescriptionHydration,
    description_is_probably_truncated,
)
from .models import JobOffer
from .text_utils import canonical_url, normalize_text


THEIRSTACK_JOB_SEARCH_URL = "https://api.theirstack.com/v1/jobs/search"
THEIRSTACK_LOCATION_CATALOG_URL = "https://api.theirstack.com/v0/catalog/locations"
THEIRSTACK_RESULT_LIMIT = 3


def _identity_text(value: Any) -> str:
    """Normalise une identité d'offre ou d'employeur pour les rapprochements de connecteur."""
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value)).strip()


def _similarity(left: Any, right: Any) -> float:
    """Mesure une proximité textuelle utilisée uniquement pour désambiguïser un enrichissement."""
    normalized_left = _identity_text(left)
    normalized_right = _identity_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _date_value(value: Any) -> date | None:
    """Convertit une date TheirStack hétérogène sans créer de date de publication fictive."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _job_company(item: dict[str, Any]) -> str:
    """Extrait le nom employeur le plus stable d'une réponse TheirStack."""
    company_object = item.get("company_object")
    if isinstance(company_object, dict):
        company_name = company_object.get("name")
        if company_name:
            return str(company_name)
    return str(item.get("company") or item.get("company_name") or "")


def _job_urls(item: dict[str, Any]) -> set[str]:
    """Collecte les URLs candidates pour vérifier l'identité d'une annonce enrichie."""
    urls = set()
    for key in ("url", "source_url", "final_url"):
        value = str(item.get(key) or "").strip()
        if value:
            urls.add(canonical_url(value))
    return urls


def _identity_score(offer: JobOffer, item: dict[str, Any]) -> float:
    """Score prudent fondé sur titre, entreprise et corroborateurs stables."""
    title_score = _similarity(offer.job_title, item.get("job_title"))
    company_score = _similarity(offer.company_name, _job_company(item))
    if title_score < 0.78 or company_score < 0.80:
        return 0.0

    score = 0.55 * title_score + 0.35 * company_score
    rocky_urls = {
        canonical_url(url)
        for url in (offer.source_url, offer.application_url)
        if url.strip()
    }
    url_matches = bool(rocky_urls & _job_urls(item))
    corroborated = url_matches
    if url_matches:
        score += 0.20

    rocky_date = _date_value(offer.publication_date)
    theirstack_date = _date_value(item.get("date_posted"))
    if rocky_date and theirstack_date:
        distance = abs((rocky_date - theirstack_date).days)
        if distance <= 14:
            score += 0.05
            corroborated = True
        elif distance > 45:
            if not url_matches:
                return 0.0
            score -= 0.15

    city = _identity_text(offer.city)
    location = _identity_text(
        item.get("location") or item.get("short_location") or item.get("long_location")
    )
    if city and location and city in location:
        score += 0.05
        corroborated = True
    return score if corroborated else 0.0


class TheirStackClient:
    """Client HTTP borné pour recherche Indeed et enrichissement descriptif via TheirStack."""

    """Client HTTP commun, sans logique métier propre à une source Rocky."""

    def __init__(self, api_key: str, timeout: int = 20):
        """Configure le client sans lancer d'appel réseau ni exposer la clé API."""
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._location_cache: dict[tuple[str, str], int | None] = {}

    def _headers(self) -> dict[str, str]:
        """Prépare les en-têtes d'authentification nécessaires aux appels TheirStack."""
        if not self.api_key:
            raise ConfigurationError("TheirStack n’est pas configuré.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _request_error(error: requests.RequestException) -> SourceError:
        """Convertit une erreur HTTP en incident de source sûr à afficher dans Monitoring."""
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status == 402:
            detail = "quota ou crédits insuffisants"
        elif status == 429:
            detail = "limite de débit atteinte"
        elif status:
            detail = f"HTTP {status}"
        else:
            detail = "service indisponible ou délai dépassé"
        return SourceError(f"TheirStack n’a pas pu répondre ({detail}).")

    def search_jobs(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Exécute une recherche officielle et valide sa structure minimale."""
        try:
            response = requests.post(
                THEIRSTACK_JOB_SEARCH_URL,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            decoded = response.json()
        except requests.RequestException as error:
            raise self._request_error(error) from error
        except ValueError as error:
            raise SourceError("TheirStack a renvoyé une réponse illisible.") from error

        if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
            raise SourceError("TheirStack a renvoyé une réponse invalide.")
        return [item for item in decoded["data"] if isinstance(item, dict)]

    def resolve_location_ids(
        self,
        locations: list[str],
        country_code: str = "FR",
    ) -> list[int]:
        """Résout les libellés Rocky via le catalogue géographique officiel."""
        resolved: list[int] = []
        for location in dict.fromkeys(
            value.strip() for value in locations if value.strip()
        ):
            cache_key = (normalize_text(location), country_code.upper())
            if cache_key not in self._location_cache:
                try:
                    response = requests.get(
                        THEIRSTACK_LOCATION_CATALOG_URL,
                        headers=self._headers(),
                        params={
                            "name": location,
                            "country_code": country_code.upper(),
                            "limit": 5,
                        },
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    decoded = response.json()
                except requests.RequestException as error:
                    raise self._request_error(error) from error
                except ValueError as error:
                    raise SourceError(
                        "TheirStack a renvoyé un catalogue de lieux illisible."
                    ) from error
                candidates = (
                    decoded.get("data", []) if isinstance(decoded, dict) else decoded
                )
                if not isinstance(candidates, list):
                    raise SourceError(
                        "TheirStack a renvoyé un catalogue de lieux invalide."
                    )
                expected = normalize_text(location)
                valid = [
                    item
                    for item in candidates
                    if isinstance(item, dict) and item.get("id") is not None
                ]
                exact = next(
                    (
                        item
                        for item in valid
                        if expected
                        in {
                            normalize_text(item.get("name")),
                            normalize_text(item.get("display_name")),
                        }
                    ),
                    None,
                )
                selected = exact or (valid[0] if valid else None)
                try:
                    location_id = int(selected["id"]) if selected else None
                except (TypeError, ValueError):
                    location_id = None
                self._location_cache[cache_key] = location_id
            location_id = self._location_cache[cache_key]
            if location_id is not None and location_id not in resolved:
                resolved.append(location_id)
        return resolved

    def search_candidates(self, offer: JobOffer) -> list[dict[str, Any]]:
        """Recherche des candidats d'enrichissement sans modifier l'annonce d'origine."""
        if not offer.company_name.strip() or not offer.job_title.strip():
            return []
        payload = {
            "company_name_or": [offer.company_name.strip()],
            "job_title_or": [offer.job_title.strip()],
            "limit": THEIRSTACK_RESULT_LIMIT,
        }
        return self.search_jobs(payload)

    def hydrate(self, offer: JobOffer) -> DescriptionHydration:
        """Tente de compléter la description d'une offre tout en conservant sa provenance."""
        candidates = self.search_candidates(offer)
        ranked = sorted(
            ((_identity_score(offer, item), item) for item in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for identity_score, item in ranked:
            if identity_score < 0.80:
                continue
            description = str(item.get("description") or "").strip()
            current_length = max(
                len(offer.responsibilities.strip()),
                len(offer.short_description.strip()),
            )
            if len(description) < max(
                300, current_length + 80
            ) or description_is_probably_truncated(description):
                continue
            theirstack_id = str(item.get("id") or "")
            enriched = replace(
                offer,
                responsibilities=description,
                description_is_full=True,
                description_enrichment_source="TheirStack",
                description_enrichment_external_id=theirstack_id,
            )
            return DescriptionHydration(
                offer=enriched,
                is_complete=True,
                method="TheirStack Job Search",
            )
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            method="TheirStack Job Search",
            warning="Aucune correspondance TheirStack suffisamment fiable.",
        )
