"""Exporte une fiche Apec complète en JSON grâce à un navigateur Playwright."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.sources.apec_detail import (
    ApecExtractionError,
    extract_apec_offer,
    extract_offer_number,
)


def _arguments() -> argparse.Namespace:
    """Déclare les options du CLI sans cacher le mode visible par défaut."""
    parser = argparse.ArgumentParser(
        description=(
            "Ouvre une fiche Apec avec Playwright et exporte l'intégralité "
            "des données de l'offre et de l'entreprise."
        )
    )
    parser.add_argument(
        "url",
        help="URL publique Apec contenant /detail-offre/<numéro>.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=("Fichier JSON de sortie. Par défaut : output/apec/<numero-offre>.json."),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Masque le navigateur (désactivé par défaut pour permettre l'audit visuel)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Délai maximal de chargement, en secondes (défaut : 30).",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=100,
        help="Délai visuel entre actions Playwright, en millisecondes (défaut : 100).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="Durée d'affichage finale avant fermeture, en secondes (défaut : 1).",
    )
    return parser.parse_args()


def main() -> int:
    """Exécute l'extraction et écrit un JSON UTF-8 de manière explicite."""
    arguments = _arguments()
    try:
        offer_number = extract_offer_number(arguments.url)
        result = extract_apec_offer(
            arguments.url,
            headless=arguments.headless,
            timeout_ms=max(1, int(arguments.timeout * 1_000)),
            slow_mo_ms=max(0, arguments.slow_mo),
            pause_ms=max(0, int(arguments.pause * 1_000)),
        )
    except ApecExtractionError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1

    output = (
        arguments.output or PROJECT_DIR / "output" / "apec" / f"{offer_number}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"Offre {offer_number} extraite dans {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
