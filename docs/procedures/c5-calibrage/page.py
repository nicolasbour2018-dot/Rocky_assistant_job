"""C5 calibration: build the local annotation page (see README.md).

Runs with the host's python3 (standard library only). Reads the archive and ``echantillon.json`` and writes
``index.html`` into a folder **outside the repository**: the page holds the texts of the postings, which stay out of
Git (A1). It shows no score and no v1 status (decision C5, Q5).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import HERE, load_archive

REPOSITORY = HERE.parents[2]
# Reasons (decision C5, Q9): code → label. Each chosen reason carries a sign, + (attracts) or − (puts off).
REASONS = {
    "metier": "Métier / intitulé",
    "competences": "Compétences / stack",
    "seniorite": "Séniorité",
    "secteur": "Secteur / domaine",
    "entreprise": "Entreprise",
    "contrat": "Contrat",
    "lieu": "Lieu",
    "teletravail": "Télétravail",
    "salaire": "Salaire / TJM",
    "langue": "Langue",
    "condition": "Condition bloquante",
    "piste": "Mauvaise piste",
    "floue": "Annonce floue ou incomplète",
    "autre": "Autre (commentaire)",
}


def facts(row: dict[str, str]) -> dict[str, str]:
    """What a reader of the posting sees: no score, no status, no date."""
    bounds = (row["salary_min"], row["salary_max"])
    amount = " – ".join(f"{float(value):,.0f}".replace(",", " ") for value in bounds if value)
    salary = f"{amount} {row['salary_currency']}".strip() if amount else ""
    return {
        "title": row["job_title"],
        "company": row["company_name"],
        "place": ", ".join(value for value in (row["city"], row["country"]) if value),
        "contract": row["contract_type"],
        "remote": row["remote_policy"],
        "salary": salary,
        "source": row["source_name"],
        "url": row["source_url"],
        "text": row["responsibilities"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="folder outside the repository")
    arguments = parser.parse_args()
    out = arguments.out.resolve()
    if out.is_relative_to(REPOSITORY.resolve()):
        print(f"Refusé : {out} est dans le dépôt ; les textes des annonces restent hors de Git.", file=sys.stderr)
        return 1
    archive = load_archive(arguments.archive)
    sample = json.loads((HERE / "echantillon.json").read_text())
    data = {
        "seed": sample["seed"],
        "order": sample["order"],
        "postings": {item["id"]: facts(archive.rows[item["id"]]) for item in sample["sample"]},
        "reasons": REASONS,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text((HERE / "page.html").read_text().replace("__DATA__", payload))
    print(f"{len(sample['order'])} annonces → {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
