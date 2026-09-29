"""Profile files (``rocky-admin import-profil`` / ``export-profil``): JSON read and validated field by field.

Every problem is reported with the path of its field (``skills[3].category``), all at once, so that one review
fixes them all. Unknown keys are refused: a misspelt key would otherwise be silently ignored. ``export_profile``
writes what ``parse_import`` reads (decision D2, Q18): the photo and the CV templates are files, not in it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from rocky.profil.model import (
    Hobby,
    Identity,
    ImportedCv,
    ImportedExperience,
    ImportedProfile,
    ImportedProject,
    ImportedSkillGroup,
    Preferences,
    Profile,
    SkillDraft,
    Text,
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
from rocky.system.events import JsonValue

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
    "cv",
}
# Before D2, identity had one field per link: still read, as links.
LEGACY_LINKS = {
    "linkedin_url": "LinkedIn",
    "github_url": "GitHub",
    "portfolio_url": "Portfolio",
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
    cv = reader.build("cv", root["cv"], _cv) if "cv" in root else None
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
        cv=cv,
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
    plain = ("full_name", "contact_email", "phone", "city", "postal_code")
    names = {
        **{key: key for key in plain},
        **{key: key for key in LEGACY_LINKS},
        "links": "links",
        "headline": "headline",
        "title": "title",
        "birth_date": "birth_date",
        "show_age": "show_age",
    }
    found = reader.fields(value, path, names)
    links = [
        f"{label} | {found.pop(key)}"
        for key, label in LEGACY_LINKS.items()
        if found.get(key)
    ]
    for key in LEGACY_LINKS:
        found.pop(key, None)
    listed = found.pop("links", [])
    if not isinstance(listed, list) or not all(isinstance(v, str) for v in listed):
        reader.fail(f"{path}.links", "doit être une liste de « Libellé | URL ».")
        raise _RecordedError
    for key in ("headline", "title"):
        if key in found:
            found[f"{key}_fr"], found[f"{key}_en"] = _text(
                reader, found.pop(key), f"{path}.{key}"
            )
    return make_identity(**{"full_name": "", **found, "links": [*links, *listed]})


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


def _cv(reader: _Reader, value: object, path: str) -> ImportedCv:
    found = reader.fields(
        value,
        path,
        {k: k for k in ("groups", "transversal", "projects", "hobbies")},
    )
    groups = reader.items(f"{path}.groups", found.get("groups", []), _group)
    hobbies = reader.items(f"{path}.hobbies", found.get("hobbies", []), _hobby)
    return ImportedCv(
        groups=tuple(groups),
        transversal=_names(reader, found.get("transversal", []), f"{path}.transversal"),
        projects=_names(reader, found.get("projects", []), f"{path}.projects"),
        hobbies=tuple(hobbies),
    )


def _group(reader: _Reader, value: object, path: str) -> ImportedSkillGroup:
    found = reader.fields(value, path, {"name": "name", "skills": "skills"})
    french, english = _text(reader, found.get("name"), f"{path}.name")
    if not french.strip():
        reader.fail(f"{path}.name", "le nom français est obligatoire.")
        raise _RecordedError
    return ImportedSkillGroup(
        Text(french.strip(), (english or "").strip() or None),
        _names(reader, found.get("skills", []), f"{path}.skills"),
    )


def _hobby(reader: _Reader, value: object, path: str) -> Hobby:
    found = reader.fields(value, path, {"label": "label", "in_cv": "in_cv"})
    french, english = _text(reader, found.get("label"), f"{path}.label")
    in_cv = found.get("in_cv", True)
    if not isinstance(in_cv, bool):
        reader.fail(f"{path}.in_cv", "vaut true ou false.")
        raise _RecordedError
    if not french.strip():
        reader.fail(f"{path}.label", "le nom français est obligatoire.")
        raise _RecordedError
    return Hobby(Text(french.strip(), (english or "").strip() or None), in_cv)


def _names(reader: _Reader, value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        reader.fail(path, "doit être une liste de noms de compétences.")
        raise _RecordedError
    return tuple(value)


def export_profile(profile: Profile) -> dict[str, JsonValue]:
    """The profile as a file ``parse_import`` reads back: skills and projects named, never by id."""
    labels = {skill.id: skill.label.fr for skill in profile.skills}
    projects = {project.id: project.content.name.fr for project in profile.projects}
    identity = profile.identity
    return {
        "format": FORMAT,
        "identity": _drop_empty(
            {
                "full_name": identity.full_name,
                "contact_email": identity.contact_email,
                "phone": identity.phone,
                "city": identity.city,
                "postal_code": identity.postal_code,
                "links": [f"{link.label} | {link.url}" for link in identity.links],
                "headline": _export_text(identity.headline),
                "title": _export_text(identity.title),
                "birth_date": (
                    identity.birth_date.isoformat() if identity.birth_date else None
                ),
                "show_age": identity.show_age,
            }
        ),
        "preferences": {
            "contracts": [c.value for c in profile.preferences.contracts],
            "remote_modes": [m.value for m in profile.preferences.remote_modes],
            "min_salary_eur": profile.preferences.min_salary_eur,
            "min_daily_rate_eur": profile.preferences.min_daily_rate_eur,
        },
        "skills": [
            _drop_empty(
                {
                    "label": _export_text(skill.label),
                    "aliases": list(skill.content.aliases),
                    "category": skill.content.category.value,
                    "level": skill.content.level.value if skill.content.level else None,
                    "is_key": skill.content.is_key,
                }
            )
            for skill in profile.skills
        ],
        "languages": [
            {"code": item.content.code, "level": item.content.level.value}
            for item in profile.languages
        ],
        "experiences": [
            _drop_empty(
                {
                    "kind": item.content.kind.value,
                    "title": _export_text(item.content.title),
                    "organisation": item.content.organisation,
                    "place": item.content.place,
                    "start": item.content.start.strftime("%Y-%m"),
                    "end": item.content.end.strftime("%Y-%m")
                    if item.content.end
                    else None,
                    "bullets": {
                        "fr": list(item.content.bullets_fr),
                        "en": list(item.content.bullets_en),
                    },
                    "skills": [labels[s] for s in item.content.skill_ids],
                }
            )
            for item in profile.experiences
        ],
        "projects": [
            _drop_empty(
                {
                    "name": _export_text(item.content.name),
                    "problem": _export_text(item.content.problem),
                    "work": _export_text(item.content.work),
                    "results": _export_text(item.content.results),
                    "stack": list(item.content.stack),
                    "url": item.content.url,
                    "skills": [labels[s] for s in item.content.skill_ids],
                }
            )
            for item in profile.projects
        ],
        "tracks": [
            {
                "name": track.content.name,
                "titles": list(track.content.titles),
                "keywords": list(track.content.keywords),
                "excluded_keywords": list(track.content.excluded_keywords),
                "locations": list(track.content.locations),
            }
            for track in profile.tracks
        ],
        "cv": {
            "groups": [
                {
                    "name": _export_text(group.name),
                    "skills": [labels[s] for s in group.skill_ids],
                }
                for group in profile.cv.groups
            ],
            "transversal": [labels[s] for s in profile.cv.transversal],
            "projects": [projects[p] for p in profile.cv.projects],
            "hobbies": [
                {"label": _export_text(hobby.label), "in_cv": hobby.in_cv}
                for hobby in profile.cv.hobbies
            ],
        },
    }


def _export_text(text: Text) -> dict[str, JsonValue]:
    return {"fr": text.fr, "en": text.en}


def _drop_empty(values: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Absent fields rather than nulls: the file stays short to review."""
    return {key: value for key, value in values.items() if value is not None}
