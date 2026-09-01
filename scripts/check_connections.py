"""Teste les services externes de Rocky sans afficher les credentials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import text

from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.models import CandidateProfile
from dashboard.rocky.sources import build_watch_sources


def _arguments() -> argparse.Namespace:
    """Lit le service demandé sans accepter de credential en argument."""
    parser = argparse.ArgumentParser(
        description="Teste les connexions externes de Rocky sans afficher de secret."
    )
    parser.add_argument(
        "--only",
        choices=(
            "all",
            "postgresql",
            "mistral",
            "france-travail",
            "adzuna",
            "linkedin",
            "indeed",
            "welcome-to-the-jungle",
            "apec",
            "wellfound",
        ),
        default="all",
        help="Limite le test à un service (all par défaut).",
    )
    return parser.parse_args()


def main() -> int:
    requested = _arguments().only
    settings = Settings()
    failures = 0

    if requested in {"all", "postgresql"}:
        try:
            with create_db_engine(settings).connect() as connection:
                connection.execute(text("SELECT 1"))
            print("OK PostgreSQL")
        except Exception as error:
            failures += 1
            print(f"ERREUR PostgreSQL : {error}")

    if requested in {"all", "mistral"}:
        try:
            answer = RockyLLM(settings).complete_text(
                "Réponds uniquement avec ROCKY_OK.",
                "Test de connexion.",
                temperature=0,
            )
            if "ROCKY_OK" not in answer.upper():
                raise RuntimeError("Réponse inattendue du modèle")
            print(f"OK Mistral ({settings.mistral_model})")
        except Exception as error:
            failures += 1
            print(f"ERREUR Mistral : {error}")

    test_profile = CandidateProfile(
        id=0,
        profile_name="Data",
        target_job_titles=["Data Analyst"],
    )
    source_keys = {
        "France Travail": "france-travail",
        "Adzuna": "adzuna",
        "LinkedIn": "linkedin",
        "Indeed": "indeed",
        "Welcome to the Jungle": "welcome-to-the-jungle",
        "Apec": "apec",
        "Wellfound": "wellfound",
    }
    sources = [
        source
        for source in build_watch_sources(settings)
        if requested == "all" or source_keys[source.name] == requested
    ]

    for source in sources:
        try:
            offers = source.search(test_profile, 1)
            print(f"OK {source.name} ({len(offers)} résultat(s))")
        except Exception as error:
            failures += 1
            print(f"ERREUR {source.name} : {error}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
