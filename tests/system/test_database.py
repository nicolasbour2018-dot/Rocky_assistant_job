from __future__ import annotations

import psycopg


def test_test_database_runs_postgresql_18_or_later(
    pg_connection: psycopg.Connection,
) -> None:
    assert pg_connection.info.server_version >= 180000


def test_application_role_is_not_superuser(pg_connection: psycopg.Connection) -> None:
    row = pg_connection.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles"
        " WHERE rolname = current_user"
    ).fetchone()

    assert row == (False, False, False)
