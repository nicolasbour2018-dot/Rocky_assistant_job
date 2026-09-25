"""``rocky-admin import-profil``: a reviewed file into the empty profile of an account, once."""

from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine

from rocky.profil.sql import SqlProfileStore
from rocky.system.admin import import_profile
from rocky.system.auth.sql import SqlAuthStore
from tests.system.auth.fakes import FakeClock

SKILLS = [
    {
        "label": {"fr": "NLP"},
        "aliases": ["Traitement du langage naturel (NLP)"],
        "category": "technical",
    },
    {"label": {"fr": "Data Visualisation"}, "category": "technical"},
]
PROFILE: dict[str, object] = {
    "format": "rocky-profil/1",
    "identity": {"full_name": "Nicolas Exemple"},
    "skills": SKILLS,
    "languages": [{"code": "fr", "level": "native"}],
}


def account(engine: Engine) -> str:
    email = f"{uuid4().hex}@example.fr"
    with engine.begin() as connection:
        SqlAuthStore(connection).create_account(email, FakeClock()())
    return email


def run(engine: Engine, path: Path, email: str) -> tuple[int, str]:
    out = io.StringIO()
    code = import_profile(engine, path=path, email=email, out=out, clock=FakeClock())
    return code, out.getvalue()


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "profil.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def skill_count(engine: Engine, email: str) -> int:
    with engine.connect() as connection:
        found = SqlAuthStore(connection).find_account(email)
        assert found is not None
        store = SqlProfileStore(connection)
        profile_id = store.find_profile_id(found.id)
        return 0 if profile_id is None else len(store.load(profile_id).skills)


def test_a_reviewed_file_is_imported_once(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    email, path = account(migrated_engine), write(tmp_path, PROFILE)

    first = run(migrated_engine, path, email)
    second = run(migrated_engine, path, email)

    assert first == (
        0,
        (
            f"Profil importé pour {email} : 2 compétences, 1 langues, "
            "0 expériences et formations, 0 projets, 0 pistes.\n"
        ),
    )
    assert second[0] == 1
    assert "déjà un contenu" in second[1]
    assert skill_count(migrated_engine, email) == 2


def test_a_refused_import_writes_nothing(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    email = account(migrated_engine)
    duplicate = {
        **PROFILE,
        "skills": [
            *SKILLS,
            {
                "label": {"fr": "traitement du langage naturel (nlp)"},
                "category": "technical",
            },
        ],
    }

    code, output = run(migrated_engine, write(tmp_path, duplicate), email)

    assert code == 2
    assert "déjà présent sous « NLP »" in output
    assert skill_count(migrated_engine, email) == 0


def test_an_invalid_file_lists_its_problems(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    code, output = run(
        migrated_engine,
        write(tmp_path, {**PROFILE, "to_review": ["Domaine : finance"]}),
        account(migrated_engine),
    )

    assert code == 2
    assert output.startswith("Le fichier n'est pas importable :\n- to_review : ")


def test_an_unknown_account_is_reported(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    code, output = run(migrated_engine, write(tmp_path, PROFILE), "personne@example.fr")

    assert code == 1
    assert "Aucun compte pour personne@example.fr" in output
