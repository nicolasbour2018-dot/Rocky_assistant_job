"""G2: the place component on the offers of the development database, scored again in memory (see README.md).

Reads the account's offers and profile, scores every offer with the rules of the running code and prints the counts
of the measure of 29/09 (plan §8, C7). Nothing is written to the database; ``--out`` keeps the best score of each
offer (a JSON file outside the repository) to compare two runs with ``compare.py``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import select

from rocky.offres.analysis.rules import analyze
from rocky.offres.rules import scoring_inputs
from rocky.offres.scoring.model import (
    OUT_OF_ZONE,
    OUT_OF_ZONE_HYBRID,
    RULES_VERSION,
    THRESHOLD,
    ComponentCode,
)
from rocky.offres.scoring.rules import score
from rocky.offres.sql import SqlStore
from rocky.profil.sql import SqlProfileStore, profiles
from rocky.system.config import load_settings
from rocky.system.db import create_db_engine

# Same day for every run, so that two runs differ by their rules only.
TODAY = date(2026, 10, 6)
OUT = frozenset({OUT_OF_ZONE, OUT_OF_ZONE_HYBRID})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with create_db_engine(load_settings().database_url).connect() as connection:
        account_id = connection.execute(
            select(profiles.c.account_id).where(profiles.c.id == args.profile_id)
        ).scalar_one()
        profile = SqlProfileStore(connection).load(args.profile_id)
        # No score carries an empty fingerprint: every offer of the account.
        stored = SqlStore(connection).stale_offers(account_id, "")
    inputs = scoring_inputs(profile)
    values: Counter[str] = Counter()
    details: Counter[str] = Counter()
    best: dict[int, dict[str, object]] = {}
    for offer in stored:
        result = score(
            analyze(offer.offer, inputs.skills, today=TODAY),
            offer.offer,
            inputs.profile,
            today=TODAY,
        )
        for track in result.tracks:
            location = next(c for c in track.components if c.code == ComponentCode.LOCATION)
            values["neutre" if location.neutral else str(location.value)] += 1
            if location.value in OUT:
                details[offer.offer.location or ""] += 1
        top = result.best
        location = next(c for c in top.components if c.code == ComponentCode.LOCATION)
        best[offer.id] = {
            "display": top.display,
            "track": top.track_name,
            "location": offer.offer.location,
            "location_value": location.value,
            "location_detail": location.detail,
        }
    scores = sum(values.values())
    out_40_49 = sum(
        1
        for item in best.values()
        if 40 <= int(str(item["display"])) < THRESHOLD and item["location_value"] in OUT
    )
    above = sum(1 for item in best.values() if int(str(item["display"])) >= THRESHOLD)
    print(f"# Lieux — règles {RULES_VERSION}, profil {args.profile_id}, {len(best)} offres, {scores} scores")
    print()
    print("| Composante lieu | Scores |")
    print("|---|---|")
    for value, count in sorted(values.items()):
        print(f"| {value} | {count} |")
    print()
    print(f"- offres au-dessus du seuil ({THRESHOLD}) : {above}")
    print(f"- offres entre 40 et {THRESHOLD - 1} avec un lieu hors zone : {out_40_49}")
    print()
    print("Lieux hors zone les plus fréquents (scores) :")
    for place, count in details.most_common(25):
        print(f"- {place or '(vide)'} : {count}")
    if args.out:
        args.out.write_text(
            json.dumps({"rules_version": RULES_VERSION, "offers": best}, ensure_ascii=False, indent=1)
        )


if __name__ == "__main__":
    main()
