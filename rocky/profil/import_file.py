"""Reviewed profile files (``rocky-admin import-profil``): JSON read and validated field by field.

Every problem is reported with the path of its field (``skills[3].category``), all at once, so that one review
fixes them all. Unknown keys are refused: a misspelt key would otherwise be silently ignored.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from rocky.profil.model import (
    Identity,
    ImportedExperience,
    ImportedProfile,
    ImportedProject,
    Preferences,
    SkillDraft,
    TrackDraft,
)
from rocky.profil.rules import (
    ProfileInputError,
    make_experience,
    make_identity,
    make_language,
    make_preferences,
    make_project,
    make_skill,
    make_track,
)

FORMAT = "rocky-profil/1"
TOP_KEYS = {
    "format",
    "to_review",
    "identity",
    "preferences",
    "skills",
    "languages",
    "experiences",
    "projects",
    "tracks",
}


class ImportFileError(ValueError):
    """The file cannot be imported; ``problems`` lists every field at fault."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def read_import_file(path: Path) -> ImportedProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise ImportFileError([f"Fichier illisible : {error}"]) from error
    except json.JSONDecodeError as error:
        raise ImportFileError(
            [
                f"JSON invalide, ligne {error.lineno}, colonne {error.colno} : {error.msg}"
            ]
        ) from error
    return parse_import(data)


def parse_import(data: object) -> ImportedProfile:
    reader = _Reader()
    root = reader.mapping(data, "", TOP_KEYS)
    if root is None:
        raise ImportFileError(reader.problems)
    if root.get("format") != FORMAT:
        reader.fail("format", f"doit valoir « {FORMAT} ».")
    if root.get("to_review"):
        reader.fail(
            "to_review",
            "des éléments restent à relire : place-les dans le profil, puis vide ou retire cette rubrique.",
        )
    identity = reader.build("identity", root.get("identity"), _identity)
    preferences = reader.build("preferences", root.get("preferences", {}), _preferences)
    skills = reader.items("skills", root.get("skills", []), _skill)
    languages = reader.items(
        "languages",
        root.get("languages", []),
        lambda r, v, p: make_language(
            **r.fields(v, p, {"code": "code_value", "level": "level"})
        ),
    )
    experiences = reader.items("experiences", root.get("experiences", []), _experience)
    projects = reader.items("projects", root.get("projects", []), _project)
    tracks = reader.items("tracks", root.get("tracks", []), _track)
    if reader.problems or identity is None:
        raise ImportFileError(reader.problems)
    return ImportedProfile(
        identity=identity,
        preferences=preferences or Preferences(),
        skills=tuple(skills),
        languages=tuple(languages),
        experiences=tuple(experiences),
        projects=tuple(projects),
        tracks=tuple(tracks),
    )


class _Reader:
    """Walks the file, collecting problems instead of stopping at the first one."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def fail(self, path: str, message: str) -> None:
        self.problems.append(f"{path or 'fichier'} : {message}")

    def mapping(
        self, value: object, path: str, allowed: set[str]
    ) -> Mapping[str, Any] | None:
        if not isinstance(value, dict):
            self.fail(path, "doit être un objet { … }.")
            return None
        for key in sorted(set(value) - allowed):
            self.fail(f"{path}.{key}" if path else key, "clé inconnue.")
        return value

    def fields(
        self, value: object, path: str, names: Mapping[str, str]
    ) -> dict[str, Any]:
        """Keys of ``value`` renamed to the builder's arguments; skips an item already reported."""
        found = self.mapping(value, path, set(names))
        if found is None or not set(found) <= set(names):
            raise _RecordedError
        return {names[key]: item for key, item in found.items()}

    def build[T](
        self, path: str, value: object, build: Callable[[_Reader, object, str], T]
    ) -> T | None:
        try:
            return build(self, value, path)
        except _RecordedError:
            return None
        except ProfileInputError as error:
            self.fail(path, str(error))
        except (TypeError, AttributeError):
            self.fail(path, "valeur d'un type inattendu (texte, liste ou objet ?).")
        return None

    def items[T](
        self, path: str, value: object, build: Callable[[_Reader, object, str], T]
    ) -> list[T]:
        if not isinstance(value, list):
            self.fail(path, "doit être une liste [ … ].")
            return []
        built = []
        for index, item in enumerate(value):
            result = self.build(f"{path}[{index}]", item, build)
            if result is not None:
                built.append(result)
        return built


