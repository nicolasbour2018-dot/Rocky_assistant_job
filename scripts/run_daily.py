"""Orchestrateur local de midi : Gmail puis veille, avec verrou exclusif."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine, initialize_database
from dashboard.rocky.gmail_service import GmailService
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.sources import build_watch_sources
from dashboard.rocky.watch import WatchService


def _run_account(
    settings: Settings, repository: RockyRepository, dry_run: bool = False
) -> dict[str, object]:
    """Isole chaque boîte Gmail et la veille dans un bilan sérialisable.

    Une panne ou une autorisation manquante sur une boîte ne bloque ni les
    autres comptes ni la collecte d'annonces.
    """
    profile = repository.fetch_active_profile()
    if profile is None:
        raise RuntimeError("Aucun profil actif.")
    result: dict[str, object] = {
        "dry_run": dry_run,
        "profile_id": profile.id,
        "gmail": {"status": "SKIPPED"},
        "watch": {"status": "SKIPPED"},
    }
    gmail_services = [
        GmailService(settings, repository, profile, account)
        for account in settings.gmail_accounts
    ]
    if dry_run:
        account_statuses = {
            gmail.account_email: (
                "READY"
                if gmail.is_configured and gmail.is_authorized
                else "AUTHORIZATION_REQUIRED"
                if gmail.is_configured
                else "NOT_CONFIGURED"
            )
            for gmail in gmail_services
        }
        result["gmail"] = {
            "status": (
                "READY"
                if account_statuses
                and all(status == "READY" for status in account_statuses.values())
                else "PARTIAL"
                if any(status == "READY" for status in account_statuses.values())
                else "AUTHORIZATION_REQUIRED"
                if "AUTHORIZATION_REQUIRED" in account_statuses.values()
                else "NOT_CONFIGURED"
            ),
            "accounts": account_statuses,
        }
        result["watch"] = {
            "status": "READY",
            "sources": len(build_watch_sources(settings)),
        }
        return result
    gmail_accounts: dict[str, object] = {}
    for gmail in gmail_services:
        if not gmail.is_configured:
            gmail_accounts[gmail.account_email] = {"status": "NOT_CONFIGURED"}
            continue
        if not gmail.is_authorized:
            gmail_accounts[gmail.account_email] = {"status": "AUTHORIZATION_REQUIRED"}
            continue
        try:
            gmail_accounts[gmail.account_email] = {
                "status": "SUCCESS",
                **gmail.sync_gmail().__dict__,
            }
        except Exception as error:
            gmail_accounts[gmail.account_email] = {
                "status": "FAILED",
                "error": type(error).__name__,
            }
    account_statuses = {
        str(dict(account_result).get("status"))
        for account_result in gmail_accounts.values()
    }
    if account_statuses == {"SUCCESS"}:
        gmail_status = "SUCCESS"
    elif "SUCCESS" in account_statuses:
        gmail_status = "PARTIAL"
    elif "FAILED" in account_statuses:
        gmail_status = "FAILED"
    elif "AUTHORIZATION_REQUIRED" in account_statuses:
        gmail_status = "AUTHORIZATION_REQUIRED"
    else:
        gmail_status = "NOT_CONFIGURED"
    result["gmail"] = {"status": gmail_status, "accounts": gmail_accounts}
    try:
        result["watch"] = WatchService(
            settings, repository, build_watch_sources(settings)
        ).run()
    except Exception as error:
        result["watch"] = {"status": "FAILED", "error": type(error).__name__}
    return result


def run(dry_run: bool = False) -> dict[str, object]:
    """Exécute la veille indépendamment pour chaque compte actif vérifié."""
    settings = Settings()
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    base_repository = RockyRepository(engine)
    user_ids = base_repository.fetch_active_user_ids()
    account_results: dict[str, object] = {}
    for user_id in user_ids:
        repository = base_repository.for_user(user_id)
        if repository.fetch_active_profile() is None:
            account_results[str(user_id)] = {"status": "SKIPPED_NO_PROFILE"}
            continue
        try:
            account_results[str(user_id)] = _run_account(settings, repository, dry_run)
        except Exception as error:
            account_results[str(user_id)] = {
                "status": "FAILED",
                "error": type(error).__name__,
            }
    return {"dry_run": dry_run, "accounts": account_results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    # Le code de l'image appartient à root, alors que Rocky s'exécute sans
    # privilèges. Les journaux et le verrou doivent donc suivre le stockage
    # modifiable (`/data` dans Docker, racine du projet en local).
    logs = Settings().storage_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(logs / "daily.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    lock_path = logs / "daily.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("Une exécution quotidienne est déjà en cours.")
            return 0
        summary = run(arguments.dry_run)
        logging.info(
            "Résumé : %s", json.dumps(summary, ensure_ascii=False, default=str)
        )
    statuses = {
        str(dict(value).get("status"))
        for value in dict(summary.get("accounts") or {}).values()
    }
    return 1 if statuses == {"FAILED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
