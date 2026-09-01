from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from dashboard.rocky.application_statuses import (
    RESPONSE_STATUSES,
    can_apply_automatic_transition,
)
from dashboard.rocky.assistant_agent import plan_rocky_action
from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.gmail_service import (
    classify_and_match_email,
    classify_email,
    extract_job_links,
    match_application,
)
from dashboard.rocky.models import JobOffer, ProfileProject
from dashboard.rocky.projects import parse_projects_markdown
from dashboard.rocky.repository import RockyRepository


PROJECT_DIR = Path(__file__).resolve().parents[1]


def _repository(tmp_path: Path) -> RockyRepository:
    settings = Settings(database_url_override=f"sqlite:///{tmp_path / 'rocky_yolo.db'}")
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    return RockyRepository(engine)


def test_projects_markdown_requires_real_problem_and_deliverable():
    projects = parse_projects_markdown(
        """# Projets
## Démo fiable
- Problématique : Comprendre un besoin réel.
- Stack : Python, SQL
- Livrable : Application de démonstration.
- Compétences : Analyse, communication
"""
    )
    assert projects[0].slug == "demo_fiable"
    assert projects[0].stack == ("Python", "SQL")


def test_email_classification_and_unique_matching():
    decision = classify_email(
        "Votre candidature",
        "Nous avons retenu un autre profil et ne donnerons pas suite.",
    )
    assert decision.proposed_status == "REFUS"
    assert decision.confidence >= 0.9
    applications = pd.DataFrame(
        [
            {
                "id": 7,
                "company_name": "Acme Data",
                "job_title": "Data Analyst",
            },
            {
                "id": 8,
                "company_name": "Autre Société",
                "job_title": "Data Engineer",
            },
        ]
    )
    application_id, confidence, _ = match_application(
        applications,
        "recrutement@acme-data.fr",
        "Candidature Data Analyst chez Acme Data",
        "Nous avons bien reçu votre dossier.",
    )
    assert application_id == 7
    assert confidence > 0.9
    links = extract_job_links(
        "Voir https://www.indeed.com/viewjob?jk=123 et https://evil.example/x"
    )
    assert links == ["https://www.indeed.com/viewjob?jk=123"]


def test_employer_response_matching_ignores_original_job_platform():
    """La réponse directe de l'employeur doit retrouver sa fiche candidature."""
    applications = pd.DataFrame(
        [
            {
                "id": 17,
                "company_name": "emagine Consulting SARL",
                "job_title": "Machine Learning Engineer",
                "source_name": "Indeed",
            }
        ]
    )
    decision, application_id, confidence, reason = classify_and_match_email(
        applications,
        "emagine Careers <jobs@emagine.com>",
        "A quick update",
        "We will get back to you shortly.",
    )
    assert decision.classification == "APPLICATION_UPDATE"
    assert application_id == 17
    assert confidence >= 0.9
    assert "employeur de la fiche" in reason


def test_job_alert_flow_never_matches_an_existing_application():
    """Les alertes restent dans le flux déterministe d'import d'annonces."""
    applications = pd.DataFrame(
        [{"id": 17, "company_name": "Acme", "job_title": "Data Analyst"}]
    )
    decision, application_id, confidence, reason = classify_and_match_email(
        applications,
        "Indeed <alerts@indeed.com>",
        "Alerte emploi Acme",
        "De nouvelles offres d'emploi sont disponibles chez Acme.",
    )
    assert decision.classification == "JOB_ALERT"
    assert application_id is None
    assert confidence == 0.0
    assert reason == "Flux d'annonces déterministe"


def test_job_title_alone_cannot_match_an_employer_response():
    """Un intitulé commun ne remplace jamais l'employeur de la fiche."""
    applications = pd.DataFrame(
        [{"id": 17, "company_name": "Acme", "job_title": "Data Analyst"}]
    )
    application_id, confidence, _ = match_application(
        applications,
        "newsletter@example.org",
        "Une opportunité Data Analyst",
        "Découvrez les tendances du marché.",
    )
    assert application_id is None
    assert confidence == 0.0


def test_email_triage_separates_job_alerts_from_personal_noise():
    """Une synchronisation ne doit pas transformer toute la boîte en revue."""
    assert (
        classify_email(
            "Responsable IA – FIRST FINANCE SAS",
            "Votre parcours pourrait correspondre pour l'offre d'emploi suivante.",
        ).classification
        == "JOB_ALERT"
    )
    noise = classify_email(
        "Votre facture est disponible", "Merci de consulter votre espace client."
    )
    assert noise.classification == "NOISE"
    assert noise.confidence >= 0.9


def test_application_matching_rejects_generic_words_from_unrelated_mail():
    applications = pd.DataFrame(
        [{"id": 7, "company_name": "EY", "job_title": "Consultant junior Data"}]
    )
    application_id, confidence, _ = match_application(
        applications,
        "France TV <francetv@example.com>",
        "Une nouvelle vidéo est disponible",
        "Bonjour, découvrez notre programme du jour.",
    )
    assert application_id is None
    assert confidence == 0.0


