from pathlib import Path

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


PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_discarded_jobs_are_hidden_without_being_deleted():
    import pandas as pd

    jobs = pd.DataFrame(
        [
            {"id": 1, "status": "NOUVELLE"},
            {"id": 2, "status": "ÉCARTÉE"},
            {"id": 3, "status": "INCOMPLÈTE"},
        ]
    )
    visible = dashboard_common.visible_jobs(jobs)
    assert visible["id"].tolist() == [1, 3]
    assert jobs["id"].tolist() == [1, 2, 3]


def test_enrichment_queue_contains_only_incomplete_status():
    import pandas as pd

    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "status": "INCOMPLÈTE",
                "description_is_full": False,
                "publication_date": None,
            },
            {"id": 2, "status": "RETENUE", "description_is_full": False},
            {"id": 3, "status": "REFUS", "description_is_full": False},
            {"id": 4, "status": "ÉCARTÉE", "description_is_full": False},
            {"id": 5, "status": "INCOMPLÈTE", "description_is_full": True},
        ]
    )
    selected = dashboard_common.jobs_to_enrich(jobs)
    assert selected["id"].tolist() == [1]
    assert dashboard_common.metric_counts(jobs)["incomplete"] == 1


def test_recent_metric_uses_the_selected_duration():
    import pandas as pd
    from datetime import date, timedelta

    jobs = pd.DataFrame(
        [
            {
                "id": 1,
                "status": "NOUVELLE",
                "description_is_full": True,
                "publication_date": date.today(),
            },
            {
                "id": 2,
                "status": "NOUVELLE",
                "description_is_full": True,
                "publication_date": date.today() - timedelta(days=2),
            },
            {
                "id": 3,
                "status": "NOUVELLE",
                "description_is_full": True,
                "publication_date": date.today() - timedelta(days=10),
            },
        ]
    )

    assert dashboard_common.metric_counts(jobs, recent_days=1)["recent"] == 1
    assert dashboard_common.metric_counts(jobs, recent_days=3)["recent"] == 2
    assert dashboard_common.metric_counts(jobs, recent_days=7)["recent"] == 2
    assert dashboard_common.metric_counts(jobs, recent_days=30)["recent"] == 3


def test_stale_dataframe_selection_positions_are_ignored():
    import pandas as pd

    frame = pd.DataFrame([{"id": 41}, {"id": 42}])

    assert dashboard_common.selected_row_ids(frame, [0, 8, -1, 1, 1]) == [41, 42]


def test_matching_summary_separates_categories_and_near_matches():
    import pandas as pd

    row = pd.Series(
        {
            "match_score": 76.0,
            "match_breakdown": {
                "skills": {
                    "raw_score": 33.3,
                    "weight": 55,
                    "profile_skills": [
                        "Python",
                        "PowerBI",
                        "Communication orale",
                    ],
                    "detected_skills": [
                        "Python",
                        "Power BI",
                        "Communication",
                    ],
                    "matched_skills": ["Python"],
                    "missing_skills": ["Power BI", "Communication"],
                }
            },
            "match_strengths": [],
            "match_gaps": [],
            "required_skills": [],
        }
    )

    summary = dashboard_common.matching_category_summary(row)

    assert summary is not None
    assert summary["technical"]["score"] == 50.0
    assert summary["transversal"]["score"] == 0.0
    assert {item["skill"] for item in summary["to_review"]} == {
        "Power BI",
        "Communication",
    }
    assert all(item["close_profile_skill"] for item in summary["to_review"])


