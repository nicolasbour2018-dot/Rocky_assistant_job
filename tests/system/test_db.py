from __future__ import annotations

from rocky.system.db import create_db_engine


def test_create_db_engine_forces_the_psycopg_driver() -> None:
    engine = create_db_engine("postgresql://user:secret@host:5432/rocky")

    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.password == "secret"
    assert engine.url.database == "rocky"