def test_application_events_are_reversible(tmp_path):
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil test")
    job_id, _ = repository.insert_job(
        JobOffer("Analyste", "Acme", "Python SQL", description_is_full=True),
        profile_id,
    )
    application_id = repository.create_application(
        job_id, profile_id, "cv.pdf", None, "letter.pdf"
    )
    event_id = repository.update_application_status(
        application_id, "ENTRETIEN", source="TEST"
    )
    assert repository.fetch_application(application_id)["status"] == "ENTRETIEN"
    assert repository.revert_application_event(event_id)
    assert repository.fetch_application(application_id)["status"] == "DOSSIER PRÉPARÉ"
    assert not can_apply_automatic_transition("REFUS", "ENTRETIEN")


def test_manual_send_confirmation_syncs_application_and_job(tmp_path):
    """Le dernier jalon du parcours est audité et synchronise l'annonce."""
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil envoi")
    job_id, _ = repository.insert_job(
        JobOffer("Analyste", "Acme", "Python SQL", description_is_full=True),
        profile_id,
    )
    application_id = repository.create_application(
        job_id, profile_id, "cv.pdf", None, "letter.pdf"
    )
    event_id = repository.update_application_status(
        application_id,
        "CANDIDATURE ENVOYÉE",
        source="USER_CONFIRMATION",
        details={"confirmed_from": "application_preparation"},
    )
    assert event_id
    assert (
        repository.fetch_application(application_id)["status"] == "CANDIDATURE ENVOYÉE"
    )
    assert repository.fetch_job_offer(job_id).status == "CANDIDATURE ENVOYÉE"
    event = repository.fetch_application_events(application_id).iloc[0]
    assert event["source"] == "USER_CONFIRMATION"


def test_only_discarded_jobs_without_application_can_be_deleted(tmp_path):
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil suppression")
    removable_id, _ = repository.insert_job(
        JobOffer("Ancienne", "Acme", "Python", description_is_full=True),
        profile_id,
    )
    protected_id, _ = repository.insert_job(
        JobOffer("Suivie", "Acme", "Python", description_is_full=True),
        profile_id,
    )
    repository.update_jobs_status([removable_id, protected_id], "ÉCARTÉE")
    repository.create_application(
        protected_id, profile_id, "cv.pdf", None, "letter.pdf"
    )
    # Une action manuelle ultérieure peut écarter une annonce déjà liée : elle
    # doit rester protégée malgré ce statut final.
    repository.update_job_status(protected_id, "ÉCARTÉE")
    result = repository.delete_discarded_jobs([removable_id, protected_id])
    assert result == {"deleted": 1, "not_discarded": 0, "linked_to_application": 1}
    assert repository.fetch_job(removable_id) is None
    assert repository.fetch_job(protected_id) is not None


def test_profile_match_recalculation_updates_complete_jobs(tmp_path):
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil score")
    repository.add_skill(profile_id, "Python", "technical", "avancé", 3, True)
    job_id, _ = repository.insert_job(
        JobOffer(
            "Data Analyst",
            "Acme",
            "Description complète Python et SQL",
            description_is_full=True,
        ),
        profile_id,
    )
    result = repository.recalculate_profile_matches(profile_id)
    assert result["recalculated"] == 1
    row = repository.fetch_jobs(profile_id).iloc[0]
    assert float(row["match_score"]) > 0
    assert int(row["id"]) == job_id


def test_rocky_actions_are_constrained():
    action = plan_rocky_action("Candidature #31 en entretien")
    assert action.action == "UPDATE_APPLICATION_STATUS"
    assert action.requires_confirmation
    assert plan_rocky_action("DROP TABLE applications").action == "ANSWER"


def test_acknowledgements_count_as_application_responses():
    """Un accusé réception est un retour, même sans traitement ATS final."""
    assert "ACCUSÉ DE RÉCEPTION" in RESPONSE_STATUSES


def test_stale_new_jobs_are_aged_or_discarded_without_touching_followed_jobs(
    tmp_path,
):
    """La règle calendrier ne s'applique qu'aux annonces restées nouvelles."""
    repository = _repository(tmp_path)
    profile_id = repository.create_profile("Profil ancienneté")
    reference = date(2026, 8, 31)

    def add_offer(title: str, age_days: int | None, status: str = "NOUVELLE"):
        publication_date = (
            reference - timedelta(days=age_days) if age_days is not None else None
        )
        job_id, _ = repository.insert_job(
            JobOffer(
                title,
                "Acme",
                "Description complète",
                source_url=f"https://jobs.example/{title}",
                publication_date=publication_date,
                status=status,
                description_is_full=True,
            ),
            profile_id,
        )
        return job_id

    age_8 = add_offer("Huit jours", 8)
    age_14 = add_offer("Quatorze jours", 14)
    age_15 = add_offer("Quinze jours", 15)
    recent = add_offer("Sept jours", 7)
    followed = add_offer("Déjà étudiée", 20, "À ÉTUDIER")
    undated = add_offer("Sans date", None)

    summary = repository.apply_stale_new_job_policy(reference)

    assert summary == {"ancient_count": 2, "discarded_count": 1}
    assert repository.fetch_job_offer(age_8).status == "ANCIENNE"
    assert repository.fetch_job_offer(age_14).status == "ANCIENNE"
    assert repository.fetch_job_offer(age_15).status == "ÉCARTÉE"
    assert repository.fetch_job_offer(recent).status == "NOUVELLE"
    assert repository.fetch_job_offer(followed).status == "À ÉTUDIER"
    assert repository.fetch_job_offer(undated).status == "NOUVELLE"
