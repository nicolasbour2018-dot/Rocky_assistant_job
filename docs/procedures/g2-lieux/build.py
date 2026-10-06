"""G2: build the place reference of ``rocky.profil.places`` from the INSEE Code officiel géographique (see README.md).

Reads the three COG files (communes, départements, régions), downloaded beforehand into ``--cog``, and writes one CSV
with only what the score reads: kind, code, name, commune (an arrondissement's), département, région. Communes and municipal arrondissements are
kept; associated and delegated communes are not (an offer names the commune of today).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

YEAR = 2026
KINDS = {"COM": "commune", "ARM": "arrondissement"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cog", type=Path, required=True, help="folder of the downloaded COG files")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    regions = _rows(args.cog / f"v_region_{YEAR}.csv")
    departements = _rows(args.cog / f"v_departement_{YEAR}.csv")
    communes = _rows(args.cog / f"v_commune_{YEAR}.csv")
    region_of = {row["DEP"]: row["REG"] for row in departements}
    parents = {row["COM"]: row for row in communes if row["TYPECOM"] == "COM"}
    lines = [("region", row["REG"], row["LIBELLE"], "", "", row["REG"]) for row in regions]
    lines += [("departement", row["DEP"], row["LIBELLE"], "", row["DEP"], row["REG"]) for row in departements]
    for row in communes:
        kind = KINDS.get(row["TYPECOM"])
        if kind is None:
            continue
        # An arrondissement carries no département: its commune's.
        departement = row["DEP"] or parents[row["COMPARENT"]]["DEP"]
        region = row["REG"] or region_of[departement]
        commune = row["COMPARENT"] if kind == "arrondissement" else row["COM"]
        lines.append((kind, row["COM"], row["LIBELLE"], commune, departement, region))
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("type", "code", "nom", "commune", "departement", "region"))
        writer.writerows(lines)
    print(f"{len(lines)} lieux écrits dans {args.out}")


if __name__ == "__main__":
    main()
