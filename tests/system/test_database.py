from __future__ import annotations

from sqlalchemy import Connection, text


def test_test_database_runs_postgresql_18_or_later(db: Connection) -> None:
    version = db.dialect.server_version_info

    assert version is not None
    assert version >= (18,)


def test_application_role_is_not_superuser(db: Connection) -> None:
    row = db.execute(
        text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles"
            " WHERE rolname = current_user"
        )
    ).one()

    assert tuple(row) == (False, False, False)
