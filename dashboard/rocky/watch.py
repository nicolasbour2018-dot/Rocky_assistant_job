"""Orchestration de la veille quotidienne."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from .config import Settings
from .errors import ConfigurationError, SourceError
from .job_importer import hydrate_job_offer
from .matching import calculate_match
from .repository import RockyRepository
from .sources.base import JobSource
from .statuses import INCOMPLETE_STATUS


logger = logging.getLogger(__name__)


SOURCE_REFRESH_FIELDS = (
    "application_url",
    "job_title",
    "company_name",
    "city",
    "country",
    "remote_policy",
    "contract_type",
    "work_schedule",
    "experience_level",
    "salary_min",
    "salary_max",
    "salary_currency",
    "short_description",
    "required_education",
    "minimum_experience_years",
    "main_domain",
    "publication_date",
    "application_deadline",
)


def _has_value(value: Any) -> bool:
    """Distingue les valeurs métier renseignées des valeurs pandas vides ou indéfinies."""
    return value not in (None, "", [])


def merge_known_offer(existing: Any, incoming: Any):
    """Actualise les métadonnées sans toucher à l'identité ni au texte validé."""
    updates = {
        field: getattr(incoming, field)
        for field in SOURCE_REFRESH_FIELDS
        if _has_value(getattr(incoming, field))
    }
    if not existing.detected_skills and incoming.detected_skills:
        updates["detected_skills"] = incoming.detected_skills
    if (
        not existing.collector_name
        and existing.source_name == incoming.source_name
        and incoming.collector_name
    ):
        updates["collector_name"] = incoming.collector_name
    return replace(existing, **updates)


