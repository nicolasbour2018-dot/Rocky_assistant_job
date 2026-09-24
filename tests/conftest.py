"""Shared fixtures for the new Rocky tests (tests/<module>/)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

# The flat tests/test_*.py belong to the old Rocky (read-only until F2) and are never collected.
collect_ignore_glob = ["test_*.py"]

TEST_DATABASE_URL_VAR = "ROCKY_TEST_DATABASE_URL"
# Throwaway local test database from docker-compose.yml (service test-db); not a secret.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql://rocky_app:rocky_test@127.0.0.1:55432/rocky_test"
)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ.get(TEST_DATABASE_URL_VAR) or DEFAULT_TEST_DATABASE_URL


@pytest.fixture
def pg_connection(test_database_url: str) -> Iterator[psycopg.Connection]:
    """Connection to the test database; an unreachable database fails the test, it is never skipped."""
    with psycopg.connect(test_database_url, connect_timeout=5) as connection:
        yield connection
