"""Régression ciblée du retrait d'un dossier de la pile de candidatures."""

from pathlib import Path

import pytest

from dashboard.rocky.application_statuses import normalize_application_status
from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine, initialize_database
from dashboard.rocky.models import JobOffer
from dashboard.rocky.repository import RockyRepository


def _repository(tmp_path: Path) -> RockyRepository:
    """Construit une base isolée : un seul test couvre cette règle d'affichage."""
    settings = Settings(database_url_override=f"sqlite:///{tmp_path / 'rocky.db'}")
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    return RockyRepository(engine)


def test_discarded_application_uses_one_label_and_leaves_candidate_stack(tmp_path):
    """Écarter garde l'historique, mais masque le dossier du suivi courant."""
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil écarté")
    job_id, _ = repository.insert_job(
        JobOffer("Analyste", "Acme", "Python SQL", description_is_full=True),
        profile_id,
    )
    application_id = repository.create_application(
        job_id, profile_id, "cv.pdf", None, "letter.pdf"
    )

    repository.update_application_status(application_id, "ÉCARTÉE")

    with pytest.raises(ValueError, match="Statut de candidature inconnu"):
        normalize_application_status("RETIRÉE")
    assert repository.fetch_application(application_id)["status"] == "ÉCARTÉE"
    assert repository.fetch_job_offer(job_id).status == "ÉCARTÉE"
    assert repository.fetch_applications(profile_id).empty
