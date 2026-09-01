"""Crée un premier profil actif à partir du CV déjà présent."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.bootstrap import bootstrap_default_profile
from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.repository import RockyRepository


def main() -> int:
    settings = Settings()
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)

    profile, created = bootstrap_default_profile(settings, repository)
    if created:
        print(f"Profil {profile.id} créé depuis le CV.")
    else:
        print(f"Profil existant {profile.id} conservé.")
    print("Profil actif prêt pour la veille.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
