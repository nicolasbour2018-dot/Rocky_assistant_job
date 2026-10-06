from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, func, insert, select, text
from sqlalchemy.exc import IntegrityError

from rocky.system.auth.sql import SqlAuthStore
from rocky.system.events import (
    Actor,
    NewEvent,
    append_event,
    events,
    events_of,
    first_occurrences,
    user_days,
)


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


# What the cockpit reads in the journal (decision G3)


def _account(db: Connection) -> int:
    return SqlAuthStore(db).create_account(f"{uuid4().hex}@example.fr", NOW)


def _at(
    db: Connection,
    account_id: int,
    kind: str,
    moment: datetime,
    actor: Actor = Actor.USER,
) -> None:
    db.execute(
        insert(events).values(
            type=kind,
            actor=actor.value,
            account_id=account_id,
            occurred_at=moment,
            payload={},
        )
    )


NOW = datetime(2026, 10, 7, 10, tzinfo=UTC)


def test_the_events_of_an_account_since_a_moment(db: Connection) -> None:
    account_id, other = _account(db), _account(db)
    _at(db, account_id, "messages.alert_read", NOW - timedelta(days=8))
    _at(db, account_id, "messages.alert_read", NOW - timedelta(days=1))
    _at(db, account_id, "messages.sync_finished", NOW)
    _at(db, other, "messages.alert_read", NOW)

    found = events_of(db, account_id, ("messages.alert_read",), NOW - timedelta(days=7))

    assert [(e.type, e.occurred_at) for e in found] == [
        ("messages.alert_read", NOW - timedelta(days=1))
    ]


def test_the_first_time_of_each_type(db: Connection) -> None:
    account_id = _account(db)
    _at(db, account_id, "profil.track_created", NOW)
    _at(db, account_id, "profil.track_created", NOW - timedelta(days=3))

    assert first_occurrences(
        db, account_id, ("profil.track_created", "profil.profile_imported")
    ) == {"profil.track_created": NOW - timedelta(days=3)}


def test_the_days_of_the_user_are_paris_days(db: Connection) -> None:
    account_id = _account(db)
    # 22:30 UTC on 5 October is 00:30 on the 6th in Paris.
    _at(
        db,
        account_id,
        "offres.decision_recorded",
        datetime(2026, 10, 5, 22, 30, tzinfo=UTC),
    )
    _at(db, account_id, "candidatures.stage_changed", NOW)
    _at(
        db,
        account_id,
        "candidatures.stage_changed",
        NOW - timedelta(days=4),
        Actor.RULE,
    )
    _at(db, account_id, "profil.track_created", NOW - timedelta(days=5))

    days = user_days(
        db, account_id, ("offres", "candidatures"), NOW - timedelta(days=30)
    )

    assert days == {date(2026, 10, 6), date(2026, 10, 7)}
