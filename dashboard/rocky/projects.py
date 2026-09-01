"""Fichier Markdown simple servant de source aux projets du profil.

Le format privilégie une édition humaine : chaque projet commence par un titre
``##`` puis utilise des champs ``Clé : valeur``. Le parseur refuse les doublons
et les projets sans faits suffisants afin d'éviter qu'un CV ne soit complété par
des inventions.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .errors import DocumentError
from .models import ProfileProject
from .llm import RockyLLM
from .repository import RockyRepository
from .text_utils import ensure_list, safe_slug


FIELD_NAMES = {
    "problem": "problem",
    "problematique": "problem",
    "problématique": "problem",
    "stack": "stack",
    "deliverable": "deliverable",
    "livrable": "deliverable",
    "details": "details",
    "détails": "details",
    "competences": "skills",
    "compétences": "skills",
    "skills": "skills",
    "resultats": "results",
    "résultats": "results",
    "results": "results",
}


def projects_path(
    settings: Settings,
    profile_id: int,
    user_id: int,
    locale: str = "fr",
) -> Path:
    """Retourne le Markdown privé de la version linguistique demandée."""
    if locale not in {"fr", "en"}:
        raise ValueError("La langue des projets doit être fr ou en.")
    return (
        settings.user_profiles_dir(user_id) / str(profile_id) / f"projects_{locale}.md"
    )


def _authenticated_user_id(repository: RockyRepository) -> int:
    if repository.user_id is None:
        raise PermissionError(
            "Un compte authentifié est requis pour gérer les projets."
        )
    return repository.user_id


def parse_projects_markdown(content: str) -> list[ProfileProject]:
    """Valide et transforme un fichier Markdown en projets typés."""
    sections = re.split(r"(?m)^##\s+", content)
    projects: list[ProfileProject] = []
    seen: set[str] = set()
    for order, section in enumerate(sections[1:]):
        lines = [line.rstrip() for line in section.strip().splitlines()]
        if not lines:
            continue
        name = lines[0].strip()
        slug = safe_slug(name, f"projet-{order + 1}")
        fields: dict[str, str] = {}
        current_key = ""
        for line in lines[1:]:
            match = re.match(r"^\s*[-*]?\s*([^:]+)\s*:\s*(.*)$", line)
            if match:
                normalized = match.group(1).strip().lower()
                normalized = FIELD_NAMES.get(normalized, "")
                if normalized:
                    current_key = normalized
                    fields[current_key] = match.group(2).strip()
                    continue
            if current_key and line.strip():
                fields[current_key] = (fields[current_key] + " " + line.strip()).strip()
        if slug in seen:
            raise DocumentError(f"Projet dupliqué dans projects.md : {name}")
        if not fields.get("problem") or not fields.get("deliverable"):
            raise DocumentError(
                f"Le projet « {name} » doit préciser Problématique et Livrable."
            )
        seen.add(slug)
        projects.append(
            ProfileProject(
                slug=slug,
                name=name,
                problem=fields.get("problem", ""),
                stack=tuple(ensure_list(fields.get("stack", ""))),
                deliverable=fields.get("deliverable", ""),
                details=fields.get("details", ""),
                skills=tuple(ensure_list(fields.get("skills", ""))),
                results=fields.get("results", ""),
                sort_order=order,
            )
        )
    if not projects:
        raise DocumentError("Ajoute au moins un projet sous un titre ##.")
    return projects


def sync_projects(
    profile_id: int,
    settings: Settings,
    repository: RockyRepository,
    locale: str = "fr",
) -> list[ProfileProject]:
    """Synchronise atomiquement le Markdown validé vers la base Rocky."""
    path = projects_path(
        settings, profile_id, _authenticated_user_id(repository), locale
    )
    if not path.is_file():
        raise DocumentError(f"Fichier projets absent : {path}")
    projects = parse_projects_markdown(path.read_text(encoding="utf-8"))
    repository.replace_profile_projects(profile_id, projects, locale)
    return projects


def _project_signature(project: ProfileProject) -> tuple[object, ...]:
    """Compare le contenu métier sans dépendre des identifiants de base."""
    return (
        project.slug,
        project.name,
        project.problem,
        project.stack,
        project.deliverable,
        project.details,
        project.skills,
        project.results,
        project.sort_order,
        project.is_active,
    )


def projects_to_markdown(projects: list[ProfileProject], locale: str = "fr") -> str:
    """Reconstruit le Markdown canonique à partir de projets persistés."""
    english = locale == "en"
    sections = ["# Profile projects" if english else "# Projets du profil", ""]
    for project in projects:
        sections.extend(
            [
                f"## {project.name}",
                f"- {'Problem' if english else 'Problématique'}: {project.problem}",
                f"- Stack : {', '.join(project.stack)}",
                f"- {'Deliverable' if english else 'Livrable'}: {project.deliverable}",
                f"- {'Skills' if english else 'Compétences'}: {', '.join(project.skills)}",
                f"- {'Details' if english else 'Détails'}: {project.details}",
                f"- {'Results' if english else 'Résultats'}: {project.results}",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def prefill_english_projects(
    profile_id: int,
    settings: Settings,
    repository: RockyRepository,
    llm: RockyLLM,
) -> list[ProfileProject]:
    """Duplique et traduit les preuves FR une seule fois vers l'espace EN.

    Les identifiants ``slug`` sont conservés : il s'agit du même projet, mais
    son texte est disponible pour les prompts et l'édition en anglais. Une
    version EN déjà enregistrée n'est jamais remplacée automatiquement.
    """
    existing = repository.fetch_profile_projects(profile_id, locale="en")
    if existing:
        return existing
    try:
        french = load_profile_projects(profile_id, settings, repository, locale="fr")
    except DocumentError:
        # Aucun projet français validé à dupliquer : l'éditeur EN affichera son
        # propre modèle vide, sans transformer ce cas normal en erreur.
        return []
    if not french or not llm.is_configured:
        return []
    values: list[str] = []
    for project in french:
        values.extend(
            [
                project.name,
                project.problem,
                *project.stack,
                project.deliverable,
                project.details,
                *project.skills,
                project.results,
            ]
        )
    translated = iter(llm.translate_blocks(values))
    english_projects: list[ProfileProject] = []
    for project in french:
        english_projects.append(
            ProfileProject(
                slug=project.slug,
                name=next(translated),
                problem=next(translated),
                stack=tuple(next(translated) for _ in project.stack),
                deliverable=next(translated),
                details=next(translated),
                skills=tuple(next(translated) for _ in project.skills),
                results=next(translated),
                sort_order=project.sort_order,
                is_active=project.is_active,
            )
        )
    content = projects_to_markdown(english_projects, locale="en")
    return save_profile_projects(profile_id, content, settings, repository, locale="en")


def load_profile_projects(
    profile_id: int,
    settings: Settings,
    repository: RockyRepository,
    locale: str = "fr",
) -> list[ProfileProject]:
    """Charge la source Markdown et synchronise son contenu validé."""
    stored = repository.fetch_profile_projects(profile_id, locale=locale)
    path = projects_path(
        settings, profile_id, _authenticated_user_id(repository), locale
    )
    if not path.is_file():
        raise DocumentError(f"Fichier projets absent : {path}")
    projects = parse_projects_markdown(path.read_text(encoding="utf-8"))
    if [_project_signature(item) for item in projects] != [
        _project_signature(item) for item in stored
    ]:
        repository.replace_profile_projects(profile_id, projects, locale)
    return projects


def save_profile_projects(
    profile_id: int,
    content: str,
    settings: Settings,
    repository: RockyRepository,
    locale: str = "fr",
) -> list[ProfileProject]:
    """Valide puis enregistre le Markdown avant sa synchronisation en base.

    La validation précède l'écriture afin qu'une erreur de saisie ne remplace
    pas le dernier fichier canonique utilisable par les candidatures.
    """
    projects = parse_projects_markdown(content)
    path = projects_path(
        settings, profile_id, _authenticated_user_id(repository), locale
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    repository.replace_profile_projects(profile_id, projects, locale)
    return projects


def default_projects_markdown(locale: str = "fr") -> str:
    """Fournit un exemple explicite sans inventer de contenu utilisateur."""
    if locale == "en":
        return """# Profile projects

<!-- Duplicate the block below to add a project. -->

## Project name
- Problem:
- Stack: Python, SQL
- Deliverable:
- Skills: Data analysis, communication
- Details: Context or method that is useful for a recruiter.
- Results: A measurable outcome only when it can be verified.
"""
    return """# Projets du profil

<!-- Duplique le bloc ci-dessous pour ajouter un projet. -->

## Nom du projet
- Problématique :
- Stack : Python, SQL
- Livrable :
- Compétences : Analyse de données, communication
- Détails : Contexte ou méthode utile au recruteur.
- Résultats : Résultat mesurable uniquement s'il est vérifiable.
"""


def ensure_projects_file(
    settings: Settings,
    profile_id: int,
    user_id: int,
    locale: str = "fr",
) -> Path:
    """Crée uniquement le modèle manquant, sans écraser un fichier renseigné."""
    path = projects_path(settings, profile_id, user_id, locale)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default_projects_markdown(locale), encoding="utf-8")
    return path
