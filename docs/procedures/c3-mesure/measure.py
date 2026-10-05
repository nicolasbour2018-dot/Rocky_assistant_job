"""C3 measure: run the analysis on the annotated sample and print precision and recall per field (see README.md).

Each archived posting is turned into the offer the new collection would give (C1 connectors, C2 import): the source
facts are kept only where a connector gives them, in its own codes.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rocky.offres.analysis.model import Importance, PostingAnalysis
from rocky.offres.analysis.rules import account_skills, analyze
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.rules import make_skill

HERE = Path(__file__).parent
TODAY = date(2026, 9, 25)
SOURCES = {
    "Adzuna": "adzuna",
    "LinkedIn": "linkedin",
    "Wellfound": "wellfound",
    "Welcome to the Jungle": "wttj",
    "Indeed": "indeed.com",
    "hellowork.com": "hellowork.com",
    "Apec": "apec",
}
# Old stored values → the raw facts of the new connectors (Adzuna: contract_type; WTTJ: contract_type and remote).
ADZUNA_CONTRACTS = {"CDI": "permanent", "CDD": "contract"}
WTTJ_CONTRACTS = {"CDI": "full_time", "CDD": "temporary"}


def offer(row: dict[str, str]) -> CollectedOffer:
    source = SOURCES[row["source_name"]]
    contract: str | None = None
    remote: str | None = None
    if source == "adzuna":
        contract = ADZUNA_CONTRACTS.get(row["contract_type"])
    elif source == "wttj":
        contract = WTTJ_CONTRACTS.get(row["contract_type"])
        remote = row["remote_policy"] or None
    elif source == "wellfound":
        remote = "remote" if row["remote_policy"] == "Télétravail complet" else None
    elif source == "apec":
        contract = row["contract_type"] or None
    return CollectedOffer(
        source=source,
        external_id=row["id"],
        url=row["source_url"],
        title=row["job_title"],
        description=row["responsibilities"],
        description_complete=True,
        company=row["company_name"] or None,
        contract=contract,
        remote=remote,
        salary_min=float(row["salary_min"]) if row["salary_min"] else None,
        salary_max=float(row["salary_max"]) if row["salary_max"] else None,
        salary_currency=row["salary_currency"] or None if row["salary_min"] else None,
    )


@dataclass
class Score:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    gaps: list[str] = field(default_factory=list)

    def add(self, posting: str, expected: set[str], found: set[str]) -> None:
        self.true_positive += len(expected & found)
        self.false_positive += len(found - expected)
        self.false_negative += len(expected - found)
        if expected != found:
            self.gaps.append(f"{posting}: attendu {sorted(expected)}, trouvé {sorted(found)}")

    def line(self, name: str) -> str:
        found = self.true_positive + self.false_positive
        expected = self.true_positive + self.false_negative
        precision = f"{100 * self.true_positive / found:.0f} %" if found else "—"
        recall = f"{100 * self.true_positive / expected:.0f} %" if expected else "—"
        return f"{name:<20} précision {precision:>6}  rappel {recall:>6}  ({self.true_positive} justes, {self.false_positive} en trop, {self.false_negative} manqués)"


def facts(analysis: PostingAnalysis) -> dict[str, set[str]]:
    salary = analysis.salary
    return {
        "contrats": {contract.value for contract in analysis.contracts},
        "télétravail": {analysis.remote.value} if analysis.remote else set(),
        "salaire (période)": {salary.period.value} if salary else set(),
        "salaire (bornes)": {f"{salary.minimum:.0f}-{salary.maximum:.0f}"} if salary else set(),
        "conditions": {condition.kind.value for condition in analysis.conditions},
        "expérience": {str(analysis.experience.years)} if analysis.experience else set(),
        "langues": {need.code for need in analysis.languages},
        "compétences": {match.skill for match in analysis.skills},
        "éliminatoires": {match.skill for match in analysis.skills_of(Importance.ELIMINATORY)},
        "un plus": {match.skill for match in analysis.skills_of(Importance.PREFERRED)},
        "date limite": {analysis.deadline.isoformat()} if analysis.deadline else set(),
    }


def expected(annotation: dict[str, object]) -> dict[str, set[str]]:
    salary = annotation["salary"]
    experience = annotation["experience_years"]
    return {
        "contrats": set(annotation["contracts"]),  # type: ignore[arg-type]
        "télétravail": {annotation["remote"]} if annotation["remote"] else set(),  # type: ignore[arg-type]
        "salaire (période)": {salary["period"]} if isinstance(salary, dict) else set(),
        "salaire (bornes)": {f"{salary['min']:.0f}-{salary['max']:.0f}"} if isinstance(salary, dict) else set(),
        "conditions": set(annotation["conditions"]),  # type: ignore[arg-type]
        "expérience": {str(experience)} if experience is not None else set(),
        "langues": set(annotation["languages"]),  # type: ignore[arg-type]
        "compétences": set(annotation["skills"]),  # type: ignore[arg-type]
        "éliminatoires": set(annotation["eliminatory_skills"]),  # type: ignore[arg-type]
        "un plus": set(annotation["preferred_skills"]),  # type: ignore[arg-type]
        "date limite": set(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True, help="reviewed profile file of B5 (outside the repo)")
    parser.add_argument("--gaps", action="store_true", help="list the gaps posting by posting")
    arguments = parser.parse_args()
    csv.field_size_limit(sys.maxsize)
    with (arguments.archive / "exports" / "csv" / "job_offers.csv").open(newline="") as file:
        rows = {row["id"]: row for row in csv.DictReader(file)}
    profile = json.loads(arguments.profile.read_text())
    skills = account_skills(
        make_skill(
            label_fr=skill["label"]["fr"],
            label_en=skill["label"].get("en") or "",
            category=skill["category"],
            aliases="\n".join(skill.get("aliases") or []),
            level=skill.get("level") or "",
            is_key=bool(skill.get("is_key")),
        )
        for skill in profile["skills"]
    )
    annotations = json.loads((HERE / "annotations.json").read_text())["postings"]
    scores: dict[str, Score] = defaultdict(Score)
    for identifier, annotation in annotations.items():
        analysis = analyze(offer(rows[identifier]), skills, today=TODAY)
        found, wanted = facts(analysis), expected(annotation)
        for name in wanted:
            scores[name].add(identifier, wanted[name], found[name])
    print(f"Mesure C3 sur {len(annotations)} annonces annotées (règles {analysis.rules_version})\n")
    for name, score in scores.items():
        print(score.line(name))
        if arguments.gaps:
            for gap in score.gaps:
                print(f"    {gap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
