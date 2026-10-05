"""Vérifie que les documents référencés par la base sont présents dans la copie (étape A1).

Correspondance des chemins enregistrés par l'ancien Rocky :
  /data/<x>   → documents/volume/<x>        (volume Docker rocky-assistant-data)
  data/<x>    → documents/hote/data/<x>     (ancien ./data de l'hôte, relatif au dépôt)
  output/<x>  → documents/hote/output/<x>, puis output/previous_outputs/<x> (fichiers déplacés en août)
  autre       → cherché tel quel dans documents/volume
Le rapport liste les absents ; il n'échoue pas : une absence est un fait de l'ancien Rocky à expliquer.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, text

REFERENCES = [
    ("application_documents", "path"),
    ("applications", "cv_path"),
    ("applications", "letter_docx_path"),
    ("applications", "letter_pdf_path"),
    ("profile_documents", "source_path"),
    ("profile_documents", "preview_pdf_path"),
    ("candidate_profiles", "cv_path"),
]


def candidates(documents: Path, stored: str) -> list[Path]:
    if stored.startswith("/data/"):
        return [documents / "volume" / stored.removeprefix("/data/")]
    if stored.startswith("data/"):
        rest = stored.removeprefix("data/")
        return [documents / "hote" / "data" / rest, documents / "volume" / rest]
    if stored.startswith("output/"):
        rest = stored.removeprefix("output/")
        output = documents / "hote" / "output"
        return [output / rest, output / "previous_outputs" / rest, documents / "volume" / stored]
    return [documents / "volume" / stored]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--documents", required=True, type=Path)
    args = parser.parse_args()

    engine = create_engine(args.dsn.replace("postgresql://", "postgresql+psycopg2://", 1))
    present = absent = 0
    lines: list[str] = []
    with engine.connect() as conn:
        for table, column in REFERENCES:
            rows = conn.execute(
                text(f'SELECT DISTINCT "{column}" FROM public."{table}" WHERE coalesce("{column}", \'\') <> \'\' ORDER BY 1')  # noqa: S608
            ).scalars()
            for stored in rows:
                if any(p.is_file() for p in candidates(args.documents, stored)):
                    present += 1
                else:
                    absent += 1
                    lines.append(f"ABSENT  {table}.{column}  {stored}")

    print("Documents référencés par la base job_assistant")
    print(f"Présents dans la copie : {present}")
    print(f"Absents                : {absent}")
    if lines:
        print()
        print("\n".join(lines))


if __name__ == "__main__":
    main()
