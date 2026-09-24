"""Alembic environment.

Migrates the connection given by the caller (``config.attributes["connection"]``, used by the tests),
otherwise the database of ``ROCKY_DATABASE_URL`` (CLI, Compose service ``migrate``).
"""

from __future__ import annotations

import logging

from alembic import context
from sqlalchemy import Connection

import rocky.system.events  # noqa: F401  (registers the events table on metadata)
from rocky.system.config import load_settings
from rocky.system.db import create_db_engine, metadata


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def main() -> None:
    if context.is_offline_mode():
        raise RuntimeError("offline migrations (SQL scripts) are not supported")
    shared: Connection | None = context.config.attributes.get("connection")
    if shared is not None:
        run_migrations(shared)
        return
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("alembic").setLevel(logging.INFO)
    engine = create_db_engine(load_settings().database_url)
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()


main()
