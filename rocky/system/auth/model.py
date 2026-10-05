"""Authentication records and the storage port used by the use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from rocky.system.auth.rules import LoginFailure
from rocky.system.events import NewEvent


class AccountStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"


class TokenPurpose(StrEnum):
    ACTIVATION = "activation"
    PASSWORD_RESET = "password_reset"  # noqa: S105  (purpose name, not a password)


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    status: AccountStatus
    password_hash: str | None
    failed_login_count: int
    locked_until: datetime | None


@dataclass(frozen=True)
class SessionRecord:
    id: int
    account_id: int
    last_seen_at: datetime
    expires_at: datetime


class AuthStore(Protocol):
    """Storage of the authentication aggregate, bound to one open transaction.

    Implementations never begin nor commit: the caller owns the transaction.
    """

    def find_account(self, email: str) -> Account | None: ...

    def get_account(self, account_id: int) -> Account | None: ...

    def create_account(self, email: str, now: datetime) -> int: ...

    def activate_account(
        self, account_id: int, password_hash: str, now: datetime
    ) -> None: ...

    def set_password(self, account_id: int, password_hash: str) -> None: ...

    def record_login_failure(self, account_id: int, failure: LoginFailure) -> None: ...

    def clear_login_failures(self, account_id: int) -> None: ...

    def issue_token(
        self,
        account_id: int,
        purpose: TokenPurpose,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        """Store a new token and cancel the unused ones of the same purpose."""
        ...

    def consume_token(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int | None:
        """Mark a valid token as used, atomically; return its account, or None."""
        ...

    def peek_token(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int | None:
        """The account of a valid token, without using it."""
        ...

    def open_session(
        self, account_id: int, token_hash: str, now: datetime, expires_at: datetime
    ) -> None: ...

    def find_session(self, token_hash: str, now: datetime) -> SessionRecord | None:
        """A session neither revoked nor expired at ``now``."""
        ...

    def renew_session(
        self, session_id: int, now: datetime, expires_at: datetime
    ) -> None: ...

    def revoke_session(self, token_hash: str, now: datetime) -> None: ...

    def revoke_all_sessions(self, account_id: int, now: datetime) -> None: ...

    def append_event(self, event: NewEvent) -> None: ...
