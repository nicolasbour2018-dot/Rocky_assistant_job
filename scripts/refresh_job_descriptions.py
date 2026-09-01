"""Action volontaire de réenrichissement des annonces incomplètes Rocky."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine, initialize_database
from dashboard.rocky.enrichment import reenrich_job_offer
from dashboard.rocky.job_importer import DescriptionHydration
from dashboard.rocky.matching import calculate_match
from dashboard.rocky.models import JobOffer
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.statuses import INCOMPLETE_STATUS


def _hydrate(
    item: tuple[int, JobOffer], settings: Settings
) -> tuple[int, DescriptionHydration]:
    job_id, offer = item
    return job_id, reenrich_job_offer(offer, settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre maximal d'annonces à traiter (0 = toutes).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Nombre maximal de pages détaillées lues en parallèle.",
    )
    arguments = parser.parse_args()

    settings = Settings()
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    profile = repository.fetch_active_profile()
    jobs = repository.fetch_jobs(profile.id if profile else None)
    incomplete_ids = [
        int(row["id"])
        for _, row in jobs.iterrows()
        if not bool(row.get("description_is_full"))
    ]
    if arguments.limit > 0:
        incomplete_ids = incomplete_ids[: arguments.limit]

    pending = []
    for job_id in incomplete_ids:
        offer = repository.fetch_job_offer(job_id)
        if offer is not None:
            pending.append((job_id, offer))

    refreshed = 0
    unavailable = 0
    skills = repository.fetch_skills(profile.id) if profile else []
    with ThreadPoolExecutor(max_workers=max(1, arguments.workers)) as executor:
        futures = [executor.submit(_hydrate, item, settings) for item in pending]
        for index, future in enumerate(as_completed(futures), start=1):
            job_id, hydration = future.result()
            if not hydration.is_complete:
                current = repository.fetch_job_offer(job_id)
                if current is not None and current.status == "NOUVELLE":
                    repository.update_job_status(job_id, INCOMPLETE_STATUS)
                unavailable += 1
                print(
                    f"[{index}/{len(pending)}] Annonce {job_id} : "
                    "description complète indisponible."
                )
                continue
            repository.update_job(job_id, hydration.offer)
            if hydration.offer.status == INCOMPLETE_STATUS:
                repository.update_job_status(job_id, "NOUVELLE")
            if profile:
                result = calculate_match(hydration.offer, profile, skills)
                repository.save_match(job_id, profile.id, result)
            refreshed += 1
            print(
                f"[{index}/{len(pending)}] Annonce {job_id} : "
                f"description complète enregistrée ({hydration.method})."
            )

    print(
        f"Terminé : {refreshed} mise(s) à jour, {unavailable} page(s) indisponible(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
