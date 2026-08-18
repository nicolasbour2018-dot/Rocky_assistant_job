from __future__ import annotations

from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from dashboard import dashboard_common
from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.models import JobOffer, MatchResult
from dashboard.rocky.repository import RockyRepository


def _repository(tmp_path):
    settings = Settings(
        database_url_override=f"sqlite:///{tmp_path / 'rocky_profiles.db'}"
    )
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    return settings, engine, RockyRepository(engine)


def _offer(title: str, key: str) -> JobOffer:
    return JobOffer(
        title,
        "Entreprise Exemple",
        "Description complète avec compétences et missions détaillées.",
        source_name="Test",
        source_url=f"https://jobs.example/{key}",
        description_is_full=True,
    )


def test_one_central_job_can_be_linked_to_two_profiles_without_duplication(tmp_path):
    _, engine, repository = _repository(tmp_path)
    profile_a = repository.create_profile("Data Scientist")
    profile_b = repository.create_profile("Enseignement / EdTech")
    repository.set_active_profile(profile_a)

    data_id, _ = repository.insert_job(
        _offer("Data Scientist", "data"), profile_a
    )
    teaching_id, _ = repository.insert_job(
        _offer("Responsable pédagogique", "teaching"), profile_b
    )
    shared_id, inserted = repository.insert_job(
        _offer("Learning Data Analyst", "shared"), profile_a
    )
    same_shared_id, inserted_again = repository.insert_job(
        _offer("Learning Data Analyst", "shared"), profile_b
    )

    repository.save_match(
        shared_id, profile_a, MatchResult(84, {"profile": "data"})
    )
    repository.save_match(
        shared_id, profile_b, MatchResult(67, {"profile": "teaching"})
    )

    jobs_a = repository.get_jobs_for_profile(profile_a)
    jobs_b = repository.get_jobs_for_profile(profile_b)
    with engine.connect() as connection:
        central_count = connection.execute(
            text("SELECT COUNT(*) FROM job_offers")
        ).scalar_one()
        shared_links = connection.execute(
            text("SELECT COUNT(*) FROM profile_jobs WHERE job_id = :job_id"),
            {"job_id": shared_id},
        ).scalar_one()

    assert inserted is True
    assert inserted_again is False
    assert same_shared_id == shared_id
    assert central_count == 3
    assert shared_links == 2
    assert set(jobs_a["id"]) == {data_id, shared_id}
    assert set(jobs_b["id"]) == {teaching_id, shared_id}
    assert jobs_a.loc[jobs_a["id"] == shared_id, "match_score"].iloc[0] == 84
    assert jobs_b.loc[jobs_b["id"] == shared_id, "match_score"].iloc[0] == 67
    engine.dispose()


def test_stable_application_url_deduplicates_across_sources(tmp_path):
    _, engine, repository = _repository(tmp_path)
    profile_a = repository.create_profile("Data Scientist")
    profile_b = repository.create_profile("BI Analyst")
    stable_url = "https://careers.example/jobs/42"
    career_offer = JobOffer(
        "Data Analyst",
        "Entreprise Exemple",
        "Description complète avec Python et SQL.",
        source_name="Site carrière",
        source_url=stable_url,
        application_url=stable_url,
        description_is_full=True,
    )
    indeed_offer = JobOffer(
        "Data Analyst",
        "Entreprise Exemple",
        "Description complète avec Python et SQL.",
        source_name="Indeed",
        collector_name="TheirStack",
        source_url="https://fr.indeed.com/viewjob?jk=abc123",
        application_url=stable_url,
        external_id="abc123",
        description_is_full=True,
    )

    first_id, inserted = repository.insert_job(career_offer, profile_a)
    second_id, inserted_again = repository.insert_job(indeed_offer, profile_b)

    assert inserted is True
    assert inserted_again is False
    assert second_id == first_id
    assert len(repository.get_jobs_for_profile(profile_a)) == 1
    assert len(repository.get_jobs_for_profile(profile_b)) == 1
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM job_offers")
        ).scalar_one() == 1
    engine.dispose()


