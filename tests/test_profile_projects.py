"""Régressions ciblées sur les projets de profil et le recalcul global."""

from pathlib import Path

from sqlalchemy import text

from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.models import JobOffer, ProfileProject
from dashboard.rocky.projects import load_profile_projects
from dashboard.rocky.repository import RockyRepository


PROJECT_DIR = Path(__file__).resolve().parents[1]


def _repository(tmp_path: Path) -> RockyRepository:
    """Crée une base SQLite isolée sans toucher aux données PostgreSQL."""
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{tmp_path / 'profile-projects.db'}",
    )
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email, status) "
                "VALUES ('projects@example.test', 'ACTIVE') RETURNING id"
            )
        ).scalar_one()
    return RockyRepository(engine).for_user(user_id)


def test_mounted_storage_uses_profiles_without_a_second_data_folder(tmp_path):
    """Le volume ``/data`` représente déjà le dossier de données métier."""
    mounted = tmp_path / "mounted-data"
    settings = Settings(
        project_dir=tmp_path,
        storage_dir_override=str(mounted),
    )
    assert settings.profiles_dir == mounted / "profiles"
    assert settings.user_browser_profile_dir(7) == mounted / "users" / "7" / "browser_profile"

    local = Settings(project_dir=tmp_path, storage_dir_override="")
    assert local.profiles_dir == tmp_path / "data" / "profiles"


def test_valid_projects_file_repopulates_an_empty_database(tmp_path):
    """La préparation retrouve les projets après un changement de base."""
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil avec projets")
    settings = Settings(project_dir=tmp_path, storage_dir_override="")
    project_dir = settings.user_profiles_dir(repository.user_id) / str(profile_id)
    project_dir.mkdir(parents=True)
    (project_dir / "projects_fr.md").write_text(
        """# Projets
## Démo fiable
- Problématique : Comprendre un besoin réel.
- Stack : Python, SQL
- Livrable : Application de démonstration.
- Compétences : Analyse, communication
""",
        encoding="utf-8",
    )

    assert repository.fetch_profile_projects(profile_id) == []
    projects = load_profile_projects(profile_id, settings, repository)

    assert [project.name for project in projects] == ["Démo fiable"]
    persisted = repository.fetch_profile_projects(profile_id)
    assert [project.name for project in persisted] == ["Démo fiable"]


def test_projects_are_isolated_between_french_and_english_versions(tmp_path):
    """Une retouche EN ne peut plus remplacer les preuves françaises validées."""
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil bilingue")
    french = ProfileProject(
        slug="portfolio", name="Portfolio français", problem="Besoin client",
        deliverable="Site", sort_order=0,
    )
    english = ProfileProject(
        slug="portfolio", name="English portfolio", problem="Client need",
        deliverable="Website", sort_order=0,
    )
    repository.replace_profile_projects(profile_id, [french], "fr")
    repository.replace_profile_projects(profile_id, [english], "en")

    assert repository.fetch_profile_projects(profile_id, locale="fr")[0].name == "Portfolio français"
    assert repository.fetch_profile_projects(profile_id, locale="en")[0].name == "English portfolio"


def test_profile_match_recalculation_explains_incomplete_jobs(tmp_path):
    """Le bilan distingue clairement les annonces incomplètes."""
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil score détaillé")
    repository.insert_job(
        JobOffer(
            "Data Analyst",
            "Acme",
            "Aperçu trop court",
            description_is_full=False,
        ),
        profile_id,
    )

    result = repository.recalculate_profile_matches(profile_id)

    assert result == {
        "recalculated": 0,
        "skipped": 1,
        "incomplete": 1,
        "unavailable": 0,
    }


def test_recalculation_button_is_rendered_before_the_profile_form():
    """Le bouton global doit rester dans la barre d'actions haute."""
    page = (PROJECT_DIR / "dashboard" / "page_profiles.py").read_text(
        encoding="utf-8"
    )
    assert page.count('"Recalculer tous les scores"') == 1
    assert page.index('"Recalculer tous les scores"') < page.index(
        'with st.form(f"v2_edit_profile_{locale}")'
    )
