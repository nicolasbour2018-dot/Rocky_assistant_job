"""Shared fixtures for the new Rocky tests (tests/<module>/).

Isolation: each pytest run migrates its own PostgreSQL schema, dropped at the end, and each test runs in a
transaction rolled back afterwards. Runs from the host and from the check service never see each other.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from rocky.system.db import create_db_engine

# The flat tests/test_*.py belong to the old Rocky (read-only until F2) and are never collected.
collect_ignore_glob = ["test_*.py"]

TEST_DATABASE_URL_VAR = "ROCKY_TEST_DATABASE_URL"
# Throwaway local test database from docker-compose.yml (service test-db); not a secret.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://rocky_app:rocky_test@127.0.0.1:55432/rocky_test"
)
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def alembic_config(connection: Connection) -> Config:
    """Alembic configuration of pyproject.toml, bound to ``connection``."""
    return Config(toml_file=PYPROJECT, attributes={"connection": connection})


def migrate(engine: Engine, target: str = "head") -> None:
    """Upgrade (or downgrade, for ``target="base"``) the schema of ``engine`` and commit."""
    with engine.begin() as connection:
        config = alembic_config(connection)
        if target == "base":
            command.downgrade(config, "base")
        else:
            command.upgrade(config, target)


@contextmanager
def isolated_schema(database_url: str) -> Iterator[Engine]:
    """Engine whose search_path is a new, empty schema, dropped on exit."""
    name = f"test_{secrets.token_hex(6)}"
    admin = create_db_engine(database_url)
    with admin.begin() as connection:
        connection.execute(CreateSchema(name))
    url = make_url(database_url).update_query_dict({"options": f"-csearch_path={name}"})
    engine = create_db_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(name, cascade=True, if_exists=True))
        admin.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ.get(TEST_DATABASE_URL_VAR) or DEFAULT_TEST_DATABASE_URL


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: str) -> Iterator[Engine]:
    """Schema of this run, at the latest migration. An unreachable database fails, it never skips."""
    with isolated_schema(test_database_url) as engine:
        migrate(engine)
        yield engine


@pytest.fixture
def empty_engine(test_database_url: str) -> Iterator[Engine]:
    """Fresh schema without any migration."""
    with isolated_schema(test_database_url) as engine:
        yield engine


@pytest.fixture
def migrate_schema() -> Callable[[Engine, str], None]:
    """The ``migrate`` helper, for tests that drive Alembic themselves."""
    return migrate


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Connection]:
    """Connection in a transaction rolled back after the test."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
