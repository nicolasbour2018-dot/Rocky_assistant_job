"""C4 measure: score archived postings with the new rules and compare with the v1 scores (see README.md).

Runs in the application container: it reads the profile (skills, tracks, preferences, jobs) from the development
database, read only, and the postings and v1 scores from the archive. It writes nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from sqlalchemy import Engine

from rocky.offres.analysis.rules import account_skills, analyze
from rocky.offres.scoring.model import RULES_VERSION, Score, TrackScore
from rocky.offres.scoring.rules import score, scoring_profile
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Profile
from rocky.profil.sql import SqlProfileStore
from rocky.system.config import load_settings
from rocky.system.db import create_db_engine

HERE = Path(__file__).parent
TODAY = date(2026, 9, 25)
DATA_PROTECTION_ANALYST = "1193"
# The archive → offer conversion of the C3 measure: the facts a connector would give, in its own codes.
sys.path.insert(0, str(HERE.parent / "c3-mesure"))
from measure import SOURCES, offer  # noqa: E402  (the C3 measure script, not a package)


def load_profile(engine: Engine, profile_id: int) -> Profile:
    with engine.connect() as connection:
        return SqlProfileStore(connection).load(profile_id)


def collected(row: dict[str, str]) -> CollectedOffer:
    return replace(offer(row), location=row["city"] or None, country=row["country"] or None)


def ranks(values: list[float]) -> list[float]:
    """Ranks from 1 (highest), ties sharing their mean rank."""
    order = sorted(range(len(values)), key=lambda index: -values[index])
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        for index in order[position : end + 1]:
            result[index] = (position + end) / 2 + 1
        position = end + 1
    return result


def spearman(left: list[float], right: list[float]) -> float:
    a, b = ranks(left), ranks(right)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    spread = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
    return covariance / spread if spread else 0.0


def line(identifier: str, row: dict[str, str], v1: float | None, result: Score) -> str:
    best: TrackScore = result.best
    caps = " ; ".join(cap.label for cap in best.caps) or ""
    title = row["job_title"].replace("|", "/")[:48]
    old = f"{v1:.1f}" if v1 is not None else "—"
    return (
        f"| {identifier} | {row['source_name']} | {title} | {old} | {best.display} | "
        f"{best.track_name or '—'} | {best.confidence.level.value} | {caps} |"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile-id", type=int, required=True, help="profile of the development database")
    arguments = parser.parse_args()
    csv.field_size_limit(sys.maxsize)
    exports = arguments.archive / "exports" / "csv"
    with (exports / "job_offers.csv").open(newline="") as file:
        rows = {row["id"]: row for row in csv.DictReader(file)}
    with (exports / "job_matches.csv").open(newline="") as file:
        v1 = {
            row["job_id"]: float(row["score"])
            for row in csv.DictReader(file)
            if row["profile_id"] == "1"
        }
    engine = create_db_engine(load_settings().database_url)
    profile = load_profile(engine, arguments.profile_id)
    skills = account_skills(skill.content for skill in profile.skills)
    reading = scoring_profile(profile)

    def scored(identifier: str) -> Score:
        posting = collected(rows[identifier])
        return score(analyze(posting, skills, today=TODAY), posting, reading, today=TODAY)

    sample = [item["id"] for item in json.loads((HERE.parent / "c3-mesure" / "echantillon.json").read_text())]
    print(f"Mesure C4 (règles {RULES_VERSION}) — profil {arguments.profile_id} : "
          f"{len(profile.skills)} compétences, {len(reading.tracks)} pistes actives\n")
    print("| Id | Source | Intitulé | v1 | C4 | Piste | Confiance | Plafond |")
    print("|---|---|---|---|---|---|---|---|")
    results = {identifier: scored(identifier) for identifier in [DATA_PROTECTION_ANALYST, *sample]}
    for identifier in sorted(results, key=lambda key: -results[key].best.value):
        print(line(identifier, rows[identifier], v1.get(identifier), results[identifier]))

    # Every archived posting the v1 scored with a full description, from a source the new collection reads.
    wide = [
        identifier
        for identifier in v1
        if rows[identifier]["description_is_full"] == "True" and rows[identifier]["source_name"] in SOURCES
    ]
    new = {identifier: scored(identifier).best for identifier in wide}
    old_values = [v1[identifier] for identifier in wide]
    new_values = [new[identifier].value for identifier in wide]
    top_old = set(sorted(wide, key=lambda key: -v1[key])[:20])
    top_new = set(sorted(wide, key=lambda key: -new[key].value)[:20])
    levels = {level: sum(1 for item in new.values() if item.confidence.level == level) for level in ("high", "medium", "low")}
    print(f"\nEnsemble : {len(wide)} annonces à description complète notées en v1")
    print(f"- corrélation de rang (Spearman) v1 / C4 : {spearman(old_values, new_values):.2f}")
    print(f"- v1 ≥ 50 : {sum(1 for value in old_values if value >= 50)} ; C4 ≥ 50 : "
          f"{sum(1 for item in new.values() if item.display >= 50)}")
    print(f"- moyenne v1 : {sum(old_values) / len(old_values):.1f} ; moyenne C4 : {sum(new_values) / len(new_values):.1f}")
    print(f"- 20 premières communes aux deux classements : {len(top_old & top_new)}")
    print(f"- confiance C4 : haute {levels['high']}, moyenne {levels['medium']}, faible {levels['low']}")
    print(f"- plafonnées : {sum(1 for item in new.values() if item.caps)}")
    print("\n20 premières en C4 :")
    for identifier in sorted(wide, key=lambda key: -new[key].value)[:20]:
        print(line(identifier, rows[identifier], v1[identifier], scored(identifier)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
