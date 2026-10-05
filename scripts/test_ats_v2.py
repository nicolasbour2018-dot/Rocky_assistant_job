"""Lance le simulateur ATS V2 de Rocky depuis la ligne de commande."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard.rocky.ats import analyze_application_ats_v2
from dashboard.rocky.models import JobOffer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cv", type=Path, required=True)
    parser.add_argument("--cv-text", type=Path)
    parser.add_argument("--letter", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--description", type=Path, required=True)
    arguments = parser.parse_args()
    offer = JobOffer(
        job_title=arguments.title,
        company_name=arguments.company,
        responsibilities=arguments.description.read_text(encoding="utf-8"),
    )
    cv_text = (
        arguments.cv_text.read_text(encoding="utf-8")
        if arguments.cv_text
        else None
    )
    report = analyze_application_ats_v2(
        arguments.cv,
        arguments.letter.read_text(encoding="utf-8"),
        offer,
        cv_text_override=cv_text,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
