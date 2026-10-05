"""C3 measure: draw the sample of archived postings to annotate (identifiers only, see README.md).

Postings with a complete description, drawn with a fixed seed, a fixed number per source. Writes
``echantillon.json`` next to this file; the texts stay in the archive, outside the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
SEED = 20260925
PER_SOURCE = {
    "Adzuna": 10,
    "LinkedIn": 8,
    "Wellfound": 7,
    "Welcome to the Jungle": 6,
    "Indeed": 4,
    "hellowork.com": 3,
    "Apec": 2,
}


def complete_postings(archive: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with (archive / "exports" / "csv" / "job_offers.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    return [row for row in rows if row["description_is_full"].lower() in {"true", "t", "1"}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="archive directory (A1)")
    arguments = parser.parse_args()
    postings = complete_postings(arguments.archive)
    randomizer = random.Random(SEED)
    sample: list[dict[str, str]] = []
    for source, count in PER_SOURCE.items():
        candidates = sorted(
            (row for row in postings if row["source_name"] == source), key=lambda row: int(row["id"])
        )
        for row in randomizer.sample(candidates, count):
            sample.append({"id": row["id"], "source": source})
    (HERE / "echantillon.json").write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(sample)} annonces tirées → echantillon.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