class WatchService:
    """Orchestre une veille multi-sources, son matching et son journal d'exécution."""
    def __init__(
        self,
        settings: Settings,
        repository: RockyRepository,
        sources: list[JobSource],
    ):
        """Assemble réglages, persistance et connecteurs sans déclencher de collecte."""
        self.settings = settings
        self.repository = repository
        self.sources = sources

    def _localized_profile(self, profile, offer):
        """Garde la compatibilité avec les repositories factices des connecteurs."""
        selector = getattr(self.repository, "profile_for_offer", None)
        if not callable(selector):
            return profile
        return selector(profile.id, offer) or profile

    def run(self, profile_override=None) -> dict[str, Any]:
        """Exécute la veille, éventuellement avec des postes ponctuels.

        ``profile_override`` permet à l'interface de tester une requête libre
        sans écraser les préférences persistées du profil. En l'absence de
        surcharge, le comportement historique (profil actif) est inchangé.
        """
        profile = profile_override or self.repository.fetch_active_profile()
        if profile is None:
            raise ConfigurationError(
                "Choisis un profil actif dans le dashboard avant la veille."
            )
        stale_policy = getattr(self.repository, "apply_stale_new_job_policy", None)
        stale_summary = (
            stale_policy() if callable(stale_policy) else {
                "ancient_count": 0,
                "discarded_count": 0,
            }
        )
        skills = self.repository.fetch_skills(profile.id)
        searched_job_titles = tuple(
            str(title).strip()
            for title in profile.target_job_titles
            if str(title).strip()
        )
        run_id = self.repository.start_watch_run(profile.id, searched_job_titles)
        summary: dict[str, Any] = {
            "run_id": run_id,
            "searched_job_titles": list(searched_job_titles),
            "status": "SUCCESS",
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "duplicate_count": 0,
            "rejected_count": 0,
            "below_threshold_count": 0,
            "incomplete_description_count": 0,
            "ancient_count": int(stale_summary.get("ancient_count", 0)),
            "discarded_count": int(stale_summary.get("discarded_count", 0)),
            "errors": [],
            "sources": [],
        }
        for source in self.sources:
            collector = str(getattr(source, "collector_name", "") or "")
            source_label = (
                f"{source.name}/{collector}" if collector else source.name
            )
            logger.info(
                "[%s] Recherche démarrée · Profil : %s",
                source_label,
                profile.profile_name,
            )
            try:
                offers = source.search(
                    profile, self.settings.watch_results_per_query
                )
            except (ConfigurationError, SourceError) as error:
                summary["errors"].append(
                    {"source": source.name, "message": str(error)}
                )
                source_result = {
                    "source": source.name,
                    "status": "ERREUR",
                    "fetched_count": 0,
                }
                if collector:
                    source_result["collector"] = collector
                summary["sources"].append(source_result)
                logger.warning("[%s] Collecte en erreur : %s", source_label, error)
                continue
            except Exception:
                # Une évolution HTML d'une plateforme ne doit jamais arrêter
                # les six autres sources ni exposer un détail technique.
                message = "Erreur technique isolée dans ce connecteur."
                summary["errors"].append(
                    {"source": source.name, "message": message}
                )
                source_result = {
                    "source": source.name,
                    "status": "ERREUR",
                    "fetched_count": 0,
                }
                if collector:
                    source_result["collector"] = collector
                summary["sources"].append(source_result)
                logger.error(
                    "[%s] Erreur technique isolée dans le connecteur",
                    source_label,
                )
                continue

            logger.info("[%s] %d annonce(s) reçue(s)", source_label, len(offers))
            inserted_before = summary["inserted_count"]
            duplicate_before = summary["duplicate_count"]
            updated_before = summary["updated_count"]
            rejected_before = summary["rejected_count"]
            incomplete_before = summary["incomplete_description_count"]
            summary["fetched_count"] += len(offers)

            for offer in offers:
                duplicate_id = self.repository.find_duplicate(offer)
                if duplicate_id is not None:
                    # Une annonce connue n'est pas réhydratée à chaque veille.
                    # Sa provenance, son statut et sa description validée sont
                    # conservés ; seules les métadonnées source utiles évoluent.
                    summary["duplicate_count"] += 1
                    self.repository.link_job_to_profile(
                        duplicate_id, profile.id
                    )
                    existing = self.repository.fetch_job_offer(duplicate_id)
                    if existing is not None:
                        merged = merge_known_offer(existing, offer)
                        summary["updated_count"] += int(
                            self.repository.update_job_if_changed(
                                duplicate_id, merged
                            )
                        )
                        # Une annonce peut être connue globalement mais nouvelle
                        # pour ce profil. Son score n'est calculé qu'une fois par
                        # profil, sans réhydrater ni retraiter les veilles suivantes.
                        if (
                            merged.description_is_full
                            and not self.repository.has_job_match(
                                duplicate_id, profile.id
                            )
                        ):
                            localized = self._localized_profile(profile, merged)
                            result = calculate_match(merged, localized, skills)
                            self.repository.save_match(
                                duplicate_id, profile.id, result
                            )
                    continue
                hydration = hydrate_job_offer(offer)
                if not hydration.is_complete:
                    # L'aperçu est conservé, sans produire de score présenté
                    # comme fiable. Une action volontaire pourra le réenrichir.
                    summary["incomplete_description_count"] += 1
                    incomplete = replace(
                        hydration.offer,
                        description_is_full=False,
                        status=INCOMPLETE_STATUS,
                    )
                    _, inserted = self.repository.insert_job(
                        incomplete, profile.id
                    )
                    summary["inserted_count"] += int(inserted)
                    continue
                offer = hydration.offer
                localized = self._localized_profile(profile, offer)
                result = calculate_match(offer, localized, skills)
                if result.score < self.settings.match_threshold:
                    summary["below_threshold_count"] += 1
                    summary["rejected_count"] += 1
                    continue
                job_id, inserted = self.repository.insert_job(
                    offer, profile.id
                )
                self.repository.save_match(job_id, profile.id, result)
                summary["inserted_count"] += int(inserted)

            source_result = {
                "source": source.name,
                "status": "OK",
                "fetched_count": len(offers),
                "inserted_count": (
                    summary["inserted_count"] - inserted_before
                ),
                "duplicate_count": (
                    summary["duplicate_count"] - duplicate_before
                ),
                "updated_count": summary["updated_count"] - updated_before,
                "rejected_count": (
                    summary["rejected_count"] - rejected_before
                ),
                "incomplete_count": (
                    summary["incomplete_description_count"] - incomplete_before
                ),
            }
            if collector:
                source_result["collector"] = collector
            summary["sources"].append(source_result)
            logger.info(
                "[%s] Collecte terminée · %d nouvelle(s) · %d doublon(s) · "
                "%d actualisée(s)",
                source_label,
                source_result["inserted_count"],
                source_result["duplicate_count"],
                source_result["updated_count"],
            )

        if summary["errors"] and summary["fetched_count"] == 0:
            summary["status"] = "FAILED"
        elif summary["errors"]:
            summary["status"] = "PARTIAL"
        self.repository.finish_watch_run(run_id, summary)
        return summary