def test_rocky_v2_pages_start_with_existing_data(tmp_path, monkeypatch):
    database_path = tmp_path / "rocky_variants.db"
    settings = Settings(database_url_override=f"sqlite:///{database_path}")
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    profile_id = repository.create_profile("Profil test")
    repository.set_active_profile(profile_id)
    repository.add_skill(
        profile_id,
        "Python",
        "technical",
        "avancé",
        3.5,
        True,
    )
    repository.insert_job(
        JobOffer(
            "Data Analyst",
            "Rocky Data",
            "Description complète Python SQL",
            source_name="Adzuna",
            source_url="https://jobs.example/42",
            city="Paris",
            remote_policy="Hybride",
            salary_min=40_000,
            salary_max=45_000,
            status="À ÉTUDIER",
            description_is_full=True,
        ),
        profile_id,
    )
    repository.insert_job(
        JobOffer(
            "Annonce archivée",
            "À ne pas afficher",
            "Aperçu incomplet...",
            source_name="Apec",
            source_url="https://jobs.example/archived",
            status="ÉCARTÉE",
        ),
        profile_id,
    )
    repository.insert_job(
        JobOffer(
            "Aperçu retenu",
            "Pas dans la file",
            "Aperçu incomplet...",
            source_name="Apec",
            source_url="https://jobs.example/retained-preview",
            status="RETENUE",
        ),
        profile_id,
    )
    repository.insert_job(
        JobOffer(
            "BI Analyst",
            "Rocky BI",
            "Aperçu...",
            source_name="Apec",
            source_url="https://jobs.example/43",
            city="Lyon",
            status="INCOMPLÈTE",
        ),
        profile_id,
    )

    monkeypatch.setattr(dashboard_common, "Settings", lambda: settings)
    dashboard_common.load_repository.clear()
    for filename in (
        "dashboard_v2.py",
        "dashboard_b.py",
        "page_all_jobs.py",
        "page_enrichment.py",
        "page_job_detail.py",
        "page_import_url.py",
        "page_profiles.py",
        "page_monitoring.py",
    ):
        app = AppTest.from_file(PROJECT_DIR / "dashboard" / filename)
        app.run(timeout=30)
        assert not app.exception, filename
        assert not any(
            "Annonce archivée" in item.value for item in app.subheader
        ), filename
        if filename == "dashboard_b.py":
            assert any(
                button.label.startswith("Tout le flux ·")
                for button in app.button
            )
            assert any(
                button.label == "À enrichir · 1" for button in app.button
            )
            assert any(
                slider.label == "Seuil minimal de matching"
                and slider.value == 70
                for slider in app.slider
            )
            assert app.subheader[0].value == "Suggestions · 0 résultat(s)"
            assert not any(
                item.value == "BI Analyst" for item in app.subheader
            )
        if filename == "page_all_jobs.py":
            assert app.selectbox[0].label == "Tranche de 50 annonces"
            assert len(app.dataframe[0].value) == 4
            assert "Annonce archivée" in set(
                app.dataframe[0].value["job_title"]
            )
        if filename == "page_enrichment.py":
            assert not any(
                "Aperçu retenu" in item.value for item in app.subheader
            )
            assert any(
                button.label == "Tout enrichir (1)" for button in app.button
            )
            assert any(
                button.label == "Appliquer (0)" and button.disabled
                for button in app.button
            )
            assert any(
                select.label == "Trier par" for select in app.selectbox
            )
            assert "city" in app.dataframe[0].value.columns
        if filename == "page_profiles.py":
            assert any(
                "3,5 ans d’expérience" in item.value for item in app.markdown
            )
            assert app.get("popover")
    dashboard_common.load_repository.clear()


def test_manual_watch_uses_the_session_threshold(tmp_path, monkeypatch):
    database_path = tmp_path / "rocky_watch_threshold.db"
    settings = Settings(
        database_url_override=f"sqlite:///{database_path}",
        match_threshold=70,
    )
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    profile_id = repository.create_profile("Profil seuil")
    repository.set_active_profile(profile_id)
    captured_thresholds = []

    class FakeWatchService:
        def __init__(self, watch_settings, _repository, _sources):
            captured_thresholds.append(watch_settings.match_threshold)

        def run(self):
            return {
                "inserted_count": 0,
                "duplicate_count": 0,
                "incomplete_description_count": 0,
            }

    monkeypatch.setattr(dashboard_common, "Settings", lambda: settings)
    monkeypatch.setattr(dashboard_common, "WatchService", FakeWatchService)
    monkeypatch.setattr(dashboard_common, "build_watch_sources", lambda _: [])
    dashboard_common.load_repository.clear()
    app = AppTest.from_file(PROJECT_DIR / "dashboard" / "dashboard_b.py")
    app.run(timeout=30)

    threshold = next(
        slider
        for slider in app.slider
        if slider.label == "Seuil minimal de matching"
    )
    threshold.set_value(55)
    app.run(timeout=30)
    next(
        button for button in app.button if button.label == "Lancer la veille"
    ).click()
    app.run(timeout=30)

    assert captured_thresholds == [55]
    assert any("seuil 55 %" in caption.value for caption in app.caption)
    dashboard_common.load_repository.clear()


