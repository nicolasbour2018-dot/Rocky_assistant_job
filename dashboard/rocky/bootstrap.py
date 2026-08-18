"""Initialisation pédagogique du premier profil Rocky.

Ce module contient les seules valeurs de démarrage issues du CV fourni. Il est
appelé aussi bien par le script local que par le Space Hugging Face afin que les
deux environnements démarrent avec le même profil, sans dupliquer la logique.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .letters import save_profile_cv
from .models import CandidateProfile
from .repository import RockyRepository
from .text_utils import project_relative


DEFAULT_SKILLS = [
    ("Python", "technical", True),
    ("SQL", "technical", True),
    ("Pandas", "technical", True),
    ("NumPy", "technical", False),
    ("AWS", "technical", False),
    ("Scikit-learn", "technical", True),
    ("LangChain", "technical", False),
    ("n8n", "technical", False),
    ("FastAPI", "technical", False),
    ("Docker", "technical", False),
    ("GitHub", "technical", False),
    ("Streamlit", "technical", True),
    ("Machine Learning", "technical", True),
    ("LLM", "technical", False),
    ("RAG", "technical", False),
    ("API REST", "technical", False),
    ("Data Visualisation", "business", True),
    ("Analyse statistique", "business", True),
    ("Automatisation", "business", True),
    ("Pédagogie", "soft", True),
    ("Rigueur", "soft", True),
    ("Autonomie", "soft", True),
]


def bootstrap_default_profile(
    settings: Settings,
    repository: RockyRepository,
    cv_source: Path | None = None,
) -> tuple[CandidateProfile, bool]:
    """Crée le profil initial s'il n'existe pas et l'active.

    Retourne le profil prêt à l'emploi et un booléen qui vaut True uniquement
    lorsque le profil vient d'être créé.
    """
    profiles = repository.fetch_profiles()
    created = profiles.empty
    if created:
        profile_id = repository.create_profile(
            "Data Analyst / Data Scientist",
            (
                "Profil en reconversion vers la data, combinant rigueur "
                "scientifique, analyse de données, pédagogie et expérience "
                "de projets Python, machine learning et IA générative."
            ),
        )
        profile = repository.fetch_profile(profile_id)
        if profile is None:
            raise RuntimeError("Le profil créé est introuvable.")
        profile.target_job_titles = [
            "Data Analyst",
            "Data Scientist Junior",
            "Business Intelligence Analyst",
            "Chargé de projet Data et Automatisation",
        ]
        profile.preferred_contracts = ["CDI", "CDD", "VIE"]
        repository.update_profile(profile)
        for name, category, is_core in DEFAULT_SKILLS:
            repository.add_skill(
                profile_id,
                name,
                category,
                is_core=is_core,
            )
    else:
        active = repository.fetch_active_profile()
        profile_id = active.id if active else int(profiles.iloc[0]["id"])

    repository.set_active_profile(profile_id)
    profile = repository.fetch_profile(profile_id)
    if profile is None:
        raise RuntimeError("Le profil actif est introuvable.")

    source = cv_source or settings.project_dir / "CV Nicolas Bour.pdf"
    if not profile.cv_path and source.is_file():
        cv_path = save_profile_cv(settings, profile_id, source.read_bytes())
        repository.save_cv_path(
            profile_id, project_relative(cv_path, settings.project_dir)
        )
        profile = repository.fetch_profile(profile_id) or profile
    return profile, created
