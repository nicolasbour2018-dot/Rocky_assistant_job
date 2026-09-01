"""Ouvre le navigateur Rocky, préremplit puis laisse la main à l'utilisateur.

Le script n'identifie et ne clique volontairement aucun bouton de soumission.
Il reste vivant tant que la fenêtre dédiée est ouverte afin que l'utilisateur
puisse terminer les questions propres au site et envoyer lui-même le dossier.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine
from dashboard.rocky.repository import RockyRepository

FIELD_SELECTORS = {
    "Nom complet": (
        "input[autocomplete='name']",
        "input[name*='full'][name*='name' i]",
        "input[id*='full'][id*='name' i]",
    ),
    "E-mail": (
        "input[type='email']",
        "input[autocomplete='email']",
        "input[name*='email' i]",
    ),
    "Téléphone": (
        "input[type='tel']",
        "input[autocomplete='tel']",
        "input[name*='phone' i]",
    ),
    "Adresse": (
        "input[autocomplete='street-address']",
        "input[name*='address' i]",
    ),
    "Code postal": (
        "input[autocomplete='postal-code']",
        "input[name*='postal' i]",
        "input[name*='zip' i]",
    ),
    "Ville": (
        "input[autocomplete='address-level2']",
        "input[name*='city' i]",
        "input[name*='ville' i]",
    ),
    "LinkedIn": (
        "input[name*='linkedin' i]",
        "input[id*='linkedin' i]",
    ),
    "GitHub": (
        "input[name*='github' i]",
        "input[id*='github' i]",
    ),
    "Portfolio": (
        "input[name*='portfolio' i]",
        "input[name*='website' i]",
    ),
}


def _resolve(path_value: str, settings: Settings) -> Path:
    path = Path(path_value).expanduser()
    return path if path.is_absolute() else settings.project_dir / path


def _fill_first(page: Page, selectors: tuple[str, ...], value: str) -> bool:
    if not value:
        return False
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 5)):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible() and candidate.is_editable():
                    candidate.fill(value)
                    return True
            except Exception:
                continue
    return False


def _upload_documents(
    page: Page, cv_path: Path, letter_path: Path
) -> tuple[list[str], list[str]]:
    filled: list[str] = []
    missing = ["CV", "Lettre"]
    inputs = page.locator("input[type='file']")
    fallback_paths = [cv_path, letter_path]
    for index in range(inputs.count()):
        candidate: Locator = inputs.nth(index)
        descriptor = " ".join(
            filter(
                None,
                [
                    candidate.get_attribute("name"),
                    candidate.get_attribute("id"),
                    candidate.get_attribute("aria-label"),
                    candidate.get_attribute("accept"),
                ],
            )
        ).lower()
        selected: Path | None = None
        label = ""
        if any(marker in descriptor for marker in ("cv", "resume", "résumé")):
            selected, label = cv_path, "CV"
        elif any(marker in descriptor for marker in ("cover", "letter", "motivation")):
            selected, label = letter_path, "Lettre"
        elif fallback_paths:
            selected = fallback_paths.pop(0)
            label = "CV" if selected == cv_path else "Lettre"
        if selected and selected.is_file():
            try:
                candidate.set_input_files(str(selected))
                filled.append(label)
                if label in missing:
                    missing.remove(label)
            except Exception:
                continue
    return filled, missing


def run(session_id: int, user_id: int) -> int:
    """Préremplit uniquement dans le contexte propriétaire transmis par Rocky."""
    settings = Settings()
    base_repository = RockyRepository(create_db_engine(settings))
    repository = base_repository.for_user(user_id)
    session = repository.fetch_browser_session(session_id)
    if not session:
        return 2
    application = repository.fetch_application(int(session["application_id"]))
    if not application:
        repository.update_browser_session(
            session_id, "ERROR", error_message="Candidature introuvable"
        )
        return 2
    values = {
        "Nom complet": str(application.get("full_name") or ""),
        "E-mail": str(application.get("email") or ""),
        "Téléphone": str(application.get("phone") or ""),
        "Adresse": str(application.get("address") or ""),
        "Code postal": str(application.get("postal_code") or ""),
        "Ville": str(application.get("home_city") or ""),
        "LinkedIn": str(application.get("linkedin_url") or ""),
        "GitHub": str(application.get("github_url") or ""),
        "Portfolio": str(application.get("portfolio_url") or ""),
    }
    filled: list[str] = []
    missing: list[str] = []
    try:
        browser_profile_dir = settings.user_browser_profile_dir(user_id)
        browser_profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(browser_profile_dir), headless=False, no_viewport=True
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(
                str(session["target_url"]), wait_until="domcontentloaded", timeout=60000
            )
            page.wait_for_timeout(1200)
            for label, selectors in FIELD_SELECTORS.items():
                if _fill_first(page, selectors, values[label]):
                    filled.append(label)
                elif values[label]:
                    missing.append(label)
            uploaded, missing_uploads = _upload_documents(
                page,
                _resolve(str(application["cv_path"]), settings),
                _resolve(str(application["letter_pdf_path"]), settings),
            )
            filled.extend(uploaded)
            missing.extend(missing_uploads)
            repository.update_browser_session(
                session_id, "READY_FOR_REVIEW", filled, missing
            )
            while context.pages:
                time.sleep(1)
            repository.update_browser_session(session_id, "CLOSED", filled, missing)
    except Exception as error:
        repository.update_browser_session(
            session_id,
            "ERROR",
            filled,
            missing,
            f"Le préremplissage a échoué ({type(error).__name__}).",
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    arguments = parser.parse_args()
    return run(arguments.session_id, arguments.user_id)


if __name__ == "__main__":
    raise SystemExit(main())
