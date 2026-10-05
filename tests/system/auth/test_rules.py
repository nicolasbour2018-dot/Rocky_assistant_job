from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rocky.system.auth.rules import (
    InvalidEmailError,
    InvalidPasswordError,
    after_failed_login,
    is_locked,
    needs_renewal,
    new_token,
    normalize_email,
    safe_next_path,
    session_expiry,
    token_hash,
    validate_password,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_normalize_email_trims_and_lowers() -> None:
    assert normalize_email("  Nicolas@Example.FR ") == "nicolas@example.fr"


@pytest.mark.parametrize("value", ["", "nicolas", "nicolas@example", "a b@c.fr"])
def test_normalize_email_rejects_non_addresses(value: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalize_email(value)


def test_password_needs_twelve_characters() -> None:
    validate_password("a" * 12)
    with pytest.raises(InvalidPasswordError, match="12"):
        validate_password("a" * 11)


def test_tokens_are_random_and_only_their_hash_is_kept() -> None:
    first, second = new_token(), new_token()

    assert first != second
    assert len(first) >= 43
    assert token_hash(first) == token_hash(first)
    assert token_hash(first) != first
    assert len(token_hash(first)) == 64


def test_session_expires_seven_days_after_last_use() -> None:
    assert session_expiry(NOW) == NOW + timedelta(days=7)


def test_session_is_renewed_at_most_once_an_hour() -> None:
    assert not needs_renewal(NOW - timedelta(minutes=59), NOW)
    assert needs_renewal(NOW - timedelta(hours=1), NOW)


def test_fifth_failure_locks_for_fifteen_minutes() -> None:
    fourth = after_failed_login(3, NOW)
    fifth = after_failed_login(4, NOW)

    assert (fourth.failures, fourth.locked_until) == (4, None)
    assert (fifth.failures, fifth.locked_until) == (5, NOW + timedelta(minutes=15))
    assert is_locked(fifth.locked_until, NOW + timedelta(minutes=14))
    assert not is_locked(fifth.locked_until, NOW + timedelta(minutes=15))
    assert not is_locked(None, NOW)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/candidatures?etape=envoyee", "/candidatures?etape=envoyee"),
        (None, "/"),
        ("", "/"),
        ("candidatures", "/"),
        ("//evil.example/x", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
        ("/ok\nSet-Cookie: x", "/"),
    ],
)
def test_safe_next_path_only_accepts_local_paths(
    value: str | None, expected: str
) -> None:
    assert safe_next_path(value) == expected
