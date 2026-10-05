"""Exécute ATS V3 en ligne de commande sur un CV et une annonce."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.ats_v3 import analyze_ats_v3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Banc de test multi-parseurs ATS V3 de Rocky."
    )
    parser.add_argument("--cv", required=True, type=Path, help="CV PDF ou DOCX")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--job-file",
        type=Path,
        help="Fichier texte UTF-8 contenant la description complète",
    )
    source.add_argument("--description", help="Description complète en argument")
    parser.add_argument("--title", default="", help="Intitulé du poste")
    parser.add_argument(
        "--output",
        type=Path,
        help="Écrit le rapport JSON à cet emplacement au lieu de stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    description = (
        args.job_file.read_text(encoding="utf-8")
        if args.job_file
        else args.description
    )
    report = analyze_ats_v3(
        args.cv.read_bytes(),
        args.cv.name,
        description,
        job_title=args.title,
    )
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