class _RecordedError(Exception):
    """The problem is already recorded; skip the item."""


def _text(reader: _Reader, value: object, path: str) -> tuple[str, str | None]:
    """A ``{"fr": …, "en": …}`` pair (English optional)."""
    found = reader.mapping(value, path, {"fr", "en"})
    if found is None:
        raise _RecordedError
    french, english = found.get("fr") or "", found.get("en")
    if not isinstance(french, str) or not isinstance(english, str | None):
        reader.fail(path, "« fr » et « en » sont des textes.")
        raise _RecordedError
    return french, english


def _identity(reader: _Reader, value: object, path: str) -> Identity:
    names = {
        key: key
        for key in (
            "full_name",
            "contact_email",
            "phone",
            "city",
            "postal_code",
            "linkedin_url",
            "github_url",
            "portfolio_url",
        )
    }
    found = reader.fields(value, path, {**names, "headline": "headline"})
    headline = found.pop("headline", None)
    if headline is not None:
        found["headline_fr"], found["headline_en"] = _text(
            reader, headline, f"{path}.headline"
        )
    return make_identity(**{"full_name": "", **found})


def _preferences(reader: _Reader, value: object, path: str) -> Preferences:
    keys = ("contracts", "remote_modes", "min_salary_eur", "min_daily_rate_eur")
    return make_preferences(**reader.fields(value, path, {key: key for key in keys}))


def _skill(reader: _Reader, value: object, path: str) -> SkillDraft:
    found = reader.fields(
        value,
        path,
        {
            "label": "label",
            "aliases": "aliases",
            "category": "category",
            "level": "level",
            "is_key": "is_key",
        },
    )
    label_fr, label_en = _text(reader, found.pop("label", None), f"{path}.label")
    return make_skill(label_fr=label_fr, label_en=label_en, **found)


def _experience(reader: _Reader, value: object, path: str) -> ImportedExperience:
    keys = ("kind", "organisation", "place", "start", "end")
    found = reader.fields(
        value,
        path,
        {
            **{key: key for key in keys},
            "title": "title",
            "bullets": "bullets",
            "skills": "skills",
        },
    )
    title_fr, title_en = _text(reader, found.pop("title", None), f"{path}.title")
    bullets = reader.mapping(found.pop("bullets", {}), f"{path}.bullets", {"fr", "en"})
    if bullets is None:
        raise _RecordedError
    skills = _names(reader, found.pop("skills", []), f"{path}.skills")
    content = make_experience(
        title_fr=title_fr,
        title_en=title_en,
        bullets_fr=bullets.get("fr", []),
        bullets_en=bullets.get("en", []),
        **{"kind": "", "organisation": "", "start": "", **found},
    )
    return ImportedExperience(content, skills)


def _project(reader: _Reader, value: object, path: str) -> ImportedProject:
    texts = ("name", "problem", "work", "results")
    found = reader.fields(
        value,
        path,
        {
            **{key: key for key in texts},
            "stack": "stack",
            "url": "url",
            "skills": "skills",
        },
    )
    arguments: dict[str, Any] = {}
    for key in texts:
        if key in found:
            french, english = _text(reader, found.pop(key), f"{path}.{key}")
            arguments[f"{key}_fr"], arguments[f"{key}_en"] = french, english
    skills = _names(reader, found.pop("skills", []), f"{path}.skills")
    content = make_project(**{"name_fr": "", **arguments, **found})
    return ImportedProject(content, skills)


def _track(reader: _Reader, value: object, path: str) -> TrackDraft:
    keys = ("name", "titles", "keywords", "excluded_keywords", "locations")
    return make_track(
        **{"name": "", **reader.fields(value, path, {k: k for k in keys})}
    )


def _names(reader: _Reader, value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        reader.fail(path, "doit être une liste de noms de compétences.")
        raise _RecordedError
    return tuple(value)
