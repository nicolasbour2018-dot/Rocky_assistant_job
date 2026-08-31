"""Préremplissage visible d'un formulaire sans soumission finale."""

from __future__ import annotations

import subprocess
import sys
from urllib.parse import urlsplit

from .config import Settings
from .errors import ConfigurationError
from .models import BrowserPrefillReport
from .repository import RockyRepository


def application_target_url(
    application_id: int, repository: RockyRepository
) -> str:
    """Retourne une URL HTTP(S) validée pour le lien de candidature client."""
    application = repository.fetch_application(application_id)
    if not application:
        raise ConfigurationError("Candidature introuvable.")
    target_url = str(
        application.get("application_url") or application.get("source_url") or ""
    ).strip()
    parts = urlsplit(target_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConfigurationError("L'URL de candidature n'est pas exploitable.")
    return target_url


def start_prefill(
    application_id: int,
    settings: Settings,
    repository: RockyRepository,
    *,
    confirmed: bool,
) -> BrowserPrefillReport:
    """Démarre un processus Playwright après confirmation des données envoyées."""
    if not confirmed:
        raise ConfigurationError(
            "Confirme les données et les deux PDF avant le préremplissage."
        )
    if repository.user_id is None:
        raise PermissionError(
            "Un compte authentifié est requis pour lancer le préremplissage."
        )
    application = repository.fetch_application(application_id)
    if not application:
        raise ConfigurationError("Candidature introuvable.")
    target_url = str(
        application.get("application_url") or application.get("source_url") or ""
    ).strip()
    parts = urlsplit(target_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConfigurationError("L'URL de candidature n'est pas exploitable.")
    for field in ("full_name", "email", "phone", "cv_path", "letter_pdf_path"):
        if not str(application.get(field) or "").strip():
            raise ConfigurationError(
                f"Le dossier doit renseigner {field} avant le préremplissage."
            )
    session_id = repository.create_browser_session(application_id, target_url)
    user_id = repository.user_id
    logs_dir = settings.user_dir(user_id) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"prefill_{session_id}.log"
    with log_path.open("ab") as log_stream:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scripts.prefill_application",
                "--session-id",
                str(session_id),
                "--user-id",
                str(user_id),
            ],
            cwd=settings.project_dir,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return BrowserPrefillReport(
        application_id=application_id,
        target_url=target_url,
        status="STARTING",
    )
