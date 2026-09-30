"""Exit criterion of step B2: upgrade and downgrade work on an empty database."""

from __future__ import annotations

from collections.abc import Callable

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

import rocky.system.tables  # noqa: F401  (registers every table on metadata)
from rocky.system.db import metadata
from tests.conftest import alembic_config

HEAD_TABLES = {
    "alembic_version",
    "events",
    "accounts",
    "account_tokens",
    "sessions",
    "profiles",
    "search_tracks",
    "skills",
    "skill_terms",
    "languages",
    "experiences",
    "projects",
    "experience_skills",
    "project_skills",
    "job_offers",
    "offer_tracks",
    "offer_scores",
    "watch_runs",
    "watch_run_sources",
    "job_decisions",
    "offer_summaries",
    "applications",
    "application_changes",
    "profile_links",
    "hobbies",
    "skill_groups",
    "cv_templates",
    "application_cv_selections",
    "glossary_terms",
    "translation_memory",
}


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def function_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT p.proname FROM pg_proc p"
                " JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = current_schema()"
            )
        )
        return {row.proname for row in rows}


def test_upgrade_and_downgrade_work_on_an_empty_database(
    empty_engine: Engine, migrate_schema: Callable[[Engine, str], None]
) -> None:
    assert table_names(empty_engine) == set()

    migrate_schema(empty_engine, "head")
    assert table_names(empty_engine) == HEAD_TABLES
    assert function_names(empty_engine) == {"rocky_forbid_event_change"}

    migrate_schema(empty_engine, "base")
    assert table_names(empty_engine) == {"alembic_version"}
    assert function_names(empty_engine) == set()

    migrate_schema(empty_engine, "head")
    assert table_names(empty_engine) == HEAD_TABLES


def test_declared_tables_match_migrations(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, metadata)

    assert differences == []


def test_the_links_of_a_profile_move_to_their_list_and_back(
    empty_engine: Engine, migrate_schema: Callable[[Engine, str], None]
) -> None:
    """Migration 0007 (decision D2, Q8): LinkedIn, GitHub and portfolio become links, in that order."""
    migrate_schema(empty_engine, "0006")
    with empty_engine.begin() as connection:
        account_id = connection.execute(
            text(
                "INSERT INTO accounts (email, status) VALUES ('n@example.fr', 'pending')"
                " RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO profiles (account_id, linkedin_url, portfolio_url) VALUES"
                " (:account, 'https://www.linkedin.com/in/n', 'https://n.example.fr')"
            ),
            {"account": account_id},
        )

    migrate_schema(empty_engine, "0007")
    with empty_engine.connect() as connection:
        links = connection.execute(
            text("SELECT label, url FROM profile_links ORDER BY position")
        ).all()
    assert [tuple(link) for link in links] == [
        ("LinkedIn", "https://www.linkedin.com/in/n"),
        ("Portfolio", "https://n.example.fr"),
    ]

    with empty_engine.begin() as connection:
        command.downgrade(alembic_config(connection), "0006")
    with empty_engine.connect() as connection:
        row = connection.execute(
            text("SELECT linkedin_url, github_url, portfolio_url FROM profiles")
        ).one()
    assert tuple(row) == ("https://www.linkedin.com/in/n", None, "https://n.example.fr")
