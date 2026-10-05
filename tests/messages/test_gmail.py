"""Gmail and Google OAuth over HTTP (decision E1), on recorded answers: no network in the tests."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from cryptography.fernet import Fernet

from rocky.messages import gmail as gmail_module
from rocky.messages.gmail import GoogleGmail
from rocky.messages.model import AccessLostError, GmailError
from rocky.messages.oauth import (
    ACCESS_LOST_REASON,
    GoogleOAuth,
    PendingAuthorization,
    authorization_url,
    code_challenge,
    new_authorization,
    open_pending,
    redirect_uri,
    seal_pending,
)
from rocky.system.crypto import TokenCipher
from tests.messages.fakes import (
    API_URL,
    GMAIL,
    KEY,
    REPLY_ID,
    TOKEN_URL,
    Google,
    cipher,
    json_answer,
    recorded,
)

TOKEN, API = TOKEN_URL, API_URL


def form(request: httpx2.Request) -> dict[str, str]:
    return {
        key: values[0] for key, values in parse_qs(request.content.decode()).items()
    }


def refreshing(request: httpx2.Request) -> httpx2.Response:
    return json_answer(recorded("oauth_refresh.json"))


def test_a_reader_refreshes_the_access_then_lists_every_page() -> None:
    def messages(request: httpx2.Request) -> httpx2.Response:
        page = request.url.params.get("pageToken")
        return json_answer(
            recorded("list_page_2.json" if page == "page-2" else "list_page_1.json")
        )

    google = Google({("POST", TOKEN): refreshing, ("GET", f"{API}/messages"): messages})

    with GoogleGmail(google.oauth()).reader("1//rafraichissement") as reader:
        ids = reader.list_ids("-in:sent after:1")

    assert ids == ["18f0a1b2c3d4e5f6", "18f0b2c3d4e5f607", "18f0c3d4e5f60718"]
    refresh, first, second = google.requests
    assert form(refresh) == {
        "grant_type": "refresh_token",
        "refresh_token": "1//rafraichissement",
        "client_id": "client.apps",
        "client_secret": "secret-client",
    }
    assert first.headers["Authorization"] == "Bearer ya29.acces-de-test"
    assert first.url.params["q"] == "-in:sent after:1"
    assert first.url.params["maxResults"] == "500"
    assert "pageToken" not in first.url.params
    assert second.url.params["pageToken"] == "page-2"


def test_an_empty_search_gives_no_identifier() -> None:
    google = Google(
        {
            ("POST", TOKEN): refreshing,
            ("GET", f"{API}/messages"): lambda r: json_answer(
                recorded("list_empty.json")
            ),
        }
    )

    with GoogleGmail(google.oauth()).reader("1//r") as reader:
        assert reader.list_ids("q") == []


def test_a_search_of_too_many_pages_is_stopped_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gmail_module, "MAX_PAGES", 2)
    google = Google(
        {
            ("POST", TOKEN): refreshing,
            ("GET", f"{API}/messages"): lambda r: json_answer(
                recorded("list_page_1.json")
            ),
        }
    )

    with (
        GoogleGmail(google.oauth()).reader("1//r") as reader,
        pytest.raises(GmailError, match="trop longue"),
    ):
        reader.list_ids("q")


def test_a_message_is_read_whole() -> None:
    google = Google(
        {
            ("POST", TOKEN): refreshing,
            ("GET", f"{API}/messages/{REPLY_ID}"): lambda r: json_answer(
                recorded("message_reply.json")
            ),
        }
    )

    with GoogleGmail(google.oauth()).reader("1//r") as reader:
        message = reader.get(REPLY_ID)
        with pytest.raises(GmailError, match="inattendu"):
            reader.get("../profile")

    assert message["id"] == REPLY_ID
    assert google.requests[-1].url.params["format"] == "full"


def test_a_refused_refresh_token_means_the_access_is_lost() -> None:
    google = Google(
        {
            ("POST", TOKEN): lambda r: json_answer(
                recorded("oauth_invalid_grant.json"), 400
            )
        }
    )

    with (
        pytest.raises(AccessLostError) as refused,
        GoogleGmail(google.oauth()).reader("1//r"),
    ):
        pass

    assert refused.value.reason == ACCESS_LOST_REASON


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (httpx2.Response(503), "Gmail est en panne (HTTP 503)."),
        (httpx2.Response(429), "Quota Gmail atteint pour le moment (HTTP 429)."),
        (httpx2.Response(404), "Gmail ne trouve plus ce message (HTTP 404)."),
        (
            json_answer(
                {
                    "error": {
                        "code": 403,
                        "message": "Gmail API has not been used",
                        "errors": [{"reason": "accessNotConfigured"}],
                    }
                },
                403,
            ),
            "Google a refusé la demande (HTTP 403, accessNotConfigured).",
        ),
        (
            httpx2.Response(200, text="<html>"),
            "Google a renvoyé une réponse illisible.",
        ),
        (json_answer(["liste"]), "Google a renvoyé une réponse inattendue."),
    ],
    ids=["down", "quota", "gone", "forbidden", "unreadable", "unexpected"],
)
def test_each_failure_of_gmail_has_its_reason(
    answer: httpx2.Response, reason: str
) -> None:
    google = Google(
        {("POST", TOKEN): refreshing, ("GET", f"{API}/messages"): lambda r: answer}
    )

    with (
        GoogleGmail(google.oauth()).reader("1//r") as reader,
        pytest.raises(GmailError) as failure,
    ):
        reader.list_ids("q")

    assert failure.value.reason == reason


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx2.ConnectTimeout("lent"), "Google ne répond pas (délai dépassé)."),
        (httpx2.ConnectError("coupé"), "Google est injoignable (erreur réseau)."),
    ],
    ids=["timeout", "network"],
)
def test_google_out_of_reach_has_its_reason(error: Exception, reason: str) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise error

    oauth = GoogleOAuth(GMAIL, transport=httpx2.MockTransport(fail))

    with pytest.raises(GmailError) as failure, GoogleGmail(oauth).reader("1//r"):
        pass

    assert failure.value.reason == reason


def test_a_wrong_client_is_named_without_its_secret() -> None:
    google = Google(
        {("POST", TOKEN): lambda r: json_answer({"error": "invalid_client"}, 401)}
    )

    with (
        pytest.raises(GmailError) as failure,
        GoogleGmail(google.oauth()).reader("1//r"),
    ):
        pass

    assert "ROCKY_GOOGLE_CLIENT_ID" in failure.value.reason
    assert "secret-client" not in failure.value.reason


def test_the_consent_page_asks_read_only_access_with_pkce() -> None:
    pending = new_authorization(7)

    url = authorization_url(
        GMAIL, redirect_to=redirect_uri("http://127.0.0.1:8000"), pending=pending
    )

    parts = urlsplit(url)
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert params == {
        "client_id": "client.apps",
        "redirect_uri": "http://127.0.0.1:8000/messages/gmail/retour",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "select_account consent",
        "state": pending.state,
        "code_challenge": code_challenge(pending.verifier),
        "code_challenge_method": "S256",
    }
    assert pending.verifier not in url


def test_the_pkce_challenge_is_the_s256_of_the_verifier() -> None:
    # Example of RFC 7636, appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_a_pending_authorization_comes_back_only_sealed_by_rocky_and_fresh() -> None:
    pending = PendingAuthorization("etat", "verificateur", 7)

    assert open_pending(cipher(), seal_pending(cipher(), pending)) == pending
    assert open_pending(cipher(), "pas-scelle") is None
    assert open_pending(cipher(), "é") is None
    other = Fernet.generate_key().decode()
    assert open_pending(cipher(), seal_pending(TokenCipher(other), pending)) is None
    old = Fernet(KEY.encode()).encrypt_at_time(
        json.dumps({"s": "etat", "v": "v", "a": 7}).encode(), current_time=1_000
    )
    assert open_pending(cipher(), old.decode()) is None


def test_an_authorization_code_gives_the_mailbox_address_and_its_refresh_token() -> (
    None
):
    google = Google(
        {
            ("POST", TOKEN): lambda r: json_answer(recorded("oauth_exchange.json")),
            ("GET", f"{API}/profile"): lambda r: json_answer(recorded("profile.json")),
        }
    )

    grant = google.oauth().exchange(
        "4/code", verifier="verificateur", redirect_to="http://x/messages/gmail/retour"
    )

    assert grant.address == "camille.dupont@example.com"
    assert grant.refresh_token == "1//rafraichissement-de-test"
    exchange, profile = google.requests
    assert form(exchange) == {
        "grant_type": "authorization_code",
        "code": "4/code",
        "code_verifier": "verificateur",
        "redirect_uri": "http://x/messages/gmail/retour",
        "client_id": "client.apps",
        "client_secret": "secret-client",
    }
    assert profile.headers["Authorization"] == "Bearer ya29.acces-de-test"


def test_a_consent_without_the_read_scope_is_refused_with_its_reason() -> None:
    answer = {**recorded("oauth_exchange.json"), "scope": "openid email"}
    google = Google({("POST", TOKEN): lambda r: json_answer(answer)})

    with pytest.raises(GmailError, match="coche cette autorisation"):
        google.oauth().exchange("4/code", verifier="v", redirect_to="http://x")


def test_a_consent_without_a_refresh_token_is_refused() -> None:
    answer = {
        key: value
        for key, value in recorded("oauth_exchange.json").items()
        if key != "refresh_token"
    }
    google = Google({("POST", TOKEN): lambda r: json_answer(answer)})

    with pytest.raises(GmailError, match="accès durable"):
        google.oauth().exchange("4/code", verifier="v", redirect_to="http://x")


def test_a_revocation_tells_google_and_an_unknown_token_is_already_revoked() -> None:
    revoke = "https://oauth2.googleapis.com/revoke"
    google = Google({("POST", revoke): lambda r: httpx2.Response(200)})

    google.oauth().revoke("1//r")

    assert form(google.requests[0]) == {"token": "1//r"}
    gone = Google(
        {("POST", revoke): lambda r: json_answer({"error": "invalid_token"}, 400)}
    )
    gone.oauth().revoke("1//r")
