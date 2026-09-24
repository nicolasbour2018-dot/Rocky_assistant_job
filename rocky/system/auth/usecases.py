"""Authentication use cases, on the ``AuthStore`` port.

Each use case runs inside one transaction opened by the caller. Expected failures (wrong password, dead link)
are returned as results, so that what the use case wrote (a failure count) is committed too. E-mails are
returned, never sent here: the caller sends them after the commit.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import VerifyMismatchError

from rocky.system.auth.model import Account, AccountStatus, AuthStore, TokenPurpose
from rocky.system.auth.rules import (
    ACTIVATION_LIFETIME,
    RESET_LIFETIME,
    InvalidEmailError,
    after_failed_login,
    is_locked,
    needs_renewal,
    new_token,
    normalize_email,
    session_expiry,
    token_hash,
    validate_password,
)
from rocky.system.events import Actor, NewEvent

type Clock = Callable[[], datetime]

ACTIVATION_PATH = "/activation"
RESET_PATH = "/reinitialisation"
TOKEN_PARAMETER = "jeton"  # noqa: S105  (query parameter name)


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str | None, password: str) -> bool:
        """False on mismatch; with no hash, spends the same time and returns False."""
        ...


class Argon2Hasher:
    """argon2id; checking an absent account costs as much as a real one."""

    def __init__(self) -> None:
        self._argon2 = _Argon2()
        self._dummy_hash = self._argon2.hash(secrets.token_hex(16))

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        try:
            self._argon2.verify(password_hash or self._dummy_hash, password)
        except VerifyMismatchError:
            return False
        return password_hash is not None


class MailKind(StrEnum):
    INVITATION = "invitation"
    PASSWORD_RESET = "password_reset"  # noqa: S105  (mail kind, not a password)


@dataclass(frozen=True)
class OutgoingMail:
    recipient: str
    kind: MailKind
    link: str


@dataclass(frozen=True)
class Invited:
    account_id: int
    mail: OutgoingMail


@dataclass(frozen=True)
class AlreadyActive:
    account_id: int


@dataclass(frozen=True)
class SessionOpened:
    account_id: int
    session_token: str


@dataclass(frozen=True)
class LoginRefused:
    """Same answer for an unknown address, a wrong password and a locked account."""


@dataclass(frozen=True)
class InvalidLink:
    """Unknown, used, cancelled or expired link."""


@dataclass(frozen=True)
class PasswordChanged:
    account_id: int


@dataclass(frozen=True)
class ResolvedSession:
    account: Account
    renewed: bool


class Auth:
    def __init__(
        self,
        store: AuthStore,
        *,
        hasher: PasswordHasher,
        clock: Clock,
        public_url: str,
    ) -> None:
        self._store = store
        self._hasher = hasher
        self._clock = clock
        self._public_url = public_url

    def invite(self, email: str) -> Invited | AlreadyActive:
        """Create a pending account, or send a new link to a pending one."""
        address = normalize_email(email)
        now = self._clock()
        account = self._store.find_account(address)
        if account is not None and account.status is AccountStatus.ACTIVE:
            return AlreadyActive(account.id)
        account_id = account.id if account else self._store.create_account(address, now)
        token = new_token()
        self._store.issue_token(
            account_id,
            TokenPurpose.ACTIVATION,
            token_hash(token),
            now,
            now + ACTIVATION_LIFETIME,
        )
        self._event("system.account_invited", Actor.USER, account_id)
        mail = OutgoingMail(
            address, MailKind.INVITATION, self._link(ACTIVATION_PATH, token)
        )
        return Invited(account_id, mail)

    def activate(self, token: str, password: str) -> SessionOpened | InvalidLink:
        """Consume the invitation, set the first password and open a session."""
        validate_password(password)
        now = self._clock()
        account_id = self._store.consume_token(
            token_hash(token), TokenPurpose.ACTIVATION, now
        )
        account = None if account_id is None else self._store.get_account(account_id)
        if account is None or account.status is not AccountStatus.PENDING:
            return InvalidLink()
        self._store.activate_account(account.id, self._hasher.hash(password), now)
        self._event("system.account_activated", Actor.USER, account.id)
        return self._open_session(account.id, now)

    def link_email(self, token: str, purpose: TokenPurpose) -> str | None:
        """E-mail of the account behind a valid link, without using the link."""
        account_id = self._store.peek_token(token_hash(token), purpose, self._clock())
        account = None if account_id is None else self._store.get_account(account_id)
        return None if account is None else account.email

    def login(self, email: str, password: str) -> SessionOpened | LoginRefused:
        now = self._clock()
        try:
            account = self._store.find_account(normalize_email(email))
        except InvalidEmailError:
            account = None
        usable = account is not None and account.status is AccountStatus.ACTIVE
        password_hash = account.password_hash if account and usable else None
        matches = self._hasher.verify(password_hash, password)
        if account is None or not usable:
            return LoginRefused()
        if is_locked(account.locked_until, now):
            return LoginRefused()
        if not matches:
            self._record_failure(account, now)
            return LoginRefused()
        self._store.clear_login_failures(account.id)
        return self._open_session(account.id, now)

    def resolve_session(self, session_token: str) -> ResolvedSession | None:
        """The account behind a valid session; slides its expiry when due."""
        now = self._clock()
        session = self._store.find_session(token_hash(session_token), now)
        if session is None:
            return None
        account = self._store.get_account(session.account_id)
        if account is None or account.status is not AccountStatus.ACTIVE:
            return None
        renewed = needs_renewal(session.last_seen_at, now)
        if renewed:
            self._store.renew_session(session.id, now, session_expiry(now))
        return ResolvedSession(account, renewed)

    def logout(self, session_token: str) -> None:
        self._store.revoke_session(token_hash(session_token), self._clock())

    def request_reset(self, email: str) -> OutgoingMail | None:
        """A link for an active account; None otherwise (the caller answers the same)."""
        try:
            address = normalize_email(email)
        except InvalidEmailError:
            return None
        account = self._store.find_account(address)
        if account is None or account.status is not AccountStatus.ACTIVE:
            return None
        now = self._clock()
        token = new_token()
        self._store.issue_token(
            account.id,
            TokenPurpose.PASSWORD_RESET,
            token_hash(token),
            now,
            now + RESET_LIFETIME,
        )
        return OutgoingMail(
            address, MailKind.PASSWORD_RESET, self._link(RESET_PATH, token)
        )

    def reset_password(
        self, token: str, password: str
    ) -> PasswordChanged | InvalidLink:
        """Set a new password and close every session of the account."""
        validate_password(password)
        now = self._clock()
        account_id = self._store.consume_token(
            token_hash(token), TokenPurpose.PASSWORD_RESET, now
        )
        account = None if account_id is None else self._store.get_account(account_id)
        if account is None or account.status is not AccountStatus.ACTIVE:
            return InvalidLink()
        self._store.set_password(account.id, self._hasher.hash(password))
        self._store.revoke_all_sessions(account.id, now)
        self._event("system.password_reset", Actor.USER, account.id)
        return PasswordChanged(account.id)

    def _record_failure(self, account: Account, now: datetime) -> None:
        # Failures counted before an expired lock start over.
        lock_expired = account.locked_until is not None and not is_locked(
            account.locked_until, now
        )
        previous = 0 if lock_expired else account.failed_login_count
        failure = after_failed_login(previous, now)
        self._store.record_login_failure(account.id, failure)
        if failure.locked_until is not None:
            self._event("system.account_locked", Actor.RULE, account.id)

    def _open_session(self, account_id: int, now: datetime) -> SessionOpened:
        token = new_token()
        self._store.open_session(
            account_id, token_hash(token), now, session_expiry(now)
        )
        return SessionOpened(account_id, token)

    def _event(self, event_type: str, actor: Actor, account_id: int) -> None:
        self._store.append_event(
            NewEvent(
                type=event_type,
                actor=actor,
                subject_type="account",
                subject_id=str(account_id),
                account_id=account_id,
            )
        )

    def _link(self, path: str, token: str) -> str:
        return f"{self._public_url}{path}?{TOKEN_PARAMETER}={token}"
