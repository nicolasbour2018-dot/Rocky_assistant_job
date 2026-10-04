"""Secrets kept by Rocky, encrypted with the key ``ROCKY_SECRET_KEY`` (Fernet: authenticated encryption).

Decision ``docs/decisions/E1-collecte.md`` (Q3): a Google refresh token is stored encrypted, never in clear; the same
cipher seals the short-lived state of an OAuth authorisation (a cookie, checked with a maximum age).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SealedValueError(Exception):
    """A sealed value was altered, sealed with another key, or is too old."""


class TokenCipher:
    def __init__(self, key: str) -> None:
        """Raises ``ValueError`` when ``key`` is not a Fernet key."""
        self._fernet = Fernet(key.encode("ascii"))

    def seal(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def open(self, sealed: bytes, *, max_age_seconds: int | None = None) -> str:
        try:
            return self._fernet.decrypt(sealed, ttl=max_age_seconds).decode("utf-8")
        except InvalidToken as error:
            raise SealedValueError("sealed value refused") from error


def is_valid_key(key: str) -> bool:
    try:
        TokenCipher(key)
    except ValueError:
        return False
    return True