def test_switching_active_profile_changes_the_existing_cockpit(
    tmp_path, monkeypatch
):
    settings, engine, repository = _repository(tmp_path)
    profile_a = repository.create_profile("Data Scientist")
    profile_b = repository.create_profile("Enseignement / EdTech")
    repository.insert_job(_offer("Offre Data uniquement", "a"), profile_a)
    repository.insert_job(_offer("Offre EdTech uniquement", "b"), profile_b)
    shared_id, _ = repository.insert_job(
        _offer("Offre commune", "shared"), profile_a
    )
    repository.link_job_to_profile(shared_id, profile_b)
    repository.set_active_profile(profile_a)

    monkeypatch.setattr(dashboard_common, "Settings", lambda: settings)
    dashboard_common.load_repository.clear()
    app = AppTest.from_file(
        settings.project_dir / "dashboard" / "dashboard_b.py"
    )
    app.run(timeout=30)
    next(
        select for select in app.selectbox if select.label == "Flux — statut"
    ).set_value("NOUVELLE").run(timeout=30)
    titles_a = {item.value for item in app.subheader}

    repository.set_active_profile(profile_b)
    app.run(timeout=30)
    titles_b = {item.value for item in app.subheader}

    assert "Offre Data uniquement" in titles_a
    assert "Offre EdTech uniquement" not in titles_a
    assert "Offre commune" in titles_a
    assert "Offre EdTech uniquement" in titles_b
    assert "Offre Data uniquement" not in titles_b
    assert "Offre commune" in titles_b
    assert repository.fetch_active_profile().id == profile_b
    dashboard_common.load_repository.clear()
    engine.dispose()


def test_idempotent_schema_backfills_a_legacy_watch_without_match(tmp_path):
    settings, engine, repository = _repository(tmp_path)
    old_profile = repository.create_profile("Profil historique")
    watch_profile = repository.create_profile("Profil de veille")
    repository.set_active_profile(watch_profile)
    run_id = repository.start_watch_run(watch_profile)
    job_id, _ = repository.insert_job(
        JobOffer(
            "Annonce incomplète historique",
            "Entreprise Exemple",
            "Bref aperçu",
            source_name="Test",
            source_url="https://jobs.example/legacy-preview",
            status="INCOMPLÈTE",
        )
    )
    repository.finish_watch_run(
        run_id,
        {
            "status": "SUCCESS",
            "fetched_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "rejected_count": 0,
            "errors": [],
        },
    )

    initialize_database(engine, settings)
    initialize_database(engine, settings)

    assert job_id in set(repository.get_jobs_for_profile(watch_profile)["id"])
    assert job_id not in set(repository.get_jobs_for_profile(old_profile)["id"])
    with engine.connect() as connection:
        links = connection.execute(
            text("SELECT COUNT(*) FROM profile_jobs WHERE job_id = :job_id"),
            {"job_id": job_id},
        ).scalar_one()
    assert links == 1
    engine.dispose()


def test_bulk_status_update_changes_only_the_selected_jobs(tmp_path):
    _, engine, repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil test")
    first, _ = repository.insert_job(_offer("Première", "first"), profile_id)
    second, _ = repository.insert_job(_offer("Deuxième", "second"), profile_id)
    untouched, _ = repository.insert_job(
        _offer("Non sélectionnée", "untouched"), profile_id
    )

    updated = repository.update_jobs_status([first, second, first], "À ÉTUDIER")

    assert updated == 2
    assert repository.fetch_job(first)["status"] == "À ÉTUDIER"
    assert repository.fetch_job(second)["status"] == "À ÉTUDIER"
    assert repository.fetch_job(untouched)["status"] == "NOUVELLE"
    engine.dispose()
