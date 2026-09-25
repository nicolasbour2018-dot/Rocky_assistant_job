from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from rocky.profil.import_file import ImportFileError, parse_import, read_import_file
from rocky.profil.model import Contract, ExperienceKind, LanguageLevel, SkillLevel


def valid_file() -> dict[str, Any]:
    return {
        "format": "rocky-profil/1",
        "identity": {
            "full_name": "Nicolas Exemple",
            "city": "Paris",
            "headline": {"fr": "Data scientist", "en": "Data scientist"},
        },
        "preferences": {
            "contracts": ["permanent", "fixed_term"],
            "min_salary_eur": 45000,
        },
        "skills": [
            {
                "label": {"fr": "NLP", "en": "Natural Language Processing (NLP)"},
                "aliases": ["Traitement du langage naturel (NLP)"],
                "category": "technical",
                "level": "advanced",
                "is_key": True,
            },
            {"label": {"fr": "Curiosité"}, "category": "soft"},
        ],
        "languages": [{"code": "en", "level": "c1"}],
        "experiences": [
            {
                "kind": "education",
                "title": {"fr": "Master data science"},
                "organisation": "Université",
                "start": "2023-09",
                "end": "2024-09",
                "bullets": {"fr": ["Mémoire en NLP"]},
                "skills": ["NLP"],
            }
        ],
        "projects": [
            {
                "name": {"fr": "Finance connectée", "en": "Connected finance"},
                "problem": {"fr": "Suivre ses dépenses"},
                "stack": ["Python"],
                "skills": ["nlp"],
            }
        ],
        "tracks": [],
    }


def test_a_valid_file_becomes_a_profile() -> None:
    imported = parse_import(valid_file())

    assert imported.identity.full_name == "Nicolas Exemple"
    assert imported.identity.headline.en == "Data scientist"
    assert imported.preferences.contracts == (Contract.PERMANENT, Contract.FIXED_TERM)
    nlp, soft = imported.skills
    assert nlp.level is SkillLevel.ADVANCED
    assert nlp.is_key
    assert soft.label.en is None
    assert imported.languages[0].level is LanguageLevel.C1
    [experience] = imported.experiences
    assert experience.content.kind is ExperienceKind.EDUCATION
    assert experience.content.end == date(2024, 9, 1)
    assert experience.skills == ("NLP",)
    assert imported.projects[0].content.name.en == "Connected finance"


def test_every_problem_is_reported_with_its_field() -> None:
    data = valid_file()
    data["skills"][0]["category"] = "hard"
    data["skills"][1]["categorie"] = "soft"
    data["experiences"][0]["start"] = "septembre"
    data["languages"] = {"code": "en"}

    with pytest.raises(ImportFileError) as caught:
        parse_import(data)

    assert caught.value.problems == [
        "skills[0] : Catégorie de compétence inconnue.",
        "skills[1].categorie : clé inconnue.",
        "languages : doit être une liste [ … ].",
        "experiences[0] : Le début doit être un mois (AAAA-MM).",
    ]


def test_items_left_to_review_block_the_import() -> None:
    data = valid_file()
    data["to_review"] = ["Domaine cible : Finance"]

    with pytest.raises(ImportFileError, match="restent à relire"):
        parse_import(data)


def test_the_format_is_checked() -> None:
    data = valid_file()
    data["format"] = "rocky-profil/0"

    with pytest.raises(ImportFileError, match="format"):
        parse_import(data)


def test_an_identity_is_required() -> None:
    data = valid_file()
    del data["identity"]

    with pytest.raises(ImportFileError, match="identity : doit être un objet"):
        parse_import(data)


def test_broken_json_says_where(tmp_path: Path) -> None:
    path = tmp_path / "profil.json"
    path.write_text('{"format": "rocky-profil/1",\n "identity": }', encoding="utf-8")

    with pytest.raises(ImportFileError, match="ligne 2"):
        read_import_file(path)


def test_a_file_is_read_as_utf8(tmp_path: Path) -> None:
    path = tmp_path / "profil.json"
    path.write_text(json.dumps(valid_file(), ensure_ascii=False), encoding="utf-8")

    assert read_import_file(path).skills[1].label.fr == "Curiosité"
