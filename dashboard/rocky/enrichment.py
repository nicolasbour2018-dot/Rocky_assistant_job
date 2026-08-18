"""Réenrichissement volontaire des annonces déjà enregistrées."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Callable

from .config import Settings
from .errors import RockyError
from .job_importer import DescriptionHydration, hydrate_job_offer
from .matching import calculate_match
from .models import CandidateProfile, JobOffer
from .statuses import INCOMPLETE_STATUS
from .theirstack import TheirStackClient

if TYPE_CHECKING:
    from .repository import RockyRepository


def reenrich_job_offer(
    offer: JobOffer,
    settings: Settings,
    theirstack_client: TheirStackClient | None = None,
) -> DescriptionHydration:
    """Essaie la source d'origine, puis TheirStack seulement si nécessaire."""
    primary = hydrate_job_offer(offer)
    if primary.is_complete:
        return primary
    if not settings.theirstack_api_key and theirstack_client is None:
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            method=primary.method,
            warning=(
                primary.warning
                + " TheirStack n’est pas configuré pour le fallback."
            ).strip(),
        )
    client = theirstack_client or TheirStackClient(settings.theirstack_api_key)
    try:
        secondary = client.hydrate(offer)
    except RockyError as error:
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            method=primary.method,
            warning=" ".join(
                value for value in (primary.warning, str(error)) if value
            ),
        )
    if secondary.is_complete:
        return secondary
    return DescriptionHydration(
        offer=offer,
        is_complete=False,
        method=secondary.method or primary.method,
        warning=" ".join(
            value for value in (primary.warning, secondary.warning) if value
        ),
    )


def reenrich_saved_job(
    job_id: int,
    settings: Settings,
    repository: RockyRepository,
    profile: CandidateProfile | None = None,
    theirstack_client: TheirStackClient | None = None,
) -> DescriptionHydration:
    """Exécute l'action volontaire, persiste le succès et relance le matching."""
    offer = repository.fetch_job_offer(job_id)
    if offer is None:
        raise ValueError(f"Annonce Rocky introuvable : {job_id}")
    hydration = reenrich_job_offer(offer, settings, theirstack_client)
    if not hydration.is_complete:
        if offer.status == "NOUVELLE":
            repository.update_job_status(job_id, INCOMPLETE_STATUS)
        return hydration

    next_status = (
        "NOUVELLE" if offer.status == INCOMPLETE_STATUS else offer.status
    )
    enriched = replace(hydration.offer, status=next_status)
    repository.update_job(job_id, enriched)
    if next_status != offer.status:
        repository.update_job_status(job_id, next_status)
    if profile is not None:
        skills = repository.fetch_skills(profile.id)
        result = calculate_match(enriched, profile, skills)
        repository.save_match(job_id, profile.id, result)
    return replace(hydration, offer=enriched)


def reenrich_saved_jobs(
    job_ids: list[int],
    settings: Settings,
    repository: RockyRepository,
    profile: CandidateProfile | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Retente volontairement toute une file sans interrompre sur un échec."""
    theirstack_client = (
        TheirStackClient(settings.theirstack_api_key)
        if settings.theirstack_api_key
        else None
    )
    summary = {
        "attempted": len(job_ids),
        "enriched": 0,
        "still_incomplete": 0,
        "errors": 0,
    }
    for index, job_id in enumerate(job_ids, start=1):
        try:
            hydration = reenrich_saved_job(
                job_id,
                settings,
                repository,
                profile,
                theirstack_client,
            )
            if hydration.is_complete:
                summary["enriched"] += 1
            else:
                summary["still_incomplete"] += 1
        except (RockyError, OSError, ValueError):
            summary["errors"] += 1
        if on_progress is not None:
            on_progress(index, len(job_ids))
    return summary
