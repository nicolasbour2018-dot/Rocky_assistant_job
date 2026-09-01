"""Vérifie que la page Candidatures reste compacte avec un volume réel."""

from pathlib import Path

import pandas as pd
from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from dashboard import dashboard_common
from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine, initialize_database
from dashboard.rocky.application_filters import filter_applications
from dashboard.rocky.models import JobOffer, MatchResult
from dashboard.rocky.repository import RockyRepository


PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_applications_use_horizontal_cards_and_counted_tabs(tmp_path, monkeypatch):
    """Les dossiers et e-mails utilisent des cartes, sans liste verticale."""
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{tmp_path / 'compact-applications.db'}",
    )
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email, status) "
                "VALUES ('applications@example.test', 'ACTIVE') RETURNING id"
            )
        ).scalar_one()
    repository = RockyRepository(engine).for_user(user_id)
    profile_id = repository.create_profile("Profil compact")
    repository.set_active_profile(profile_id)

    application_ids: list[int] = []
    for index, (company, status) in enumerate(
        (("Acme", "DOSSIER PRÉPARÉ"), ("Beta", "CANDIDATURE ENVOYÉE")),
        start=1,
    ):
        job_id, _ = repository.insert_job(
            JobOffer(
                f"Data Analyst {index}",
                company,
                "Python SQL et analyse de données",
                source_url=f"https://jobs.example/{index}",
                application_url=f"https://jobs.example/{index}/apply",
                description_is_full=True,
            ),
            profile_id,
        )
        repository.save_match(
            job_id,
            profile_id,
            MatchResult(60 if index == 1 else 80, {}),
        )
        application_id = repository.create_application(
            job_id, profile_id, "cv.pdf", None, "lettre.pdf"
        )
        application_ids.append(application_id)
        if status != "DOSSIER PRÉPARÉ":
            repository.update_application_status(application_id, status)

    repository.save_email_message(
        {
            "gmail_account": "second@example.test",
            "gmail_message_id": "compact-email-1",
            "gmail_thread_id": None,
            "sender": "recruteur@example.com",
            "subject": "Votre candidature chez Beta",
            "received_at": None,
            "snippet": "Nous avons reçu votre candidature.",
            "classification": "APPLICATION_UPDATE",
            "confidence": 0.78,
            "matched_application_id": application_ids[1],
            "processing_state": "REVIEW",
            "reason": "Test de rendu compact",
            "extracted_links": [],
        }
    )

    monkeypatch.setattr(dashboard_common, "Settings", lambda: settings)
    dashboard_common.load_repository.clear()
    app = AppTest.from_file(PROJECT_DIR / "dashboard" / "page_applications.py")
    app.session_state["rocky_authenticated_user_id"] = user_id
    app.session_state["selected_email_id"] = 1
    app.run(timeout=30)

    assert not app.exception
    candidate_buttons = [
        button for button in app.button if button.label == "Voir le dossier"
    ]
    assert len(candidate_buttons) == 2
    score_threshold = next(
        slider for slider in app.slider if slider.label == "Seuil de score"
    )
    assert score_threshold.value == 0
    dashboard_common.load_repository.clear()


def test_application_score_threshold_keeps_unscored_dossiers_at_zero():
    """Un seuil positif filtre le score, tandis que zéro reste non restrictif."""
    applications = pd.DataFrame(
        [
            {
                "status": "DOSSIER PRÉPARÉ",
                "company_name": "Sans score",
                "job_title": "Analyste",
                "match_score": None,
                "prepared_at": "2026-08-31",
            },
            {
                "status": "CANDIDATURE ENVOYÉE",
                "company_name": "Score 60",
                "job_title": "Analyste",
                "match_score": 60,
                "prepared_at": "2026-08-30",
            },
            {
                "status": "CANDIDATURE ENVOYÉE",
                "company_name": "Score 80",
                "job_title": "Analyste",
                "match_score": 80,
                "prepared_at": "2026-08-29",
            },
        ]
    )
    base_filters = {
        "segment": "Toutes",
        "statuses": [],
        "query": "",
        "sort_order": "Plus récentes",
    }

    assert len(filter_applications(applications, minimum_score=0, **base_filters)) == 3
    assert list(
        filter_applications(applications, minimum_score=70, **base_filters)[
            "company_name"
        ]
    ) == ["Score 80"]
