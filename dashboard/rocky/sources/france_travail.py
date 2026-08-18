"""Connecteur API Offres d'emploi de France Travail."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests

from ..config import Settings
from ..errors import ConfigurationError, SourceError
from ..models import CandidateProfile, JobOffer


class FranceTravailSource:
    name = "France Travail"
    token_url = (
        "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
        "?realm=/partenaire"
    )
    search_url = (
        "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    )

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _oauth_error_code(response: requests.Response | None) -> str | None:
        """Retourne uniquement un code OAuth connu, jamais le corps brut.

        Les réponses d'authentification peuvent contenir des détails sensibles.
        Une liste fermée permet d'aider au diagnostic sans risquer de recopier
        un identifiant ou une URL incluant un secret dans l'interface ou les logs.
        """
        if response is None:
            return None
        try:
            value = str(response.json().get("error") or "")
        except (ValueError, AttributeError):
            return None
        allowed = {
            "access_denied",
            "invalid_client",
            "invalid_grant",
            "invalid_request",
            "invalid_scope",
            "server_error",
            "temporarily_unavailable",
            "unauthorized_client",
            "unsupported_grant_type",
        }
        return value if value in allowed else None

    def _token(self) -> str:
        if (
            not self.settings.france_travail_client_id
            or not self.settings.france_travail_client_secret
        ):
            raise ConfigurationError(
                "Les credentials France Travail sont absents."
            )
        try:
            response = requests.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.france_travail_client_id,
                    "client_secret": self.settings.france_travail_client_secret,
                    "scope": "api_offresdemploiv2 o2dsoffre",
                },
                timeout=20,
            )
            response.raise_for_status()
            return str(response.json()["access_token"])
        except requests.HTTPError as error:
            status = (
                error.response.status_code
                if error.response is not None
                else "inconnu"
            )
            oauth_code = self._oauth_error_code(error.response)
            if oauth_code == "invalid_client":
                raise SourceError(
                    "Les identifiants applicatifs France Travail sont refusés. "
                    "Utilise le client_id et le client_secret de l'application "
                    "abonnée à l'API Offres d'emploi v2, pas les identifiants "
                    "de ton compte personnel."
                ) from error
            detail = f", code {oauth_code}" if oauth_code else ""
            raise SourceError(
                f"Authentification France Travail refusée (HTTP {status}{detail})."
            ) from error
        except (requests.RequestException, ValueError, KeyError) as error:
            raise SourceError(
                "France Travail ne répond pas ou son jeton est invalide."
            ) from error

    @staticmethod
    def _salary(value: str) -> tuple[float | None, float | None]:
        numbers = []
        for raw in re.findall(r"\d[\d\s.,]*", value or ""):
            try:
                number = float(raw.replace(" ", "").replace(",", "."))
            except ValueError:
                continue
            if number >= 1_000:
                numbers.append(number)
        if not numbers:
            return None, None
        return min(numbers), max(numbers)

    @classmethod
    def _offer(cls, item: dict[str, Any]) -> JobOffer:
        company = item.get("entreprise") or {}
        location = item.get("lieuTravail") or {}
        origin = item.get("origineOffre") or {}
        salary = item.get("salaire") or {}
        salary_min, salary_max = cls._salary(str(salary.get("libelle") or ""))
        published = item.get("dateCreation")
        publication_date = None
        if published:
            try:
                publication_date = datetime.fromisoformat(
                    str(published).replace("Z", "+00:00")
                ).date()
            except ValueError:
                publication_date = None
        source_url = str(
            origin.get("urlOrigine")
            or item.get("contact", {}).get("urlPostulation")
            or ""
        )
        return JobOffer(
            external_id=str(item.get("id") or ""),
            source_name="France Travail",
            source_url=source_url,
            application_url=str(
                item.get("contact", {}).get("urlPostulation") or source_url
            ),
            job_title=str(item.get("intitule") or "").strip(),
            company_name=str(company.get("nom") or "Non précisée").strip(),
            city=str(location.get("libelle") or "").strip(),
            country="France",
            remote_policy=str(item.get("typeLieuTravail") or ""),
            contract_type=str(
                item.get("typeContratLibelle") or item.get("typeContrat") or ""
            ),
            work_schedule=str(
                item.get("dureeTravailLibelleConverti")
                or item.get("dureeTravailLibelle")
                or ""
            ),
            experience_level=str(item.get("experienceLibelle") or ""),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="EUR",
            short_description=str(item.get("description") or "")[:600],
            description_is_full=bool(item.get("description")),
            responsibilities=str(item.get("description") or "").strip(),
            required_education=", ".join(
                formation.get("niveauLibelle", "")
                for formation in item.get("formations", [])
                if formation.get("niveauLibelle")
            ),
            main_domain=str(item.get("secteurActiviteLibelle") or ""),
            publication_date=publication_date,
        )

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        token = self._token()
        queries = profile.target_job_titles or [profile.profile_name]
        collected: list[JobOffer] = []
        for query in queries:
            try:
                response = requests.get(
                    self.search_url,
                    params={"motsCles": query},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Range": f"offres=0-{max(0, results_per_query - 1)}",
                    },
                    timeout=25,
                )
                response.raise_for_status()
                items = response.json().get("resultats", [])
            except requests.HTTPError as error:
                status = (
                    error.response.status_code
                    if error.response is not None
                    else "inconnu"
                )
                raise SourceError(
                    f"France Travail a refusé la recherche (HTTP {status})."
                ) from error
            except (requests.RequestException, ValueError) as error:
                raise SourceError(
                    "France Travail ne répond pas ou sa réponse est invalide."
                ) from error
            collected.extend(self._offer(item) for item in items)
        return collected
