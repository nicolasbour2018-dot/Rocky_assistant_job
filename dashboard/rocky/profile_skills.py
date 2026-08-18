"""Détection simple des compétences d'un profil à partir de son CV PDF."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dashboard.job_analysis import (
    BUSINESS_SKILLS,
    SKILL_ALIASES,
    SOFT_SKILLS,
    TECHNICAL_SKILLS,
    analyze_job,
)

from .ats import extract_pdf_text, repair_spaced_pdf_text
from .text_utils import normalize_text


@dataclass(frozen=True)
class InferredProfileSkill:
    name: str
    category: str
    level: str
    mentions: int


def _forms(skill: str) -> tuple[str, ...]:
    values = [skill, *SKILL_ALIASES.get(skill, [])]
    return tuple(dict.fromkeys(normalize_text(value) for value in values if value))


def _occurrences(text: str, forms: tuple[str, ...]) -> list[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for form in forms:
        pattern = r"(?<![a-z0-9])" + re.escape(form) + r"(?![a-z0-9])"
        found.update((match.start(), match.end()) for match in re.finditer(pattern, text))
    return sorted(found)


def _level(text: str, occurrences: list[tuple[int, int]]) -> str:
    surroundings = [
        (
            text[max(0, start - 55):start].rstrip(),
            text[end:min(len(text), end + 30)].lstrip(),
        )
        for start, end in occurrences
    ]
    if any(
        before.endswith(marker) or after.startswith(marker)
        for before, after in surroundings
        for marker in (
            "niveau expert en",
            "expertise en",
            "expertise de",
            "expert en",
            "experte en",
            "expert",
        )
    ):
        return "expert"
    if any(
        before.endswith(marker) or after.startswith(marker)
        for before, after in surroundings
        for marker in (
            "maitrise avancee de",
            "maitrise avancee du",
            "maitrise de",
            "maitrise du",
            "maitrise des",
            "utilisation avancee de",
            "avance",
        )
    ):
        return "avancé"
    if any(
        before.endswith(marker) or after.startswith(marker)
        for before, after in surroundings
        for marker in (
            "notions de",
            "notions en",
            "initiation a",
            "debutant en",
            "debutante en",
            "debutant",
        )
    ):
        return "débutant"
    return "avancé" if len(occurrences) >= 3 else "intermédiaire"


def _category(skill: str) -> str:
    if skill in TECHNICAL_SKILLS:
        return "technical"
    if skill in BUSINESS_SKILLS:
        return "business"
    if skill in SOFT_SKILLS:
        return "soft"
    return "business"


def infer_profile_skills_from_cv(cv_path: str | Path) -> tuple[InferredProfileSkill, ...]:
    """Lit le PDF réel et applique la taxonomie générique déjà utilisée par Rocky."""
    raw_text, _, _ = extract_pdf_text(cv_path)
    repaired_text, _ = repair_spaced_pdf_text(raw_text)
    normalized = normalize_text(repaired_text)
    skills = analyze_job("", repaired_text)["all_skills"]
    inferred = []
    for skill in skills:
        occurrences = _occurrences(normalized, _forms(skill))
        inferred.append(
            InferredProfileSkill(
                name=skill,
                category=_category(skill),
                level=_level(normalized, occurrences),
                mentions=len(occurrences),
            )
        )
    return tuple(inferred)


def add_missing_inferred_skills(
    repository: Any,
    profile_id: int,
    inferred: tuple[InferredProfileSkill, ...],
) -> tuple[int, int]:
    """Ajoute les absentes sans écraser les saisies manuelles existantes."""
    existing = {
        normalize_text(skill.get("skill_name"))
        for skill in repository.fetch_skills(profile_id)
    }
    added = 0
    skipped = 0
    for skill in inferred:
        key = normalize_text(skill.name)
        if key in existing:
            skipped += 1
            continue
        repository.add_skill(
            profile_id,
            skill.name,
            skill.category,
            skill.level,
            None,
            False,
        )
        existing.add(key)
        added += 1
    return added, skipped
