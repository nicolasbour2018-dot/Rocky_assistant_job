"""Charge le dashboard comme Streamlit, sans démarrer de serveur web.

Ce contrôle complète les tests unitaires : il vérifie l'import de l'interface,
la connexion PostgreSQL et la construction des composants avec les données
réelles. Il ne clique sur aucun bouton et n'appelle aucune API externe.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from streamlit.testing.v1 import AppTest
from sqlalchemy import text
from dashboard import dashboard_common


def main() -> int:
    dashboards = (
        "dashboard_v2.py",
        "dashboard_b.py",
        "page_all_jobs.py",
        "page_enrichment.py",
        "page_job_detail.py",
        "page_application_prepare.py",
        "page_import_url.py",
        "page_profiles.py",
        "page_monitoring.py",
        "page_ats_v3.py",
        "page_applications.py",
        "page_statistics.py",
        "page_assistant.py",
    )
    for filename in dashboards:
        app = AppTest.from_file(PROJECT_DIR / "dashboard" / filename)
        with dashboard_common.load_repository().engine.connect() as connection:
            user_ids = [
                int(row[0])
                for row in connection.execute(text("SELECT id FROM users ORDER BY id"))
            ]
        if user_ids:
            app.session_state["rocky_authenticated_user_id"] = user_ids[0]
        app.run(timeout=30)
        if app.exception or app.error:
            print(
                f"ERREUR {filename} : une erreur Streamlit a été détectée."
            )
            for exception in app.exception:
                print(f"- {exception.message}")
            for error in app.error:
                print(f"- {error.value}")
            return 1
        if filename == "page_ats_v3.py":
            launch = next(
                (
                    button
                    for button in app.button
                    if button.label == "Lancer le banc de test V3"
                ),
                None,
            )
            if launch is None or launch.disabled:
                print("ERREUR page_ats_v3.py : le test V3 réel est indisponible.")
                return 1
            launch.click()
            app.run(timeout=60)
            if app.exception or app.error or not app.metric:
                print(
                    "ERREUR page_ats_v3.py : l'analyse réelle ou son rendu a échoué."
                )
                for exception in app.exception:
                    print(f"- {exception.message}")
                for error in app.error:
                    print(f"- {error.value}")
                return 1
        print(f"OK {filename} (chargement, base Rocky et composants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
