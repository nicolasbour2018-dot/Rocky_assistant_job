"""Initialise ou met à jour le schéma PostgreSQL de Rocky."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.errors import RockyError


def main() -> int:
    settings = Settings()
    try:
        created = ensure_database_exists(settings)
        engine = create_db_engine(settings)
        initialize_database(engine, settings)
    except (RockyError, OSError, RuntimeError) as error:
        print(f"Erreur : {error}")
        return 1
    except Exception as error:
        print(f"PostgreSQL a refusé l'initialisation : {error}")
        return 1
    if created:
        print(f"Base {settings.db_name} créée.")
    print("Schéma Rocky initialisé avec succès.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
