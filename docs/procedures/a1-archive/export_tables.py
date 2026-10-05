"""Exporte les tables de l'ancien Rocky en Parquet et CSV (étape A1).

Lit une copie restaurée de la base, jamais la base en service. Le mot de passe vient de PGPASSWORD.
Types : JSONB → texte JSON ; tableaux → liste de chaînes en Parquet, texte JSON en CSV ;
numeric → float64 ; horodatages conservés avec leur fuseau (UTC).
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text

# Tables exportées, rangées par catégorie du plan v2 (A1). Colonnes exclues : secrets d'authentification.
TABLES: dict[str, list[str]] = {
    "offres": ["job_offers"],
    "scores": ["job_matches", "job_match_history"],
    "rattachements": ["profile_jobs"],
    "candidatures": ["applications", "application_documents", "application_browser_sessions"],
    "evenements": ["application_events", "watch_runs"],
    "mails_et_decisions_gmail": ["email_messages"],
    "profil": [
        "candidate_profiles",
        "profile_localizations",
        "candidate_skills",
        "profile_projects",
        "profile_documents",
        "profile_analyses",
        "monitoring_notes",
    ],
    "comptes": ["users"],
}
EXCLUDED_COLUMNS = {"users": {"password_hash"}}
# Restent uniquement dans le dump : sessions et jetons de compte.
NOT_EXPORTED = ["user_sessions", "account_tokens"]


def column_types(conn, table: str) -> dict[str, str]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
        ),
        {"t": table},
    )
    return {name: kind for name, kind in rows}


def to_json_text(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def export_table(conn, table: str, out: Path) -> dict[str, object]:
    types = column_types(conn, table)
    if not types:
        raise RuntimeError(f"table absente de la base : {table}")
    columns = [c for c in types if c not in EXCLUDED_COLUMNS.get(table, set())]
    select = ", ".join(f'"{c}"' for c in columns)
    order = '"id"' if "id" in columns else ", ".join(f'"{c}"' for c in columns[:2])
    df = pd.read_sql(text(f'SELECT {select} FROM public."{table}" ORDER BY {order}'), conn)  # noqa: S608

    arrays = [c for c in columns if types[c] == "ARRAY"]
    jsons = [c for c in columns if types[c] in ("json", "jsonb")]
    for c in jsons:
        df[c] = df[c].map(to_json_text)
    for c in columns:
        if types[c] == "numeric":
            df[c] = df[c].map(lambda v: float(v) if isinstance(v, Decimal) else v).astype("float64")

    parquet_df = df.copy()
    for c in arrays:
        parquet_df[c] = parquet_df[c].map(lambda v: None if v is None else [str(x) for x in v])
    schema_fields = []
    for c in columns:
        if c in arrays:
            schema_fields.append(pa.field(c, pa.list_(pa.string())))
        elif c in jsons or types[c] == "text":
            schema_fields.append(pa.field(c, pa.string()))
        else:
            schema_fields.append(pa.field(c, pa.Schema.from_pandas(parquet_df[[c]], preserve_index=False).field(c).type))
    table_pa = pa.Table.from_pandas(parquet_df, schema=pa.schema(schema_fields), preserve_index=False)
    pq.write_table(table_pa, out / "parquet" / f"{table}.parquet")

    csv_df = df.copy()
    for c in arrays:
        csv_df[c] = csv_df[c].map(to_json_text)
    csv_df.to_csv(out / "csv" / f"{table}.csv", index=False, encoding="utf-8")

    return {"lignes": len(df), "colonnes": columns, "types_postgres": {c: types[c] for c in columns}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="postgresql://user@hôte:port/base (mot de passe via PGPASSWORD)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    (args.out / "parquet").mkdir(parents=True, exist_ok=True)
    (args.out / "csv").mkdir(parents=True, exist_ok=True)
    engine = create_engine(args.dsn.replace("postgresql://", "postgresql+psycopg2://", 1))

    manifest: dict[str, object] = {"source": args.dsn.rsplit("/", 1)[-1], "non_exportees": NOT_EXPORTED, "tables": {}}
    with engine.connect() as conn:
        conn.execute(text("SET TimeZone = 'UTC'"))
        for category, tables in TABLES.items():
            for table in tables:
                info = export_table(conn, table, args.out)
                info["categorie"] = category
                if table in EXCLUDED_COLUMNS:
                    info["colonnes_exclues"] = sorted(EXCLUDED_COLUMNS[table])
                manifest["tables"][table] = info  # type: ignore[index]
                print(f"{category:26} {table:30} {info['lignes']:>6} lignes")

    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
