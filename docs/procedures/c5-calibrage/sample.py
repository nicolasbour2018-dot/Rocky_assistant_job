"""C5 calibration: reference scores and the stratified sample to annotate (see README.md).

Runs in the application container (the profile is read, read only, from the development database). Writes
``reference.json`` (the score of every measured posting with the rules and the frozen profile of the start of C5) and
``echantillon.json`` (the postings to annotate, their stratum and the display order with the hidden duplicates).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from common import HERE, load_archive, scorer

SEED = 20260928
# Stratum (lowest reference score, inclusive) → number of postings (decision C5, Q10).
STRATA = {80: 15, 60: 15, 40: 12, 0: 8}
DUPLICATES = 5


def stratum(value: int) -> int:
    return next(bottom for bottom in STRATA if value >= bottom)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile-id", type=int, required=True, help="profile of the development database")
    arguments = parser.parse_args()
    archive = load_archive(arguments.archive)
    scored = scorer(arguments.profile_id)
    from rocky.offres.scoring.model import RULES_VERSION

    measured = archive.measured
    scores = {identifier: scored(archive.rows[identifier]).best for identifier in measured}
    reference = {
        "rules_version": RULES_VERSION,
        "profile_id": arguments.profile_id,
        "scores": {identifier: round(scores[identifier].value, 2) for identifier in sorted(measured, key=int)},
    }
    (HERE / "reference.json").write_text(json.dumps(reference, indent=1, ensure_ascii=False) + "\n")

    randomizer = random.Random(SEED)
    candidates = sorted((i for i in measured if i not in archive.control), key=int)
    sample: list[dict[str, object]] = []
    for bottom, count in STRATA.items():
        pool = [i for i in candidates if stratum(scores[i].display) == bottom]
        for identifier in sorted(randomizer.sample(pool, count), key=int):
            sample.append({"id": identifier, "source": archive.rows[identifier]["source_name"], "stratum": bottom})
    order = [str(item["id"]) for item in sample]
    randomizer.shuffle(order)
    order += randomizer.sample(order, DUPLICATES)
    (HERE / "echantillon.json").write_text(
        json.dumps({"seed": SEED, "sample": sample, "order": order}, indent=2, ensure_ascii=False) + "\n"
    )

    print(f"Référence C5 ({RULES_VERSION}, profil {arguments.profile_id}) : {len(measured)} annonces mesurées, "
          f"{sum(1 for i in measured if i in archive.control)} du contrôle")
    for bottom in STRATA:
        pool = sum(1 for i in candidates if stratum(scores[i].display) == bottom)
        print(f"- tranche ≥ {bottom} : {pool} annonces hors contrôle, {STRATA[bottom]} tirées")
    print(f"{len(sample)} annonces tirées, {len(order)} affichées (dont {DUPLICATES} doublons) → echantillon.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
