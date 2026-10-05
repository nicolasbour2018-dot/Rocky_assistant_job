from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from rocky.system.auth.model import AccountStatus
from rocky.system.auth.rules import InvalidEmailError, InvalidPasswordError
from rocky.system.auth.usecases import (
    AlreadyActive,
    Auth,
    InvalidLink,
    Invited,
    LoginRefused,
    MailKind,
    PasswordChanged,
    SessionOpened,
)
from tests.system.auth.fakes import FakeClock, FakeHasher, InMemoryAuthStore

EMAIL = "nicolas@example.fr"
PASSWORD = "un mot de passe solide"


@pytest.fixture
def store() -> InMemoryAuthStore:
    return InMemoryAuthStore()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def auth(store: InMemoryAuthStore, clock: FakeClock) -> Auth:
    return Auth(
        store, hasher=FakeHasher(), clock=clock, public_url="https://rocky.example"
    )


def token_of(link: str) -> str:
    return parse_qs(urlsplit(link).query)["jeton"][0]


def invite(auth: Auth, email: str = EMAIL) -> str:
    result = auth.invite(email)
    assert isinstance(result, Invited)
    return token_of(result.mail.link)


def active_account(auth: Auth) -> SessionOpened:
    result = auth.activate(invite(auth), PASSWORD)
    assert isinstance(result, SessionOpened)
    return result


def test_invite_creates_a_pending_account_and_an_activation_link(
    auth: Auth, store: InMemoryAuthStore
) -> None:
    result = auth.invite("  Nicolas@Example.FR ")

    assert isinstance(result, Invited)
    assert result.mail.recipient == EMAIL
    assert result.mail.kind is MailKind.INVITATION
    assert result.mail.link.startswith("https://rocky.example/activation?jeton=")
    assert store.accounts[result.account_id].status is AccountStatus.PENDING
    assert store.event_types() == ["system.account_invited"]
    assert store.events[0].account_id == result.account_id


def test_invite_rejects_a_malformed_address(auth: Auth) -> None:
    with pytest.raises(InvalidEmailError):
        auth.invite("nicolas")


def test_a_new_invitation_replaces_the_previous_link(auth: Auth) -> None:
    first = invite(auth)
    second = invite(auth)

    assert isinstance(auth.activate(first, PASSWORD), InvalidLink)
    assert isinstance(auth.activate(second, PASSWORD), SessionOpened)


def test_an_active_account_cannot_be_invited_again(auth: Auth) -> None:
    opened = active_account(auth)

    assert auth.invite(EMAIL) == AlreadyActive(opened.account_id)


def test_activation_sets_the_password_and_opens_a_session(
    auth: Auth, store: InMemoryAuthStore
) -> None:
    opened = active_account(auth)

    account = store.accounts[opened.account_id]
    assert account.status is AccountStatus.ACTIVE
    assert account.password_hash == f"hashed:{PASSWORD}"
    resolved = auth.resolve_session(opened.session_token)
    assert resolved is not None
    assert resolved.account.id == opened.account_id
    assert store.event_types() == ["system.account_invited", "system.account_activated"]


def test_activation_link_works_once(auth: Auth) -> None:
    token = invite(auth)
    auth.activate(token, PASSWORD)

    assert isinstance(auth.activate(token, PASSWORD), InvalidLink)


def test_activation_link_expires_after_seven_days(auth: Auth, clock: FakeClock) -> None:
    token = invite(auth)
    clock.advance(timedelta(days=7))

    assert isinstance(auth.activate(token, PASSWORD), InvalidLink)


def test_a_short_password_keeps_the_link_usable(auth: Auth) -> None:
    token = invite(auth)

    with pytest.raises(InvalidPasswordError):
        auth.activate(token, "court")
    assert isinstance(auth.activate(token, PASSWORD), SessionOpened)


def test_login_opens_a_session_with_the_right_password(auth: Auth) -> None:
    opened = active_account(auth)

    result = auth.login(" NICOLAS@example.fr", PASSWORD)

    assert isinstance(result, SessionOpened)
    assert result.account_id == opened.account_id
    assert result.session_token != opened.session_token


