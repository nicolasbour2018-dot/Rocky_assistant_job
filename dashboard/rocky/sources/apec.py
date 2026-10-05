"""Connecteur du webservice public utilisé par la recherche Apec."""

from __future__ import annotations

from typing import Any, Iterable

from ..errors import SourceError
from ..models import CandidateProfile, JobOffer
from .common import (
    deduplicate_offers,
    iso_date,
    public_post_json,
    salary_values,
)


class ApecSource:
    """Adaptateur Apec qui transforme son API de recherche en annonces Rocky."""
    name = "Apec"
    search_url = "https://www.apec.fr/cms/webservices/rechercheOffre"
    detail_base_url = (
        "https://www.apec.fr/candidat/recherche-emploi.html/emploi/"
        "detail-offre"
    )

    @staticmethod
    def _payload(query: str, limit: int) -> dict[str, Any]:
        """Reproduit uniquement les critères publics minimaux du formulaire Apec."""
        return {
            "motsCles": query,
            "lieux": [],
            "fonctions": [],
            "statutPoste": [],
            "typesContrat": [],
            "typesConvention": [],
            "niveauxExperience": [],
            "idsEtablissement": [],
            "secteursActivite": [],
            "typesTeletravail": [],
            "idNomZonesDeplacement": [],
            "positionNumbersExcluded": [],
            "typeClient": "CADRE",
            "sorts": [{"type": "DATE", "direction": "DESCENDING"}],
            "pagination": {"range": min(max(limit, 1), 100), "startIndex": 0},
            "activeFiltre": True,
            "pointGeolocDeReference": {},
        }

    @classmethod
    def _offer(cls, item: dict[str, Any]) -> JobOffer:
        """Normalise une offre Apec pour le flux commun de veille."""
        salary_min, salary_max, currency = salary_values(item.get("salaireTexte"))
        external_id = str(item.get("numeroOffre") or item.get("id") or "")
        url = f"{cls.detail_base_url}/{external_id}"
        description = str(item.get("texteOffre") or "").strip()
        return JobOffer(
            external_id=external_id,
            source_name=cls.name,
            source_url=url,
            application_url=url,
            job_title=str(item.get("intitule") or "").strip(),
            company_name=str(item.get("nomCommercial") or "Non précisée").strip(),
            city=str(item.get("lieuTexte") or "").strip(),
            country="France",
            remote_policy=str(item.get("typeTeletravail") or ""),
            contract_type=str(
                item.get("typeContratLibelle")
                or item.get("typeContrat")
                or ""
            ),
            work_schedule=str(
                item.get("tempsTravail")
                or item.get("dureeTravail")
                or ""
            ),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            short_description=description[:600],
            # ``texteOffre`` est l'aperçu de la liste de résultats, pas le
            # contenu de la fiche. L'hydratation Apec récupère ensuite le détail.
            description_is_full=False,
            responsibilities=description,
            publication_date=iso_date(item.get("datePublication")),
        )

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        """Recherche les postes du profil via Apec et retourne des offres non persistées."""
        queries: Iterable[str] = profile.target_job_titles or [profile.profile_name]
        collected: list[JobOffer] = []
        for query in queries:
            response = public_post_json(
                self.name,
                self.search_url,
                self._payload(query, results_per_query),
                headers={"Referer": "https://www.apec.fr/candidat/recherche-emploi.html/emploi"},
            )
            try:
                items = response.json().get("resultats", [])
            except (ValueError, AttributeError) as error:
                raise SourceError("Apec a renvoyé une réponse invalide.") from error
            collected.extend(self._offer(item) for item in items)
        return deduplicate_offers(collected)
