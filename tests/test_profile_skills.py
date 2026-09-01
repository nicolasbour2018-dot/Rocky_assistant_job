from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.rocky.profile_skills import (
    add_missing_inferred_skills,
    infer_profile_skills_from_cv,
)


def _create_cv(path: Path) -> None:
    canvas_module = pytest.importorskip("reportlab.pdfgen.canvas")
    document = canvas_module.Canvas(str(path))
    text = document.beginText(45, 805)
    text.setLeading(14)
    for line in (
        "Amina Diallo - Data Analyst",
        "amina@example.org - 06 11 22 33 44",
        "COMPETENCES",
        "Expertise en Python",
        "Maitrise avancee de SQL",
        "Notions de Docker",
        "Pandas",
        "EXPERIENCE PROFESSIONNELLE",
        "Data Analyst - Entreprise Exemple - 2022 a 2025",
        "Analyse de donnees et reporting pour les equipes metier.",
        "FORMATION",
        "Master Statistiques - Universite Exemple - 2022",
    ):
        text.textLine(line)
    document.drawText(text)
    document.save()


def test_cv_skill_detection_reuses_taxonomy_and_estimates_simple_levels(tmp_path):
    cv_path = tmp_path / "cv.pdf"
    _create_cv(cv_path)

    detected = {skill.name: skill for skill in infer_profile_skills_from_cv(cv_path)}

    assert detected["Python"].level == "expert"
    assert detected["SQL"].level == "avancé"
    assert detected["Docker"].level == "débutant"
    assert detected["Pandas"].level == "intermédiaire"
    assert detected["Python"].category == "technical"


class _Repository:
    def __init__(self):
        self.skills = [
            {
                "skill_name": "Python",
                "skill_category": "technical",
                "skill_level": "débutant",
            }
        ]

    def fetch_skills(self, _profile_id):
        return self.skills

    def add_skill(self, _profile_id, name, category, level, years, core):
        self.skills.append(
            {
                "skill_name": name,
                "skill_category": category,
                "skill_level": level,
                "years_experience": years,
                "is_core_skill": core,
            }
        )


def test_automatic_addition_preserves_existing_manual_skill_and_level(tmp_path):
    cv_path = tmp_path / "cv.pdf"
    _create_cv(cv_path)
    inferred = infer_profile_skills_from_cv(cv_path)
    repository = _Repository()

    added, skipped = add_missing_inferred_skills(repository, 1, inferred)

    python = next(item for item in repository.skills if item["skill_name"] == "Python")
    assert python["skill_level"] == "débutant"
    assert any(item["skill_name"] == "SQL" for item in repository.skills)
    assert added == len(inferred) - 1
    assert skipped == 1