@pytest.mark.parametrize(
    ("email", "password"),
    [
        (EMAIL, "pas le bon mot de passe"),
        ("inconnu@example.fr", PASSWORD),
        ("pas une adresse", PASSWORD),
    ],
)
def test_login_refusals_look_the_same(auth: Auth, email: str, password: str) -> None:
    active_account(auth)

    assert auth.login(email, password) == LoginRefused()


def test_a_pending_account_cannot_log_in(auth: Auth) -> None:
    invite(auth)

    assert auth.login(EMAIL, PASSWORD) == LoginRefused()


def test_fifth_failure_locks_the_account_for_fifteen_minutes(
    auth: Auth, store: InMemoryAuthStore, clock: FakeClock
) -> None:
    active_account(auth)
    for _ in range(5):
        auth.login(EMAIL, "pas le bon mot de passe")

    assert store.event_types()[-1] == "system.account_locked"
    assert auth.login(EMAIL, PASSWORD) == LoginRefused()
    clock.advance(timedelta(minutes=15))
    assert isinstance(auth.login(EMAIL, PASSWORD), SessionOpened)


def test_failures_start_over_after_an_expired_lock(
    auth: Auth, store: InMemoryAuthStore, clock: FakeClock
) -> None:
    opened = active_account(auth)
    for _ in range(5):
        auth.login(EMAIL, "pas le bon mot de passe")
    clock.advance(timedelta(minutes=15))

    auth.login(EMAIL, "pas le bon mot de passe")

    account = store.accounts[opened.account_id]
    assert (account.failed_login_count, account.locked_until) == (1, None)


def test_session_slides_and_expires_after_seven_idle_days(
    auth: Auth, clock: FakeClock
) -> None:
    opened = active_account(auth)

    clock.advance(timedelta(days=6))
    resolved = auth.resolve_session(opened.session_token)
    assert resolved is not None
    assert resolved.renewed is True

    clock.advance(timedelta(days=6))
    assert auth.resolve_session(opened.session_token) is not None

    clock.advance(timedelta(days=7))
    assert auth.resolve_session(opened.session_token) is None


def test_session_is_not_rewritten_within_the_hour(auth: Auth, clock: FakeClock) -> None:
    opened = active_account(auth)
    clock.advance(timedelta(minutes=30))

    resolved = auth.resolve_session(opened.session_token)

    assert resolved is not None
    assert resolved.renewed is False


def test_logout_invalidates_only_that_session(auth: Auth) -> None:
    first = active_account(auth)
    second = auth.login(EMAIL, PASSWORD)
    assert isinstance(second, SessionOpened)

    auth.logout(first.session_token)

    assert auth.resolve_session(first.session_token) is None
    assert auth.resolve_session(second.session_token) is not None


def test_unknown_session_token_resolves_to_nothing(auth: Auth) -> None:
    assert auth.resolve_session("forged") is None


def test_reset_changes_the_password_and_closes_every_session(
    auth: Auth, store: InMemoryAuthStore
) -> None:
    opened = active_account(auth)
    mail = auth.request_reset(EMAIL)
    assert mail is not None
    assert mail.kind is MailKind.PASSWORD_RESET

    new_password = "un autre mot de passe"
    result = auth.reset_password(token_of(mail.link), new_password)

    assert result == PasswordChanged(opened.account_id)
    assert auth.resolve_session(opened.session_token) is None
    assert auth.login(EMAIL, PASSWORD) == LoginRefused()
    assert isinstance(auth.login(EMAIL, new_password), SessionOpened)
    assert store.event_types()[-1] == "system.password_reset"


def test_reset_link_expires_after_one_hour(auth: Auth, clock: FakeClock) -> None:
    active_account(auth)
    mail = auth.request_reset(EMAIL)
    assert mail is not None
    clock.advance(timedelta(hours=1))

    assert isinstance(auth.reset_password(token_of(mail.link), PASSWORD), InvalidLink)


@pytest.mark.parametrize("email", ["inconnu@example.fr", "pas une adresse"])
def test_reset_is_silent_for_unknown_addresses(auth: Auth, email: str) -> None:
    active_account(auth)

    assert auth.request_reset(email) is None


def test_reset_is_silent_for_pending_accounts(auth: Auth) -> None:
    invite(auth)

    assert auth.request_reset(EMAIL) is None
