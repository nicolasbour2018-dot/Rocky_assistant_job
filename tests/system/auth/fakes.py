"""In-memory adapters for the authentication use cases (no SQL, no argon2, no clock)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from rocky.system.auth.mail import MailDeliveryError
from rocky.system.auth.model import Account, AccountStatus, SessionRecord, TokenPurpose
from rocky.system.auth.rules import LoginFailure
from rocky.system.auth.usecases import OutgoingMail
from rocky.system.events import NewEvent


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password_hash: str | None, password: str) -> bool:
        return password_hash == f"hashed:{password}"


@dataclass
class _Token:
    account_id: int
    purpose: TokenPurpose
    expires_at: datetime
    used_at: datetime | None = None


@dataclass
class _Session:
    id: int
    account_id: int
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class InMemoryAuthStore:
    def __init__(self) -> None:
        self.accounts: dict[int, Account] = {}
        self.tokens: dict[str, _Token] = {}
        self.sessions: dict[str, _Session] = {}
        self.events: list[NewEvent] = []

    def find_account(self, email: str) -> Account | None:
        return next((a for a in self.accounts.values() if a.email == email), None)

    def get_account(self, account_id: int) -> Account | None:
        return self.accounts.get(account_id)

    def create_account(self, email: str, now: datetime) -> int:
        account_id = len(self.accounts) + 1
        self.accounts[account_id] = Account(
            account_id, email, AccountStatus.PENDING, None, 0, None
        )
        return account_id

    def activate_account(
        self, account_id: int, password_hash: str, now: datetime
    ) -> None:
        self._update(
            account_id,
            status=AccountStatus.ACTIVE,
            password_hash=password_hash,
            failed_login_count=0,
            locked_until=None,
        )

    def set_password(self, account_id: int, password_hash: str) -> None:
        self._update(
            account_id,
            password_hash=password_hash,
            failed_login_count=0,
            locked_until=None,
        )

    def record_login_failure(self, account_id: int, failure: LoginFailure) -> None:
        self._update(
            account_id,
            failed_login_count=failure.failures,
            locked_until=failure.locked_until,
        )

    def clear_login_failures(self, account_id: int) -> None:
        self._update(account_id, failed_login_count=0, locked_until=None)

    def issue_token(
        self,
        account_id: int,
        purpose: TokenPurpose,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        for token in self.tokens.values():
            if (token.account_id, token.purpose, token.used_at) == (
                account_id,
                purpose,
                None,
            ):
                token.used_at = now
        self.tokens[token_hash] = _Token(account_id, purpose, expires_at)

    def consume_token(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int | None:
        token = self.tokens.get(token_hash)
        if token is None or token.purpose is not purpose:
            return None
        if token.used_at is not None or token.expires_at <= now:
            return None
        token.used_at = now
        return token.account_id

    def peek_token(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int | None:
        token = self.tokens.get(token_hash)
        if token is None or token.purpose is not purpose:
            return None
        if token.used_at is not None or token.expires_at <= now:
            return None
        return token.account_id

    def open_session(
        self, account_id: int, token_hash: str, now: datetime, expires_at: datetime
    ) -> None:
        self.sessions[token_hash] = _Session(
            len(self.sessions) + 1, account_id, now, expires_at
        )

    def find_session(self, token_hash: str, now: datetime) -> SessionRecord | None:
        session = self.sessions.get(token_hash)
        if session is None or session.revoked_at is not None:
            return None
        if session.expires_at <= now:
            return None
        return SessionRecord(
            session.id, session.account_id, session.last_seen_at, session.expires_at
        )

    def renew_session(
        self, session_id: int, now: datetime, expires_at: datetime
    ) -> None:
        for session in self.sessions.values():
            if session.id == session_id:
                session.last_seen_at, session.expires_at = now, expires_at

    def revoke_session(self, token_hash: str, now: datetime) -> None:
        session = self.sessions.get(token_hash)
        if session is not None and session.revoked_at is None:
            session.revoked_at = now

    def revoke_all_sessions(self, account_id: int, now: datetime) -> None:
        for session in self.sessions.values():
            if session.account_id == account_id and session.revoked_at is None:
                session.revoked_at = now

    def append_event(self, event: NewEvent) -> None:
        self.events.append(event)

    def event_types(self) -> list[str]:
        return [event.type for event in self.events]

    def _update(self, account_id: int, **changes: object) -> None:
        self.accounts[account_id] = replace(self.accounts[account_id], **changes)  # type: ignore[arg-type]


class RecordingMailer:
    """Keeps the e-mails instead of sending them; ``fail`` simulates an SMTP outage."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []
        self.fail = False

    def send(self, mail: OutgoingMail) -> None:
        if self.fail:
            raise MailDeliveryError("simulated SMTP outage")
        self.sent.append(mail)
