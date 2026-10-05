"""Authentication rules: no I/O and no clock, the current time is always passed in.

Error messages here are shown to the user, hence in French.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LENGTH = 12

SESSION_IDLE_LIFETIME = timedelta(days=7)
SESSION_RENEWAL_INTERVAL = timedelta(hours=1)
ACTIVATION_LIFETIME = timedelta(days=7)
RESET_LIFETIME = timedelta(hours=1)

MAX_LOGIN_FAILURES = 5
LOCK_DURATION = timedelta(minutes=15)


class InvalidEmailError(ValueError):
    """The address cannot be an e-mail address."""


class InvalidPasswordError(ValueError):
    """The password does not follow the password policy."""


@dataclass(frozen=True)
class LoginFailure:
    failures: int
    locked_until: datetime | None


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise InvalidEmailError("Saisis une adresse e-mail valide.")
    return email


def validate_password(value: str) -> None:
    """A length rule only, no arbitrary composition rule."""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise InvalidPasswordError(
            f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères."
        )


def new_token() -> str:
    """Opaque random token, given to the user (link or cookie), never stored as is."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """The only form of a token that is stored."""
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry(now: datetime) -> datetime:
    """Sliding expiry: a session lives 7 days after its last use."""
    return now + SESSION_IDLE_LIFETIME


def needs_renewal(last_seen: datetime, now: datetime) -> bool:
    """At most one write per hour and per session."""
    return now - last_seen >= SESSION_RENEWAL_INTERVAL


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and locked_until > now


def after_failed_login(previous_failures: int, now: datetime) -> LoginFailure:
    """The fifth consecutive failure locks the account for 15 minutes."""
    failures = previous_failures + 1
    locked_until = now + LOCK_DURATION if failures >= MAX_LOGIN_FAILURES else None
    return LoginFailure(failures=failures, locked_until=locked_until)


def safe_next_path(value: str | None) -> str:
    """Local path to go back to after login; anything else falls back to the home page."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if "\\" in value or any(ord(char) < 32 for char in value):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value
