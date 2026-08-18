import json
from dataclasses import replace
from datetime import date

from dashboard.rocky.bootstrap import bootstrap_default_profile
from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.models import JobOffer, MatchResult
from dashboard.rocky.repository import RockyRepository


def test_sqlite_repository_supports_huggingface_workflow(tmp_path):
    database_path = tmp_path / "storage" / "rocky.db"
    settings = Settings(
        database_url_override=f"sqlite:///{database_path}",
        storage_dir_override=str(tmp_path / "storage"),
    )
    assert ensure_database_exists(settings) is True
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)

    profile, created = bootstrap_default_profile(
        settings, repository, cv_source=tmp_path / "absent.pdf"
    )
    assert created is True
    assert profile.is_active is True
    assert "Data Analyst" in profile.target_job_titles
    skills = repository.fetch_skills(profile.id)
    assert skills
    skill_id = int(skills[0]["id"])
    original_name = str(skills[0]["skill_name"])
    assert repository.update_skill(
        skill_id,
        profile.id + 999,
        "Ne doit pas changer",
        "soft",
        "débutant",
        1,
        False,
    ) is False
    assert repository.update_skill(
        skill_id,
        profile.id,
        original_name,
        "technical",
        "avancé",
        3.5,
        True,
    ) is True
    edited_skill = next(
        item for item in repository.fetch_skills(profile.id) if item["id"] == skill_id
    )
    assert edited_skill["skill_level"] == "avancé"
    assert float(edited_skill["years_experience"]) == 3.5
    assert bool(edited_skill["is_core_skill"]) is True

    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Entreprise Exemple",
        responsibilities="Analyse avec Python et SQL",
        source_name="Test",
        collector_name="TheirStack",
        source_url="https://jobs.example/42",
        application_url="https://jobs.example/42/apply",
        contract_type="permanent",
        work_schedule="full_time",
        description_is_full=True,
        detected_skills=["Python", "SQL"],
    )
    job_id, inserted = repository.insert_job(offer)
    assert inserted is True
    repository.save_match(
        job_id,
        profile.id,
        MatchResult(
            score=91.5,
            breakdown={"skills": {"raw_score": 100}},
            strengths=["Python"],
            gaps=[],
            detected_job_skills=["Python", "SQL"],
        ),
    )

    jobs = repository.fetch_jobs(profile.id)
    assert len(jobs) == 1
    assert jobs.iloc[0]["match_score"] == 91.5
    assert jobs.iloc[0]["contract_type"] == "CDI"
    assert jobs.iloc[0]["work_schedule"] == "Temps plein"
    assert jobs.iloc[0]["collector_name"] == "TheirStack"
    assert json.loads(jobs.iloc[0]["required_skills"]) == ["Python", "SQL"]
    assert json.loads(jobs.iloc[0]["match_breakdown"])["skills"]

    edited_offer = replace(
        offer,
        company_name="Entreprise Corrigée",
        contract_type="CDD",
        work_schedule="part_time",
        detected_skills=["Python", "SQL", "Tableau"],
    )
    repository.update_job(job_id, edited_offer)
    edited_job = repository.fetch_job(job_id)
    assert edited_job is not None
    assert edited_job["company_name"] == "Entreprise Corrigée"
    assert edited_job["contract_type"] == "CDD"
    assert edited_job["work_schedule"] == "Temps partiel"
    assert edited_job["collector_name"] == "TheirStack"
    assert json.loads(edited_job["required_skills"]) == [
        "Python",
        "SQL",
        "Tableau",
    ]

    run_id = repository.start_watch_run(profile.id)
    repository.finish_watch_run(
        run_id,
        {
            "status": "SUCCESS",
            "fetched_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "rejected_count": 0,
            "errors": [],
            "sources": [
                {"source": "Adzuna", "status": "OK", "fetched_count": 1},
                {"source": "Indeed", "status": "ERREUR", "fetched_count": 0},
            ],
        },
    )
    assert repository.has_watch_run_on(date.today()) is True
    runs = repository.fetch_watch_runs()
    source_results = json.loads(runs.iloc[0]["source_results"])
    assert source_results[0] == {
        "source": "Adzuna",
        "status": "OK",
        "fetched_count": 1,
    }
    assert source_results[1]["source"] == "Indeed"
