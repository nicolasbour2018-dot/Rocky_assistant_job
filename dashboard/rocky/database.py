"""Connexion et initialisation de PostgreSQL."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, make_url, text

from .config import Settings
from .contracts import normalize_contract_details
from .errors import ConfigurationError


def create_db_engine(settings: Settings) -> Engine:
    """Crée le moteur sans ouvrir immédiatement une connexion."""
    if not settings.database_url:
        raise ConfigurationError(
            "La connexion PostgreSQL n'est pas configurée dans le fichier .env."
        )
    options = {"pool_pre_ping": True}
    if settings.database_url.startswith("sqlite"):
        options["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }
    return create_engine(settings.database_url, **options)


def ensure_database_exists(settings: Settings) -> bool:
    """Crée la base cible si elle manque.

    Retourne True uniquement lorsqu'une nouvelle base a été créée. La requête
    utilise un identifiant SQL sécurisé et ne journalise jamais le mot de passe.
    """
    if not settings.database_url:
        raise ConfigurationError(
            "La connexion PostgreSQL n'est pas configurée dans le fichier .env."
        )
    if settings.database_url.startswith("sqlite"):
        database_path = make_url(settings.database_url).database
        if not database_path or database_path == ":memory:":
            return False
        path = Path(database_path)
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        return not existed

    import psycopg2
    from psycopg2 import sql

    connection = psycopg2.connect(
        dbname="postgres",
        user=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (settings.db_name,),
            )
            if cursor.fetchone():
                return False
            cursor.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(settings.db_name)
                )
            )
            return True
    finally:
        connection.close()


def initialize_database(engine: Engine, settings: Settings) -> None:
    """Applique le schéma idempotent livré avec Rocky."""
    schema_name = (
        "schema_sqlite.sql" if engine.dialect.name == "sqlite" else "schema.sql"
    )
    schema_path = settings.project_dir / "database" / schema_name
    schema = schema_path.read_text(encoding="utf-8")
    if engine.dialect.name == "sqlite":
        raw_connection = engine.raw_connection()
        try:
            raw_connection.executescript(schema)
            raw_connection.commit()
        finally:
            raw_connection.close()
    else:
        with engine.begin() as connection:
            connection.exec_driver_sql(schema)
    _ensure_job_offer_columns(engine)
    _ensure_watch_run_columns(engine)
    _repair_contract_columns(engine)
    _repair_description_flags(engine)
    _repair_incomplete_statuses(engine)


def _ensure_job_offer_columns(engine: Engine) -> None:
    """Ajoute les nouvelles colonnes aux anciennes bases SQLite.

    PostgreSQL est migré par ``ADD COLUMN IF NOT EXISTS`` dans son schéma.
    SQLite ne gère pas cette syntaxe sur toutes les versions prises en charge,
    donc la présence de la colonne est vérifiée explicitement.
    """
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("job_offers")
    }
    missing_columns = {
        "collector_name": "TEXT",
        "work_schedule": "TEXT",
        "description_is_full": "BOOLEAN NOT NULL DEFAULT 0",
        "description_enrichment_source": "TEXT",
        "description_enrichment_external_id": "TEXT",
    }
    with engine.begin() as connection:
        for column_name, column_type in missing_columns.items():
            if column_name in columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE job_offers ADD COLUMN {column_name} {column_type}"
            )


def _ensure_watch_run_columns(engine: Engine) -> None:
    """Ajoute les diagnostics de connecteurs aux anciennes bases SQLite."""
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("watch_runs")
    }
    if "source_results" in columns:
        return
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE watch_runs "
            "ADD COLUMN source_results TEXT NOT NULL DEFAULT '[]'"
        )


def _repair_contract_columns(engine: Engine) -> None:
    """Répare sans perte les annonces créées avant la séparation des champs."""
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, contract_type, work_schedule,
                       responsibilities, short_description
                FROM job_offers
                """
            )
        ).mappings().all()
        for row in rows:
            contract_type, work_schedule = normalize_contract_details(
                row.get("contract_type"),
                row.get("work_schedule"),
                row.get("responsibilities"),
                row.get("short_description"),
            )
            current_contract = str(row.get("contract_type") or "").strip()
            current_schedule = str(row.get("work_schedule") or "").strip()
            if (
                contract_type == current_contract
                and work_schedule == current_schedule
            ):
                continue
            connection.execute(
                text(
                    """
                    UPDATE job_offers
                    SET contract_type = :contract_type,
                        work_schedule = :work_schedule
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": row["id"],
                    "contract_type": contract_type or None,
                    "work_schedule": work_schedule or None,
                },
            )


def _repair_description_flags(engine: Engine) -> None:
    """Répare les indicateurs historiques sans inventer de texte complet."""
    with engine.begin() as connection:
        # Les anciens imports Apec ont pu prendre l'extrait de recherche pour
        # une description complète. Un extrait coupé ne doit jamais être scoré.
        connection.execute(
            text(
                """
                UPDATE job_offers
                SET description_is_full = FALSE
                WHERE LOWER(source_name) = 'apec'
                  AND responsibilities IS NOT NULL
                  AND (
                      TRIM(responsibilities) LIKE '%...'
                      OR TRIM(responsibilities) LIKE '%…'
                  )
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE job_offers
                SET description_is_full = TRUE
                WHERE description_is_full = FALSE
                  AND source_name IN ('France Travail', 'Wellfound')
                  AND responsibilities IS NOT NULL
                  AND LENGTH(TRIM(responsibilities)) > 0
                """
            )
        )


def _repair_incomplete_statuses(engine: Engine) -> None:
    """Rend visibles les aperçus historiques sans écraser un choix utilisateur."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE job_offers
                SET status = 'INCOMPLÈTE'
                WHERE description_is_full = FALSE
                  AND status = 'NOUVELLE'
                """
            )
        )
