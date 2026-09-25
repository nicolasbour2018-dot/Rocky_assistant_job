"""Extract one profile of the A1 archive into a reviewable import file (decision B5, Q10-Q12).

Reads the CSV exports only (standard library, no dependency) and writes a JSON file in the format
``rocky-profil/1``, OUTSIDE the repository: it holds personal data. Nothing is guessed: what has no place in the
new profile (target domains, old target titles, the LLM career items, project details) goes to ``to_review``,
and the import refuses the file until that list is emptied by a human.

    python3 docs/procedures/b5-reimport/extract_profile.py \
        --archive backups/rocky-v1-20260924 --profile-id 1 --out ~/Developer/rocky-profil-nicolas.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

# Decision B5, Q11: the losing label becomes an alias of the winner. Other close pairs stay distinct.
MERGES = {
    "Traitement du langage naturel (NLP)": "NLP",
    "Visualisation de données": "Data Visualisation",
}
CONTRACTS = {
    "cdi": "permanent",
    "cdd": "fixed_term",
    "freelance": "freelance",
    "vie": "international_volunteer",
    "stage": "internship",
    "alternance": "apprenticeship",
    "interim": "temporary",
}
REMOTE = {
    "sur site": "on_site",
    "presentiel": "on_site",
    "hybride": "hybrid",
    "partiel": "hybrid",
    "teletravail": "full_remote",
    "full remote": "full_remote",
}
LEVELS = {
    "debutant": "beginner",
    "intermediaire": "intermediate",
    "avance": "advanced",
    "expert": "expert",
}
LANGUAGES = {"anglais": "en", "espagnol": "es", "allemand": "de", "italien": "it", "portugais": "pt"}
LANGUAGE_SKILL = re.compile(r"^(?P<name>[^\W\d_]+)\s*\((?P<level>[ABC][12])\)$")


def normalize(value: str) -> str:
    """Same comparison form as rocky.profil.rules.normalize_term."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", plain).strip()


def rows(archive: Path, table: str, profile_id: str, key: str = "profile_id") -> list[dict[str, str]]:
    with (archive / "exports" / "csv" / f"{table}.csv").open(encoding="utf-8", newline="") as file:
        return [row for row in csv.DictReader(file) if row[key] == profile_id]


def as_list(value: str) -> list[str]:
    return [str(item) for item in json.loads(value)] if value.startswith("[") else []


def text(french: str, english: str | None) -> dict[str, str]:
    pair = {"fr": french.strip()}
    if english and english.strip():
        pair["en"] = english.strip()
    return pair


def optional(value: str) -> str | None:
    return value.strip() or None


def extract(archive: Path, profile_id: str) -> tuple[dict[str, Any], list[str]]:
    report: list[str] = []
    to_review: list[str] = []
    [profile] = rows(archive, "candidate_profiles", profile_id, key="id")
    localizations = {row["locale"]: row for row in rows(archive, "profile_localizations", profile_id)}
    french, english = localizations.get("fr", {}), localizations.get("en", {})

    identity = {
        "full_name": profile["full_name"].strip(),
        "contact_email": optional(profile["email"]),
        "phone": optional(profile["phone"]),
        "city": optional(profile["home_city"]),
        "postal_code": optional(profile["postal_code"]),
        "linkedin_url": optional(profile["linkedin_url"]),
        "github_url": optional(profile["github_url"]),
        "portfolio_url": optional(profile["portfolio_url"]),
        "headline": text(french.get("summary") or profile["summary"], english.get("summary")),
    }
    identity = {key: value for key, value in identity.items() if value is not None}

    contracts, remote = [], []
    for contract in as_list(profile["preferred_contracts"]):
        code = CONTRACTS.get(normalize(contract))
        (contracts.append(code) if code else to_review.append(f"Contrat non reconnu : {contract}"))
    for mode in as_list(profile["remote_preferences"]):
        code = REMOTE.get(normalize(mode))
        (remote.append(code) if code else to_review.append(f"Télétravail non reconnu : {mode}"))
    salary = profile["minimum_salary"].strip()
    preferences: dict[str, Any] = {"contracts": contracts, "remote_modes": remote}
    if salary:
        preferences["min_salary_eur"] = int(float(salary))

    skills, languages = _skills(archive, profile_id, report, to_review)
    projects = _projects(archive, profile_id, skills, to_review)

    for title in as_list(french.get("target_job_titles", "")) or as_list(profile["target_job_titles"]):
        to_review.append(f"Intitulé visé de l'ancien profil (à reprendre dans une piste) : {title}")
    for domain in as_list(french.get("target_domains", "")):
        to_review.append(f"Domaine cible (mot-clé de piste ou abandon) : {domain}")
    for analysis in rows(archive, "profile_analyses", profile_id):
        for item in json.loads(analysis["analysis_data"]).get("career_items", []):
            to_review.append(f"Parcours selon l'analyse LLM (à vérifier sur le CV) : {item}")

    document = {
        "format": "rocky-profil/1",
        "to_review": to_review,
        "identity": identity,
        "preferences": preferences,
        "skills": skills,
        "languages": languages,
        "experiences": [],
        "projects": projects,
        "tracks": [],
    }
    return document, report


