"""Apec reference lists (C3, Q8): the labels of the contract and remote-work codes, captured once.

The Apec pages name them through ``referentielstatique`` (found in the public application script of apec.fr). Two
GET requests, stopped at the first refusal. Usage: see README.md next to this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rocky.offres.sources.apec import REFERENCE_URL
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import SourceError, SourceRefusedError

LISTS = ("RECHERCHE_OFFRE_TYPE_CONTRAT", "LISTE_OPTIONS_REDUITES_TELETRAVAIL")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="output directory (outside the repository)")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    http = PublicHttp(pause_seconds=2.0)
    try:
        for code in LISTS:
            try:
                data = http.get_json("Apec", REFERENCE_URL.format(code=code))
            except SourceRefusedError as refused:
                print(f"{code}: {refused.reason}\nArrêt au premier refus : en parler à Nicolas.")
                return 1
            except SourceError as error:
                print(f"{code}: {error.reason}")
                continue
            path = arguments.out / f"referentiel-{code.lower()}.json"
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            print(f"{code}: {len(data) if isinstance(data, list) else '?'} entrées → {path.name}")
    finally:
        http.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
