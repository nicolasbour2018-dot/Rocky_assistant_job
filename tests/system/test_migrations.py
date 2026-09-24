"""Exit criterion of step B2: upgrade and downgrade work on an empty database."""

from __future__ import annotations

from collections.abc import Callable

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

import rocky.system.tables  # noqa: F401  (registers every table on metadata)
from rocky.system.db import metadata

HEAD_TABLES = {"alembic_version", "events", "accounts", "account_tokens", "sessions"}


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