def _skills(
    archive: Path, profile_id: str, report: list[str], to_review: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    by_label: dict[str, dict[str, Any]] = {}
    languages = [{"code": "fr", "level": "native"}]
    losers = []
    for row in sorted(rows(archive, "candidate_skills", profile_id), key=lambda r: int(r["id"])):
        label = row["skill_name"].strip()
        language = LANGUAGE_SKILL.match(label)
        if language and normalize(language["name"]) in LANGUAGES:
            languages.append(
                {"code": LANGUAGES[normalize(language["name"])], "level": language["level"].lower()}
            )
            report.append(f"langue sortie des compétences : {label}")
            continue
        level = LEVELS.get(normalize(row["skill_level"]))
        if row["skill_level"].strip() and level is None:
            to_review.append(f"Niveau non reconnu pour {label} : {row['skill_level']}")
        skill: dict[str, Any] = {
            "label": text(label, row["skill_name_en"]),
            "aliases": [],
            "category": row["skill_category"],
            "level": level,
            "is_key": row["is_core_skill"] == "True",
        }
        if label in MERGES:
            losers.append(skill)
        else:
            by_label[label] = skill
    for loser in losers:
        winner = by_label[MERGES[loser["label"]["fr"]]]
        names = [loser["label"]["fr"], loser["label"].get("en", "")]
        winner["aliases"] += [n for n in names if n and normalize(n) not in _terms(winner)]
        winner["is_key"] = winner["is_key"] or loser["is_key"]
        report.append(f"fusion : « {loser['label']['fr']} » devient un alias de « {winner['label']['fr']} »")
    skills = list(by_label.values())
    seen: dict[str, str] = {}
    for skill in skills:
        for term in _terms(skill):
            if term in seen and seen[term] != skill["label"]["fr"]:
                to_review.append(
                    f"Doublon à trancher : « {skill['label']['fr']} » et « {seen[term]} » partagent « {term} »"
                )
            seen.setdefault(term, skill["label"]["fr"])
    return skills, languages


def _terms(skill: dict[str, Any]) -> set[str]:
    names = [skill["label"]["fr"], skill["label"].get("en", ""), *skill["aliases"]]
    return {normalize(name) for name in names if normalize(name)}


def _projects(
    archive: Path, profile_id: str, skills: list[dict[str, Any]], to_review: list[str]
) -> list[dict[str, Any]]:
    known = {term for skill in skills for term in _terms(skill)}
    by_order: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows(archive, "profile_projects", profile_id):
        if row["is_active"] == "True":
            by_order.setdefault(row["sort_order"], {})[row["locale"]] = row
    projects = []
    for order in sorted(by_order, key=int):
        french, english = by_order[order].get("fr"), by_order[order].get("en", {})
        if french is None:
            to_review.append(f"Projet sans version française (ordre {order}) : {english.get('name')}")
            continue
        linked, unknown = [], []
        for name in as_list(french["skills"]):
            (linked if normalize(name) in known else unknown).append(name)
        if unknown:
            to_review.append(
                f"Projet « {french['name']} » : compétences absentes du profil, non liées : {', '.join(unknown)}"
            )
        if french["details"].strip():
            to_review.append(f"Projet « {french['name']} », détails à placer : {french['details'].strip()}")
        project: dict[str, Any] = {
            "name": text(french["name"], english.get("name")),
            "problem": text(french["problem"], english.get("problem")),
            "work": text(french["deliverable"], english.get("deliverable")),
            "results": text(french["results"], english.get("results")),
            "stack": as_list(french["stack"]),
            "skills": linked,
        }
        projects.append({key: value for key, value in project.items() if value not in ({"fr": ""}, [])})
    return projects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile-id", default="1")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    out = arguments.out.expanduser().resolve()
    if Path.cwd().resolve() in out.parents:
        print("Refusé : le fichier contient des données personnelles, écris-le hors du dépôt.")
        return 2
    document, report = extract(arguments.archive, arguments.profile_id)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for line in report:
        print(f"- {line}")
    print(
        f"{len(document['skills'])} compétences, {len(document['languages'])} langues, "
        f"{len(document['projects'])} projets ; {len(document['to_review'])} éléments à relire → {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
