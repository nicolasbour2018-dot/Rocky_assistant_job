from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import Connection, Engine, func, insert, select, text
from sqlalchemy.exc import IntegrityError

from rocky.system.events import Actor, NewEvent, append_event, events


def test_append_event_stores_every_field(db: Connection) -> None:
    event = NewEvent(
        type="offres.decision_recorded",
        actor=Actor.USER,
        subject_type="offre",
        subject_id="42",
        payload={"value": "interested", "reason": "stack", "scores": [0.5, None]},
    )

    event_id = append_event(db, event)

    row = db.execute(select(events).where(events.c.id == event_id)).one()
    assert (row.type, row.actor, row.subject_type, row.subject_id) == (
        "offres.decision_recorded",
        "user",
        "offre",
        "42",
    )
    assert row.payload == {
        "value": "interested",
        "reason": "stack",
        "scores": [0.5, None],
    }
    assert isinstance(row.occurred_at, datetime)
    assert row.occurred_at.tzinfo is not None


def test_append_event_ids_follow_the_journal_order(db: Connection) -> None:
    first = append_event(db, NewEvent(type="system.first_recorded", actor=Actor.SYSTEM))
    second = append_event(db, NewEvent(type="system.second_recorded", actor=Actor.RULE))

    assert second > first


def test_event_without_subject_has_an_empty_payload(db: Connection) -> None:
    event_id = append_event(db, NewEvent(type="system.started", actor=Actor.SYSTEM))

    row = db.execute(select(events).where(events.c.id == event_id)).one()
    assert (row.subject_type, row.subject_id, row.payload) == (None, None, {})


def test_append_event_does_not_commit(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        append_event(connection, NewEvent(type="system.uncommitted", actor=Actor.AI))
        transaction.rollback()

    with migrated_engine.connect() as connection:
        count = connection.execute(
            select(func.count()).where(events.c.type == "system.uncommitted")
        ).scalar_one()
    assert count == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE events SET type = 'system.rewritten'",
        "DELETE FROM events",
        "TRUNCATE events",
    ],
)
def test_the_journal_refuses_any_change(db: Connection, statement: str) -> None:
    append_event(db, NewEvent(type="system.kept", actor=Actor.SYSTEM))

    with pytest.raises(IntegrityError, match="append-only"), db.begin_nested():
        db.execute(text(statement))


@pytest.mark.parametrize(
    "values",
    [
        {"type": "system.x", "actor": "robot"},
        {"type": "system.x", "actor": "user", "subject_type": "offre"},
    ],
    ids=["unknown actor", "incomplete subject"],
)
def test_the_database_rejects_invalid_rows(
    db: Connection, values: dict[str, str]
) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert(events).values(**values))


@pytest.mark.parametrize(
    "event_type",
    ["decision_recorded", "Offres.decision_recorded", "offres.", "unknown.fact"],
)
def test_new_event_rejects_a_malformed_type(event_type: str) -> None:
    with pytest.raises(ValueError, match="event type"):
        NewEvent(type=event_type, actor=Actor.USER)


@pytest.mark.parametrize(
    ("subject_type", "subject_id"),
    [("offre", None), (None, "42"), ("", "42"), ("offre", "")],
)
def test_new_event_rejects_an_incomplete_subject(
    subject_type: str | None, subject_id: str | None
) -> None:
    with pytest.raises(ValueError, match="subject"):
        NewEvent(
            type="offres.decision_recorded",
            actor=Actor.USER,
            subject_type=subject_type,
            subject_id=subject_id,
        )
