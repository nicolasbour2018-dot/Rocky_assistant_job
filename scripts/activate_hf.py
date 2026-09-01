"""Active le runtime Docker Rocky une fois le plan Hugging Face disponible.

Le script ne supprime aucun fichier distant : il remplace uniquement la carte
du Space statique par la carte Docker validée, puis monte le bucket privé déjà
créé sur `/data`.
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi, Volume
from huggingface_hub.errors import HfHubHTTPError

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "Neomac21/rocky-job-assistant"


def main() -> int:
    token = os.getenv("HF_TOKEN", "").strip()
    configured = os.getenv("HF_REPO", "").strip().rstrip("/")
    repo_id = configured if "/" in configured else DEFAULT_REPO
    if not token:
        print("ERREUR : HF_TOKEN manque dans le .env local.")
        return 1

    api = HfApi(token=token)
    try:
        commit = api.create_commit(
            repo_id=repo_id,
            repo_type="space",
            operations=[
                CommitOperationAdd(
                    path_in_repo="README.md",
                    path_or_fileobj=PROJECT_DIR / "README.md",
                )
            ],
            commit_message="Activate Rocky Docker runtime",
        )
        api.set_space_volumes(
            repo_id,
            volumes=[
                Volume(
                    type="bucket",
                    source="Neomac21/rocky-data",
                    mount_path="/data",
                )
            ],
        )
    except HfHubHTTPError as error:
        status = getattr(error.response, "status_code", None)
        if status == 402:
            print("BLOQUÉ : Hugging Face exige un plan PRO pour le runtime Docker.")
            return 2
        print(f"ERREUR Hugging Face (HTTP {status or 'inconnu'}).")
        return 1
    print(f"OK : runtime Docker activé, commit {commit.oid}.")
    print(f"URL : https://huggingface.co/spaces/{repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
