"""SQL access of authentication: the only place where accounts, tokens and sessions are queried."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Row,
    Table,
    Text,
    func,
    insert,
    select,
    update,
)

from rocky.system.auth.model import (
    Account,
    AccountStatus,
    SessionRecord,
    TokenPurpose,
)
from rocky.system.auth.rules import LoginFailure
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event


def _in(column: str, values: type[AccountStatus | TokenPurpose]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


accounts = Table(
    "accounts",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("password_hash", Text),
    Column("status", Text, nullable=False),
    Column("email_verified_at", DateTime(timezone=True)),
    Column("failed_login_count", Integer, nullable=False, server_default="0"),
    Column("locked_until", DateTime(timezone=True)),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint(_in("status", AccountStatus), name="status"),
    CheckConstraint(
        "status <> 'active' OR password_hash IS NOT NULL", name="active_has_password"
    ),
)

account_tokens = Table(
    "account_tokens",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    # Set when the token is used, or cancelled by a newer token of the same purpose.
    Column("used_at", DateTime(timezone=True)),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint(_in("purpose", TokenPurpose), name="purpose"),
    Index("ix_account_tokens_account_purpose", "account_id", "purpose"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Index("ix_sessions_account_id", "account_id"),
)


class SqlAuthStore:
    """``AuthStore`` on a connection already inside a transaction; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def find_account(self, email: str) -> Account | None:
        row = self._conn.execute(
            select(accounts).where(accounts.c.email == email)
        ).one_or_none()
        return None if row is None else _account(row)

    def get_account(self, account_id: int) -> Account | None:
        row = self._conn.execute(
            select(accounts).where(accounts.c.id == account_id)
        ).one_or_none()
        return None if row is None else _account(row)

    def create_account(self, email: str, now: datetime) -> int:
        statement = (
            insert(accounts)
            .values(email=email, status=AccountStatus.PENDING.value, created_at=now)
            .returning(accounts.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def activate_account(
        self, account_id: int, password_hash: str, now: datetime
    ) -> None:
        self._update_account(
            account_id,
            password_hash=password_hash,
            status=AccountStatus.ACTIVE.value,
            email_verified_at=now,
            failed_login_count=0,
            locked_until=None,
        )

    def set_password(self, account_id: int, password_hash: str) -> None:
        self._update_account(
            account_id,
            password_hash=password_hash,
            failed_login_count=0,
            locked_until=None,
        )

    def record_login_failure(self, account_id: int, failure: LoginFailure) -> None:
        self._update_account(
            account_id,
            failed_login_count=failure.failures,
            locked_until=failure.locked_until,
        )

    def clear_login_failures(self, account_id: int) -> None:
        self._update_account(account_id, failed_login_count=0, locked_until=None)

    def issue_token(
        self,
        account_id: int,
        purpose: TokenPurpose,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        self._conn.execute(
            update(account_tokens)
            .where(
                account_tokens.c.account_id == account_id,
                account_tokens.c.purpose == purpose.value,
                account_tokens.c.used_at.is_(None),
            )
            .values(used_at=now)
        )
        self._conn.execute(
            insert(account_tokens).values(
                account_id=account_id,
                purpose=purpose.value,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=now,
            )
        )

    def consume_token(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int | None:
        statement = (
            update(account_tokens)
            .where(
                account_tokens.c.token_hash == token_hash,
                account_tokens.c.purpose == purpose.value,
                account_tokens.c.used_at.is_(None),
                account_tokens.c.expires_at > now,
            )
            .values(used_at=now)
            .returning(account_tokens.c.account_id)
        )
        account_id = self._conn.execute(statement).scalar_one_or_none()
        return None if account_id is None else int(account_id)

    def peek_token(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int | None:
        account_id = self._conn.execute(
            select(account_tokens.c.account_id).where(
                account_tokens.c.token_hash == token_hash,
                account_tokens.c.purpose == purpose.value,
                account_tokens.c.used_at.is_(None),
                account_tokens.c.expires_at > now,
            )
        ).scalar_one_or_none()
        return None if account_id is None else int(account_id)

    def open_session(
        self, account_id: int, token_hash: str, now: datetime, expires_at: datetime
    ) -> None:
        self._conn.execute(
            insert(sessions).values(
                account_id=account_id,
                token_hash=token_hash,
                created_at=now,
                last_seen_at=now,
                expires_at=expires_at,
            )
        )

    def find_session(self, token_hash: str, now: datetime) -> SessionRecord | None:
        row = self._conn.execute(
            select(sessions).where(
                sessions.c.token_hash == token_hash,
                sessions.c.revoked_at.is_(None),
                sessions.c.expires_at > now,
            )
        ).one_or_none()
        if row is None:
            return None
        return SessionRecord(
            id=row.id,
            account_id=row.account_id,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
        )

    def renew_session(
        self, session_id: int, now: datetime, expires_at: datetime
    ) -> None:
        self._conn.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(last_seen_at=now, expires_at=expires_at)
        )

    def revoke_session(self, token_hash: str, now: datetime) -> None:
        self._conn.execute(
            update(sessions)
            .where(sessions.c.token_hash == token_hash, sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def revoke_all_sessions(self, account_id: int, now: datetime) -> None:
        self._conn.execute(
            update(sessions)
            .where(sessions.c.account_id == account_id, sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def append_event(self, event: NewEvent) -> None:
        append_event(self._conn, event)

    def _update_account(self, account_id: int, **values: Any) -> None:
        self._conn.execute(
            update(accounts).where(accounts.c.id == account_id).values(**values)
        )


def _account(row: Row[Any]) -> Account:
    return Account(
        id=row.id,
        email=row.email,
        status=AccountStatus(row.status),
        password_hash=row.password_hash,
        failed_login_count=row.failed_login_count,
        locked_until=row.locked_until,
    )
