"""E5 captures: a posting opened by the Rocky workstation, then read once the user says it is shown.

Goes through the real workstation (``uv run rocky-poste``) and its two requests, ``/ouvrir`` then ``/lire``: the same
path as the gesture of the offers screen. Writes ``<n>-<host>.json`` (address shown, HTML drawn, time) outside the
repository. Usage: see README.md next to this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from rocky.system.workstation import WorkstationClient, WorkstationUnavailableError

LOCAL_WORKSTATION = "http://127.0.0.1:8765"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="dossier hors du dépôt")
    parser.add_argument("urls", nargs="+", help="adresses des fiches à lire")
    parser.add_argument("--poste", default=LOCAL_WORKSTATION)
    arguments = parser.parse_args(argv)
    arguments.out.mkdir(parents=True, exist_ok=True)
    workstation = WorkstationClient(arguments.poste)
    for number, url in enumerate(arguments.urls, start=1):
        try:
            tab = workstation.open_page(url)
            input(
                f"[{number}] Fiche ouverte dans le navigateur du poste. Passe l'éventuel défi, attends que "
                "l'annonce soit affichée, puis appuie sur Entrée (Ctrl+C pour arrêter). "
            )
            shown = workstation.read_page(tab)
        except WorkstationUnavailableError as error:
            sys.stderr.write(f"[{number}] {error.reason}\n")
            return 1
        name = f"{number:02d}-{urlsplit(shown.url).hostname or 'page'}.json"
        (arguments.out / name).write_text(
            json.dumps(
                {
                    "url": shown.url,
                    "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "html": shown.html,
                },
                ensure_ascii=False,
            )
        )
        sys.stderr.write(f"[{number}] {name} : {len(shown.html):,} caractères\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
