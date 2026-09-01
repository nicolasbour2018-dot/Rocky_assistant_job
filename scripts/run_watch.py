"""Lance une veille complète, prévue pour être appelée par cron."""

from __future__ import annotations

import json
import logging
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
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.sources import build_watch_sources
from dashboard.rocky.watch import WatchService


def configure_logging() -> None:
    logs_dir = PROJECT_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(logs_dir / "veille.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    configure_logging()
    settings = Settings()
    try:
        ensure_database_exists(settings)
        engine = create_db_engine(settings)
        initialize_database(engine, settings)
        repository = RockyRepository(engine)
        service = WatchService(
            settings,
            repository,
            build_watch_sources(settings),
        )
        summary = service.run()
    except (RockyError, OSError) as error:
        logging.error("%s", error)
        return 1
    except Exception:
        logging.exception("Erreur inattendue pendant la veille")
        return 1
    logging.info("Résumé : %s", json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if summary["status"] in {"SUCCESS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
