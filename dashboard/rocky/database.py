"""Connexion et initialisation de la base Rocky."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, make_url

from .config import Settings
from .errors import ConfigurationError

REQUIRED_SCHEMA: dict[str, frozenset[str]] = {
    "users": frozenset({"id", "email", "password_hash", "status"}),
    "user_sessions": frozenset({"id", "user_id", "token_hash", "expires_at"}),
    "account_tokens": frozenset({"id", "user_id", "purpose", "token_hash"}),
    "job_offers": frozenset(
        {
            "id",
            "user_id",
            "application_url",
            "collector_name",
            "work_schedule",
            "description_is_full",
            "detected_language",
            "language_confidence",
            "language_override",
        }
    ),
    "candidate_profiles": frozenset(
        {
            "id",
            "user_id",
            "full_name",
            "email",
            "onboarding_status",
        }
    ),
    "profile_localizations": frozenset(
        {"profile_id", "locale", "target_domains", "translation_status"}
    ),
    "profile_documents": frozenset(
        {"id", "profile_id", "locale", "kind", "version", "is_current"}
    ),
    "profile_analyses": frozenset({"profile_id", "analysis_data", "status"}),
    "candidate_skills": frozenset({"id", "profile_id", "skill_name_en"}),
    "profile_jobs": frozenset({"profile_id", "job_id"}),
    "job_matches": frozenset({"job_id", "profile_id", "profile_locale"}),
    "job_match_history": frozenset(
        {"job_id", "profile_id", "profile_locale", "scoring_version"}
    ),
    "applications": frozenset(
        {
            "id",
            "job_id",
            "profile_id",
            "status_source",
            "last_email_at",
            "profile_locale",
        }
    ),
    "profile_projects": frozenset({"id", "profile_id", "locale", "slug"}),
    "application_documents": frozenset({"id", "application_id", "kind", "path"}),
    "application_events": frozenset(
        {"id", "application_id", "old_status", "new_status", "event_type"}
    ),
    "email_messages": frozenset(
        {
            "id",
            "gmail_message_id",
            "gmail_account",
            "user_id",
            "extracted_links",
            "classification_manual",
        }
    ),
    "application_browser_sessions": frozenset(
        {"id", "application_id", "target_url", "status"}
    ),
    "watch_runs": frozenset(
        {"id", "profile_id", "user_id", "source_results", "searched_job_titles"}
    ),
    "monitoring_notes": frozenset({"id", "user_id", "profile_id", "content"}),
}


def create_db_engine(settings: Settings) -> Engine:
    """Crée le moteur sans ouvrir immédiatement une connexion."""
    if not settings.database_url:
        raise ConfigurationError(
            "La connexion PostgreSQL n'est pas configurée dans le fichier .env."
        )
    options: dict[str, Any] = {"pool_pre_ping": True}
    if settings.database_url.startswith("sqlite"):
        options["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }
    return create_engine(settings.database_url, **options)


def ensure_database_exists(settings: Settings) -> bool:
    """Crée la base cible si elle manque."""
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
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.db_name))
            )
            return True
    finally:
        connection.close()


def _validate_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(REQUIRED_SCHEMA) - existing_tables)
    missing_columns: dict[str, list[str]] = {}
    for table_name, required_columns in REQUIRED_SCHEMA.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing = sorted(required_columns - existing_columns)
        if missing:
            missing_columns[table_name] = missing
    if not missing_tables and not missing_columns:
        return

    details: list[str] = []
    if missing_tables:
        details.append("tables absentes : " + ", ".join(missing_tables))
    if missing_columns:
        details.append(
            "colonnes absentes : "
            + "; ".join(
                f"{table}({', '.join(columns)})"
                for table, columns in sorted(missing_columns.items())
            )
        )
    raise ConfigurationError(
        "Le schéma de la base est incompatible avec cette version de Rocky ; "
        + " - ".join(details)
        + ". Utilise une base vide créée avec les schémas SQL courants."
    )


def initialize_database(engine: Engine, settings: Settings) -> None:
    """Crée une base vide ou valide une base Rocky déjà au schéma courant."""
    existing_tables = set(inspect(engine).get_table_names())
    if existing_tables & set(REQUIRED_SCHEMA):
        _validate_schema(engine)
        return

    schema_name = (
        "schema_sqlite.sql" if engine.dialect.name == "sqlite" else "schema.sql"
    )
    schema = (settings.project_dir / "database" / schema_name).read_text(
        encoding="utf-8"
    )
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
    _validate_schema(engine)
