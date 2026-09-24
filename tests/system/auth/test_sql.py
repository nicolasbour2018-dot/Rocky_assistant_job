from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select, update
from sqlalchemy.exc import IntegrityError

from rocky.system.auth.model import AccountStatus, TokenPurpose
from rocky.system.auth.rules import LoginFailure
from rocky.system.auth.sql import SqlAuthStore, accounts
from rocky.system.events import Actor, NewEvent, events

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


@pytest.fixture
def store(db: Connection) -> SqlAuthStore:
    return SqlAuthStore(db)


def test_account_lifecycle(store: SqlAuthStore) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)

    pending = store.find_account("nicolas@example.fr")
    assert pending is not None
    assert (pending.id, pending.status, pending.password_hash) == (
        account_id,
        AccountStatus.PENDING,
        None,
    )

    store.activate_account(account_id, "hash", NOW)
    store.record_login_failure(account_id, LoginFailure(5, LATER))
    locked = store.get_account(account_id)
    assert locked is not None
    assert (locked.status, locked.failed_login_count, locked.locked_until) == (
        AccountStatus.ACTIVE,
        5,
        LATER,
    )

    store.clear_login_failures(account_id)
    cleared = store.get_account(account_id)
    assert cleared is not None
    assert (cleared.failed_login_count, cleared.locked_until) == (0, None)


def test_email_is_unique(store: SqlAuthStore, db: Connection) -> None:
    store.create_account("nicolas@example.fr", NOW)

    with pytest.raises(IntegrityError), db.begin_nested():
        store.create_account("nicolas@example.fr", NOW)


def test_an_active_account_always_has_a_password(
    store: SqlAuthStore, db: Connection
) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            update(accounts).where(accounts.c.id == account_id).values(status="active")
        )


def test_a_token_is_used_once(store: SqlAuthStore) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)
    store.issue_token(account_id, TokenPurpose.ACTIVATION, "h1", NOW, LATER)

    assert store.consume_token("h1", TokenPurpose.PASSWORD_RESET, NOW) is None
    assert store.consume_token("h1", TokenPurpose.ACTIVATION, NOW) == account_id
    assert store.consume_token("h1", TokenPurpose.ACTIVATION, NOW) is None


def test_an_expired_token_is_refused(store: SqlAuthStore) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)
    store.issue_token(account_id, TokenPurpose.ACTIVATION, "h1", NOW, LATER)

    assert store.consume_token("h1", TokenPurpose.ACTIVATION, LATER) is None


def test_a_new_token_cancels_the_previous_one(store: SqlAuthStore) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)
    store.issue_token(account_id, TokenPurpose.ACTIVATION, "old", NOW, LATER)
    store.issue_token(account_id, TokenPurpose.ACTIVATION, "new", NOW, LATER)

    assert store.consume_token("old", TokenPurpose.ACTIVATION, NOW) is None
    assert store.consume_token("new", TokenPurpose.ACTIVATION, NOW) == account_id


def test_sessions_can_be_renewed_and_revoked(store: SqlAuthStore) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)
    store.activate_account(account_id, "hash", NOW)
    store.open_session(account_id, "s1", NOW, LATER)
    store.open_session(account_id, "s2", NOW, LATER)

    session = store.find_session("s1", NOW)
    assert session is not None
    assert (session.account_id, session.expires_at) == (account_id, LATER)
    assert store.find_session("s1", LATER) is None

    store.renew_session(session.id, LATER, LATER + timedelta(days=7))
    assert store.find_session("s1", LATER) is not None

    store.revoke_session("s1", LATER)
    assert store.find_session("s1", LATER) is None
    assert store.find_session("s2", NOW) is not None

    store.revoke_all_sessions(account_id, NOW)
    assert store.find_session("s2", NOW) is None


def test_events_can_name_their_account(store: SqlAuthStore, db: Connection) -> None:
    account_id = store.create_account("nicolas@example.fr", NOW)

    store.append_event(
        NewEvent(type="system.account_invited", actor=Actor.USER, account_id=account_id)
    )

    stored = db.execute(
        select(events.c.type).where(events.c.account_id == account_id)
    ).scalar_one()
    assert stored == "system.account_invited"


def test_an_event_cannot_name_an_unknown_account(
    store: SqlAuthStore, db: Connection
) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        store.append_event(
            NewEvent(type="system.ghost", actor=Actor.SYSTEM, account_id=999_999)
        )
