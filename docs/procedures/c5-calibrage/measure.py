"""C5 calibration measure: the v1, reference and current rankings against the annotations and the control (README.md).

Runs in the application container: the profile is read, read only, from the development database; the postings, the
v1 scores and the applications from the archive; ``reference.json``, ``echantillon.json`` and ``annotations.json``
(once Nicolas has annotated) from this folder. It writes nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from common import HERE, load_archive, scorer

LEVELS = ("oui", "examiner", "non")
RELEVANT = {"oui", "examiner"}
TOP = 10
DISAGREEMENTS = 8


def display(value: float) -> int:
    """Whole number shown on screen, as ``TrackScore.display``."""
    return math.floor(value + 0.5)


def auc(relevant: list[float], other: list[float]) -> float | None:
    """Probability that a relevant posting ranks ahead of a non-relevant one (Mann-Whitney, ties count half)."""
    if not relevant or not other:
        return None
    wins = sum(1.0 if r > o else 0.5 if r == o else 0.0 for r in relevant for o in other)
    return wins / (len(relevant) * len(other))


def ahead(values: dict[str, float], identifier: str) -> float:
    """Share (%) of the postings ranked strictly ahead of this one."""
    return 100 * sum(1 for value in values.values() if value > values[identifier]) / len(values)


def control_lines(name: str, values: dict[str, float], control: list[str], threshold: int) -> str:
    shares = [ahead(values, identifier) for identifier in control]
    return (
        f"| {name} | {statistics.median(shares):.0f} % | {sum(1 for share in shares if share < 25)} / {len(control)} | "
        f"{sum(1 for identifier in control if display(values[identifier]) >= threshold)} / {len(control)} |"
    )


def first_answers(annotations: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, str]]]:
    """The first answer of each posting (Q19) and the (id, first level, second level) of the duplicates."""
    first: dict[str, dict[str, Any]] = {}
    repeats: list[tuple[str, str, str]] = []
    for answer in sorted(annotations["answers"], key=lambda item: item["position"]):
        identifier = answer["id"]
        if identifier in first:
            repeats.append((identifier, first[identifier]["level"], answer["level"]))
        else:
            first[identifier] = answer
    return first, repeats


def threshold_line(name: str, values: dict[str, float], labels: dict[str, str], threshold: int) -> str:
    above = {identifier for identifier in labels if display(values[identifier]) >= threshold}
    relevant = [identifier for identifier, level in labels.items() if level in RELEVANT]
    yes = [identifier for identifier, level in labels.items() if level == "oui"]
    no = [identifier for identifier, level in labels.items() if level == "non"]

    def share(group: list[str]) -> str:
        return f"{sum(1 for identifier in group if identifier in above)} / {len(group)}"

    return f"| {name} | {threshold} | {share(yes)} | {share(relevant)} | {share(no)} |"


def best_threshold(values: dict[str, float], labels: dict[str, str]) -> int | None:
    """Highest threshold keeping every Oui and at least 90 % of the relevant postings above (Q13)."""
    relevant = [identifier for identifier, level in labels.items() if level in RELEVANT]
    yes = [identifier for identifier, level in labels.items() if level == "oui"]
    for threshold in range(100, -1, -1):
        kept = sum(1 for identifier in relevant if display(values[identifier]) >= threshold)
        if all(display(values[i]) >= threshold for i in yes) and relevant and kept >= 0.9 * len(relevant):
            return threshold
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile-id", type=int, required=True, help="profile of the development database")
    parser.add_argument("--annotations", type=Path, default=HERE / "annotations.json")
    arguments = parser.parse_args()
    from rocky.offres.scoring.model import RULES_VERSION, THRESHOLD

    archive = load_archive(arguments.archive)
    scored = scorer(arguments.profile_id)
    reference_file = json.loads((HERE / "reference.json").read_text())
    measured = archive.measured
    results = {identifier: scored(archive.rows[identifier]) for identifier in measured}
    rankings: dict[str, tuple[dict[str, float], int]] = {
        "v1": ({i: archive.v1[i] for i in measured}, 50),
        f"référence ({reference_file['rules_version']})": (
            {i: float(v) for i, v in reference_file["scores"].items()},
            50,
        ),
        f"actuelle ({RULES_VERSION})": ({i: results[i].best.value for i in measured}, THRESHOLD),
    }
    control = sorted((i for i in measured if i in archive.control), key=int)

    print(f"# Mesure C5 — règles {RULES_VERSION}, profil {arguments.profile_id}, {len(measured)} annonces\n")
    print(f"## Contrôle : {len(control)} candidatures parmi les {len(measured)} annonces\n")
    print("| Classement | Rang médian (part devant) | Premier quart | Au-dessus du seuil |")
    print("|---|---|---|---|")
    for name, (values, threshold) in rankings.items():
        print(control_lines(name, values, control, threshold))

    annotations_path: Path = arguments.annotations
    if not annotations_path.exists():
        print("\n(annotations.json absent : mesure du contrôle seulement)")
        return 0
    first, repeats = first_answers(json.loads(annotations_path.read_text()))
    labels = {identifier: answer["level"] for identifier, answer in first.items()}
    counts = Counter(labels.values())
    print(f"\n## Annotations : {len(labels)} annonces — " + ", ".join(f"{level} {counts[level]}" for level in LEVELS))

    print("\n### Ordre\n")
    print(f"| Classement | AUC pertinente / Non | Pertinentes dans les {TOP} premières | Non dans les {TOP} premières "
          "|")
    print("|---|---|---|---|")
    for name, (values, _) in rankings.items():
        relevant = [values[i] for i, level in labels.items() if level in RELEVANT]
        no = [values[i] for i, level in labels.items() if level == "non"]
        area = auc(relevant, no)
        top = sorted(labels, key=lambda i: -values[i])[:TOP]
        print(
            f"| {name} | {'—' if area is None else f'{area:.2f}'} | "
            f"{sum(1 for i in top if labels[i] in RELEVANT)} | {sum(1 for i in top if labels[i] == 'non')} |"
        )

    print("\n### Seuil\n")
    print("| Classement | Seuil | Oui au-dessus | Pertinentes au-dessus | Non au-dessus |")
    print("|---|---|---|---|---|")
    for name, (values, threshold) in rankings.items():
        print(threshold_line(name, values, labels, threshold))
        best = best_threshold(values, labels)
        if best is not None and best != threshold:
            print(threshold_line(f"{name}, seuil lu sur la courbe", values, labels, best))

    print("\n### Motifs (niveau : motif signe × nombre)\n")
    for level in LEVELS:
        reasons = Counter(
            f"{code} {sign}"
            for answer in first.values()
            if answer["level"] == level
            for code, sign in answer["reasons"].items()
        )
        print(f"- {level} : " + ", ".join(f"{reason} × {count}" for reason, count in reasons.most_common()))

    current = rankings[f"actuelle ({RULES_VERSION})"][0]
    print("\n### Plus gros désaccords (version actuelle)\n")
    worst = sorted((i for i in labels if labels[i] in RELEVANT), key=lambda i: current[i])[:DISAGREEMENTS]
    worst += sorted((i for i in labels if labels[i] == "non"), key=lambda i: -current[i])[:DISAGREEMENTS]
    for identifier in worst:
        best = results[identifier].best
        answer = first[identifier]
        reasons = ", ".join(f"{code} {sign}" for code, sign in answer["reasons"].items())
        print(f"- **{identifier}** {archive.rows[identifier]['job_title'][:60]} — {labels[identifier]} ({reasons}"
              f"{' ; ' + answer['comment'] if answer.get('comment') else ''}) — score {best.display}, "
              f"{best.track_name}, confiance {best.confidence.level.value}")
        for component in best.components:
            value = "absente" if component.value is None else f"{component.value:.2f}"
            print(f"  - {component.code.value} {value} × {component.weight:g} : {component.detail}")

    print("\n### Stabilité (doublons)\n")
    for identifier, before, after in repeats:
        print(f"- {identifier} : {before} puis {after}{'' if before == after else '  ← différent'}")
    print(f"Accord : {sum(1 for _, before, after in repeats if before == after)} / {len(repeats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
