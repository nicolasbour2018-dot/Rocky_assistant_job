"""Database access shared by every module: the common metadata and the engine factory."""

from __future__ import annotations

from sqlalchemy import URL, Engine, MetaData, create_engine, make_url

# Deterministic constraint and index names, so that a migration can always name what it drops.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

# Every module declares its tables on this metadata, in its own SQL access file.
metadata = MetaData(naming_convention=NAMING_CONVENTION)

DRIVER = "postgresql+psycopg"


def create_db_engine(database_url: str | URL) -> Engine:
    """Engine for a libpq URL (``postgresql://...``), always through the psycopg 3 driver."""
    url = make_url(database_url).set(drivername=DRIVER)
    return create_engine(url, pool_pre_ping=True)
