"""C5 calibration: build the final review page of the calibrated rules (decision C5, Q21; see README.md).

Runs in the application container (the profile is read, read only, from the development database). Writes
``index.html`` into a folder outside the repository, mounted by the command: the page holds the texts of the postings
and, this time, their score with its detail. Postings Nicolas annotated are left out.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common import HERE, load_archive, scorer

TOP = 20
UNDER = 10


def detail(row: dict[str, str], result: Any) -> dict[str, Any]:
    best = result.best
    return {
        "title": row["job_title"],
        "company": row["company_name"],
        "place": ", ".join(value for value in (row["city"], row["country"]) if value),
        "source": row["source_name"],
        "url": row["source_url"],
        "text": row["responsibilities"],
        "score": best.display,
        "track": best.track_name,
        "confidence": best.confidence.level.value,
        "reasons": list(best.confidence.reasons),
        "caps": [cap.label for cap in best.caps],
        "components": [
            {
                "code": component.code.value,
                "value": None if component.value is None else round(component.value, 2),
                "weight": component.weight,
                "detail": component.detail,
            }
            for component in best.components
        ],
        "gaps": list(best.gaps),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile-id", type=int, required=True, help="profile of the development database")
    parser.add_argument("--out", type=Path, required=True, help="folder outside the repository (mounted)")
    arguments = parser.parse_args()
    from rocky.offres.scoring.model import RULES_VERSION, THRESHOLD

    archive = load_archive(arguments.archive)
    scored = scorer(arguments.profile_id)
    annotated = {answer["id"] for answer in json.loads((HERE / "annotations.json").read_text())["answers"]}
    results = {identifier: scored(archive.rows[identifier]) for identifier in archive.measured}
    ranked = sorted((i for i in results if i not in annotated), key=lambda i: -results[i].best.value)
    groups = {
        f"Les {TOP} premières": ranked[:TOP],
        f"Les {UNDER} juste sous le seuil": [i for i in ranked if results[i].best.display < THRESHOLD][:UNDER],
        "Candidatures du contrôle sous le seuil": [
            i for i in ranked if i in archive.control and results[i].best.display < THRESHOLD
        ],
    }
    data = {
        "rules_version": RULES_VERSION,
        "groups": groups,
        "postings": {
            identifier: detail(archive.rows[identifier], results[identifier])
            for ids in groups.values()
            for identifier in ids
        },
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    arguments.out.mkdir(parents=True, exist_ok=True)
    page = (HERE / "review.html").read_text().replace("__DATA__", payload)
    (arguments.out / "relecture.html").write_text(page)
    print(f"{len(data['postings'])} annonces ({RULES_VERSION}) → relecture.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
