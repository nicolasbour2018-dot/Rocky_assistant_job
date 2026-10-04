"""Secrets sealed with ``ROCKY_SECRET_KEY`` (decision E1, Q3)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from rocky.system.crypto import SealedValueError, TokenCipher, is_valid_key


def test_a_sealed_value_opens_with_its_key_and_is_not_in_clear() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())

    sealed = cipher.seal("1//refresh-token")

    assert b"refresh-token" not in sealed
    assert cipher.open(sealed) == "1//refresh-token"


def test_another_key_or_an_altered_value_is_refused() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    sealed = cipher.seal("valeur")

    with pytest.raises(SealedValueError):
        TokenCipher(Fernet.generate_key().decode()).open(sealed)
    with pytest.raises(SealedValueError):
        cipher.open(sealed[:-4] + b"AAAA")


def test_a_sealed_value_older_than_its_maximum_age_is_refused() -> None:
    key = Fernet.generate_key()
    cipher = TokenCipher(key.decode())
    old = Fernet(key).encrypt_at_time(b"etat", current_time=1_000)

    with pytest.raises(SealedValueError):
        cipher.open(old, max_age_seconds=900)
    assert cipher.open(old) == "etat"


def test_only_a_fernet_key_is_valid() -> None:
    assert is_valid_key(Fernet.generate_key().decode())
    assert not is_valid_key("trop-courte")
    assert not is_valid_key("")
