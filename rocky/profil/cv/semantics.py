"""What each text block of an imported CV is, and what the CV says: one language model call (decision D2, Q14,
Q20, Q21).

The model receives the extracted texts and their positions, never the file. It names the role of every block
(the geometry stays Rocky's), translates the fixed texts of the template into English, and copies the CV into
profile proposals. Its answer is checked field by field: a block without a known role refuses the template.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from rocky.profil.cv.pdf_page import Block


class Role(StrEnum):
    NAME = "name"
    TITLE = "title"
    AGE = "age"
    HEADLINE = "headline"
    EMAIL = "email"
    PHONE = "phone"
    CITY = "city"
    HEADING = "heading"  # a fixed section title (« EXPÉRIENCES »)
    FIXED = "fixed"  # any other text of the design, kept as it is (« Designed for… »)
    GROUPS = "groups"  # technical skills with their group names
    TRANSVERSAL = "transversal"
    LANGUAGES = "languages"
    HOBBIES = "hobbies"
    PROJECT_NAME = "project_name"
    PROJECT_PROBLEM = "project_problem"
    PROJECT_STACK = "project_stack"
    PROJECT_WORK = "project_work"
    PROJECT_RESULTS = "project_results"
    EXPERIENCES = "experiences"
    EDUCATION = "education"


PROJECT_ROLES = frozenset(
    {
        Role.PROJECT_NAME,
        Role.PROJECT_PROBLEM,
        Role.PROJECT_STACK,
        Role.PROJECT_WORK,
        Role.PROJECT_RESULTS,
    }
)
TRANSLATED_ROLES = frozenset({Role.HEADING, Role.FIXED}) | PROJECT_ROLES - {
    Role.PROJECT_NAME
}

INSTRUCTIONS = """Tu lis un CV d'une page, découpé en lignes de texte numérotées (position en points depuis le \
coin haut gauche). Deux tâches, sans jamais inventer ni reformuler un texte :
1. Donne le rôle de CHAQUE ligne (liste « roles »). Rôles :
- name, title (intitulé de poste sous le nom), age, headline (paragraphe de profil), email, phone, city ;
- heading : titre de section du gabarit (« EXPÉRIENCES », « C O N T A C T ») ; fixed : autre texte du design, \
identique pour toute personne (mention en pied de page) ;
- groups : compétences techniques et leurs noms de groupe ; transversal : compétences transversales ; languages ; \
hobbies (loisirs) ;
- project_name, project_problem, project_stack, project_work (livrable, réalisation), project_results : « index » est \
le numéro du projet (0, 1, 2… de gauche à droite) ;
- experiences : emplois (intitulé, employeur, puces) ; education : diplômes, formations, certifications, écoles, et \
leurs puces. Une ligne de la colonne des formations est education, jamais experiences.
Pour heading et fixed, « en » est la traduction anglaise, dans la même casse et la même typographie ; un titre \
sur plusieurs lignes est traduit en entier sur sa première ligne, « en » restant vide pour les suivantes. \
Pour project_problem, project_stack, project_work et project_results, « label » est l'étiquette qui ouvre la ligne \
(« Problématique », sans les deux-points) et « en » sa traduction anglaise ; vides si la ligne n'en a pas.
2. Recopie le contenu du CV dans « profile », texte pour texte (dates : années seules)."""

_TEXT = {"type": "string"}
_TEXTS = {"type": "array", "items": _TEXT}

SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "roles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "role": {"type": "string", "enum": [role.value for role in Role]},
                    "index": {"type": "integer"},
                    "label": _TEXT,
                    "en": _TEXT,
                },
                "required": ["id", "role"],
            },
        },
        "profile": {
            "type": "object",
            "properties": {
                "full_name": _TEXT,
                "title": _TEXT,
                "headline": _TEXT,
                "email": _TEXT,
                "phone": _TEXT,
                "city": _TEXT,
                "skill_groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": _TEXT, "skills": _TEXTS},
                        "required": ["name", "skills"],
                    },
                },
                "transversal": _TEXTS,
                "languages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": _TEXT,
                            "level": {
                                "type": "string",
                                "enum": ["a1", "a2", "b1", "b2", "c1", "c2", "native"],
                            },
                        },
                        "required": ["name", "level"],
                    },
                },
                "hobbies": _TEXTS,
                "experiences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["job", "education"]},
                            "title": _TEXT,
                            "organisation": _TEXT,
                            "place": _TEXT,
                            "start_year": {"type": "integer"},
                            "end_year": {"type": "integer"},
                            "bullets": _TEXTS,
                        },
                        "required": ["kind", "title", "organisation", "start_year"],
                    },
                },
                "projects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": _TEXT,
                            "problem": _TEXT,
                            "stack": _TEXTS,
                            "work": _TEXT,
                            "results": _TEXT,
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["full_name"],
        },
    },
    "required": ["roles", "profile"],
}


class SemanticsError(Exception):
    """The answer cannot be used; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BlockRole:
    block_id: int
    role: Role
    index: int = 0
    label: str = ""  # lead label of a project part, as written (« Problématique »)
    label_en: str = ""
    text_en: str = ""  # English of a heading or a fixed text


def prompt(blocks: Sequence[Block]) -> str:
    """The texts and positions of the lines: all the model sees of the CV."""
    lines = []
    for block in blocks:
        box = block.box
        text = " ".join(line.text.strip() for line in block.lines)
        lines.append(
            f"[{block.id}] x={box.x:.0f} y={box.y:.0f} l={box.width:.0f} : {text}"
        )
    return "Lignes du CV :\n" + "\n".join(lines)


def block_roles(answer: Any, blocks: Sequence[Block]) -> tuple[BlockRole, ...]:
    """Every block once, with a known role; refused otherwise (Q20: blocks left without role)."""
    if not isinstance(answer, dict) or not isinstance(answer.get("roles"), list):
        raise SemanticsError("La réponse du modèle n'a pas la forme attendue.")
    known = {block.id for block in blocks}
    found: dict[int, BlockRole] = {}
    for item in answer["roles"]:
        if not isinstance(item, dict):
            continue
        block_id, role = item.get("id"), item.get("role")
        if block_id not in known or role not in {r.value for r in Role}:
            continue
        index = item.get("index", 0)
        found[int(block_id)] = BlockRole(
            block_id=int(block_id),
            role=Role(role),
            index=index if isinstance(index, int) and 0 <= index < 20 else 0,
            label=_text(item.get("label")),
            label_en=_text(item.get("en")) if Role(role) in PROJECT_ROLES else "",
            text_en=_text(item.get("en"))
            if Role(role) in (Role.HEADING, Role.FIXED)
            else "",
        )
    missing = sorted(known - set(found))
    if missing:
        raise SemanticsError(
            f"{len(missing)} bloc(s) du CV n'ont pas pu être rattachés à une rubrique : "
            "Rocky ne peut pas reproduire ce CV à l'identique."
        )
    return tuple(found[block.id] for block in blocks)


def profile_answer(answer: Any) -> Mapping[str, Any]:
    profile = answer.get("profile") if isinstance(answer, dict) else None
    if not isinstance(profile, dict):
        raise SemanticsError("La réponse du modèle ne contient pas le contenu du CV.")
    return profile


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
