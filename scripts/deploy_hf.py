"""Dépose Rocky dans un Space Hugging Face existant, sans suppression.

Le CLI `hf upload` tente actuellement de recréer le Space lorsqu'il rencontre
le README Docker local. Ce script utilise la même bibliothèque officielle mais
crée directement un commit avec une liste blanche. Le fichier `.env`, les
caches et les documents de référence non requis ne peuvent donc pas partir.
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "Neomac21/rocky-job-assistant"
ROOT_FILES = [
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "CV Nicolas Bour.pdf",
    "Dockerfile",
    "pyproject.toml",
    "requirements.txt",
]
SOURCE_DIRECTORIES = [
    "cron",
    "dashboard",
    "database",
    "scripts",
    "templates",
    "tests",
]


def _source_files() -> list[tuple[Path, str]]:
    selected: list[tuple[Path, str]] = []
    for relative in ROOT_FILES:
        path = PROJECT_DIR / relative
        if path.is_file():
            selected.append((path, relative))
    for directory in SOURCE_DIRECTORIES:
        root = PROJECT_DIR / directory
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store":
                continue
            relative = path.relative_to(PROJECT_DIR).as_posix()
            selected.append((path, relative))

    # La page statique reste la racine tant que le compte n'autorise pas Docker.
    selected.append((PROJECT_DIR / "deployment" / "README.md", "README.md"))
    selected.append((PROJECT_DIR / "deployment" / "index.html", "index.html"))
    # La documentation Docker reste consultable sans modifier le SDK actif.
    selected.append((PROJECT_DIR / "README.md", "docs/README_DOCKER.md"))
    return selected


def main() -> int:
    token = os.getenv("HF_TOKEN", "").strip()
    configured = os.getenv("HF_REPO", "").strip().rstrip("/")
    repo_id = configured if "/" in configured else DEFAULT_REPO
    if not token:
        print("ERREUR : HF_TOKEN manque dans le .env local.")
        return 1

    files = _source_files()
    operations = [
        CommitOperationAdd(path_in_repo=target, path_or_fileobj=source)
        for source, target in files
    ]
    result = HfApi(token=token).create_commit(
        repo_id=repo_id,
        repo_type="space",
        operations=operations,
        commit_message="Deploy Rocky tested source without deleting remote files",
        commit_description=(
            "Static staging because the account currently requires PRO for "
            "Docker runtime. No secret or deletion operation is included."
        ),
    )
    print(f"OK : {len(files)} fichier(s) versionné(s) dans {repo_id}.")
    print(f"Commit : {result.oid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