def test_job_detail_page_reuses_v11_actions(tmp_path, monkeypatch):
    database_path = tmp_path / "rocky_job_detail.db"
    settings = Settings(database_url_override=f"sqlite:///{database_path}")
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    profile_id = repository.create_profile("Profil test")
    repository.set_active_profile(profile_id)
    job_id, _ = repository.insert_job(
        JobOffer(
            "Data Analyst",
            "Rocky Data",
            "Description complète Python SQL et communication",
            source_name="Adzuna",
            source_url="https://jobs.example/source/42",
            application_url="https://jobs.example/apply/42",
            city="Paris",
            description_is_full=True,
        ),
        profile_id,
    )

    monkeypatch.setattr(dashboard_common, "Settings", lambda: settings)
    dashboard_common.load_repository.clear()
    app = AppTest.from_file(
        PROJECT_DIR / "dashboard" / "page_job_detail.py"
    )
    app.session_state["selected_job_id"] = job_id
    app.run(timeout=30)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Annonce et modifications",
        "Matching détaillé",
        "Lettre et candidature",
    ]
    button_labels = {button.label for button in app.button}
    assert "Recalculer le matching" in button_labels
    assert "Créer DOCX + PDF + copie du CV" in button_labels
    assert "Modifier l’annonce" in button_labels
    assert "Lancer l’ATS historique (lecture brute)" not in button_labels
    assert "Lancer l’ATS V2 (recommandé)" not in button_labels
    links = app.get("link_button")
    assert "Postuler" in button_labels
    assert any(
        link.label == "Ouvrir le site de candidature" for link in links
    )
    dashboard_common.load_repository.clear()


def test_cockpit_metrics_filter_corresponding_cards(tmp_path, monkeypatch):
    database_path = tmp_path / "rocky_metric.db"
    settings = Settings(database_url_override=f"sqlite:///{database_path}")
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    profile_id = repository.create_profile("Profil test")
    repository.set_active_profile(profile_id)
    full_id, _ = repository.insert_job(
        JobOffer(
            "Data Analyst",
            "Complet",
            "Description complète Python SQL",
            source_name="Adzuna",
            source_url="https://jobs.example/full",
            status="À ÉTUDIER",
            description_is_full=True,
        ),
        profile_id,
    )
    repository.save_match(full_id, profile_id, MatchResult(82, {}))
    incomplete_id, _ = repository.insert_job(
        JobOffer(
            "BI Analyst",
            "Incomplet",
            "Aperçu...",
            source_name="Apec",
            source_url="https://jobs.example/preview",
            status="INCOMPLÈTE",
        ),
        profile_id,
    )
    monkeypatch.setattr(dashboard_common, "Settings", lambda: settings)
    dashboard_common.load_repository.clear()
    app = AppTest.from_file(PROJECT_DIR / "dashboard" / "dashboard_b.py")
    app.session_state["cockpit_view"] = "mine"
    app.run(timeout=30)
    minimum_score = next(
        slider for slider in app.slider if slider.label == "Score min."
    )
    assert minimum_score.min == 0
    assert minimum_score.max == 100
    assert minimum_score.step == 5
    my_status = next(
        select for select in app.selectbox if select.key == "cockpit_my_status"
    )
    assert my_status.value == "À ÉTUDIER"
    assert any(
        item.value == "Data Analyst" for item in app.subheader
    )
    status_select = next(
        select
        for select in app.selectbox
        if select.key == f"card_status_select_{full_id}"
    )
    status_select.select("ÉCARTÉE")
    save_status = next(
        button
        for button in app.button
        if button.key == f"card_status_save_{full_id}"
    )
    save_status.click().run(timeout=30)
    assert not any(item.value == "Data Analyst" for item in app.subheader)
    dashboard_common.load_repository.clear()
