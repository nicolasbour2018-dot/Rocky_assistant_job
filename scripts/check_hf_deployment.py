"""Vérifie le dépôt et la page distante Rocky sans afficher le token."""

from __future__ import annotations

import os

import requests


DEFAULT_REPO = "Neomac21/rocky-job-assistant"


def main() -> int:
    token = os.getenv("HF_TOKEN", "").strip()
    configured = os.getenv("HF_REPO", "").strip().rstrip("/")
    repo_id = configured if "/" in configured else DEFAULT_REPO
    if not token:
        print("ERREUR : HF_TOKEN absent.")
        return 1
    headers = {"Authorization": f"Bearer {token}"}
    api_response = requests.get(
        f"https://huggingface.co/api/spaces/{repo_id}",
        headers=headers,
        timeout=20,
    )
    api_response.raise_for_status()
    info = api_response.json()
    filenames = {
        item.get("rfilename", "") for item in info.get("siblings", [])
    }
    required = {"Dockerfile", "README.md", "dashboard/dashboard_v2.py"}
    if not required.issubset(filenames):
        print("ERREUR : des fichiers Rocky requis manquent sur le Space.")
        return 1
    if ".env" in filenames:
        print("ERREUR : le fichier .env ne doit jamais être versionné.")
        return 1

    host = str(info.get("host") or "")
    source_response = requests.get(
        f"https://huggingface.co/spaces/{repo_id}/resolve/main/index.html",
        headers=headers,
        timeout=30,
    )
    source_response.raise_for_status()
    if "Rocky est prêt" not in source_response.text:
        print("ERREUR : l'index distant ne correspond pas à Rocky.")
        return 1
    page_response = requests.get(host, headers=headers, timeout=30)
    page_response.raise_for_status()
    browser_auth_required = "Rocky est prêt" not in page_response.text
    stage = info.get("runtime", {}).get("stage", "inconnu")
    print(f"OK Space privé : SDK={info.get('sdk')}, état={stage}.")
    if browser_auth_required:
        print("Accès à l'application : session navigateur Hugging Face requise.")
    print(f"URL : https://huggingface.co/spaces/{repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
