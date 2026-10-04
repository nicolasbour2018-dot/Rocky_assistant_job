"""Google OAuth for Gmail, read only (decision E1, Q2, Q3): authorisation code with PKCE, refresh, revocation.

Every call goes through ``google_json``: a bounded wait, no retry, a French reason on failure. No token, code or
secret ever appears in a reason, a log or an event.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2

from rocky.messages.model import AccessLostError, GmailError
from rocky.system.config import GmailSettings
from rocky.system.crypto import SealedValueError, TokenCipher

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105  (an address, not a token)
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
# The only scope Rocky ever asks (AGENTS §6: Gmail read only, no wider scope).
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALLBACK_PATH = "/messages/gmail/retour"
TIMEOUT_SECONDS = 30.0
# The state of an authorisation lives 15 minutes in a sealed cookie.
STATE_MAX_AGE = 15 * 60

ACCESS_LOST_REASON = "Google a retiré l'accès à cette boîte : reconnecte-la."


@dataclass(frozen=True)
class PendingAuthorization:
    """What the return from Google must match: the state sent, the PKCE verifier and the account that asked."""

    state: str
    verifier: str
    account_id: int


@dataclass(frozen=True)
class Grant:
    """A mailbox the user allowed Rocky to read: its address (read at Google) and its refresh token."""

    address: str
    refresh_token: str


def new_authorization(account_id: int) -> PendingAuthorization:
    return PendingAuthorization(
        state=secrets.token_urlsafe(32),
        verifier=secrets.token_urlsafe(64),
        account_id=account_id,
    )


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def redirect_uri(public_url: str) -> str:
    return f"{public_url}{CALLBACK_PATH}"


def authorization_url(
    settings: GmailSettings, *, redirect_to: str, pending: PendingAuthorization
) -> str:
    """Google's consent page. ``prompt=consent`` makes Google give a refresh token at every authorisation."""
    return f"{AUTH_URL}?" + urlencode(
        {
            "client_id": settings.client_id or "",
            "redirect_uri": redirect_to,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "select_account consent",
            "state": pending.state,
            "code_challenge": code_challenge(pending.verifier),
            "code_challenge_method": "S256",
        }
    )


def seal_pending(cipher: TokenCipher, pending: PendingAuthorization) -> str:
    value = json.dumps(
        {"s": pending.state, "v": pending.verifier, "a": pending.account_id}
    )
    return cipher.seal(value).decode("ascii")


def open_pending(cipher: TokenCipher, sealed: str) -> PendingAuthorization | None:
    """The pending authorisation of the cookie; None when it is altered, foreign or older than 15 minutes."""
    try:
        data = json.loads(
            cipher.open(sealed.encode("ascii"), max_age_seconds=STATE_MAX_AGE)
        )
    except (SealedValueError, UnicodeEncodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    state, verifier, account_id = data.get("s"), data.get("v"), data.get("a")
    if not (
        isinstance(state, str)
        and isinstance(verifier, str)
        and isinstance(account_id, int)
    ):
        return None
    return PendingAuthorization(state, verifier, account_id)


class GoogleOAuth:
    """The token endpoint and the revocation, on a client opened per call."""

    def __init__(
        self,
        settings: GmailSettings,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = timeout_seconds

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=self._transport, timeout=self._timeout)

    def exchange(self, code: str, *, verifier: str, redirect_to: str) -> Grant:
        """The mailbox behind an authorisation code; refused when Google did not grant the read scope."""
        with self.client() as client:
            data = google_json(
                client,
                "POST",
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_to,
                    "client_id": self._settings.client_id or "",
                    "client_secret": self._settings.client_secret or "",
                },
            )
            refresh_token, access_token = (
                data.get("refresh_token"),
                data.get("access_token"),
            )
            if SCOPE not in str(data.get("scope") or "").split():
                raise GmailError(
                    "Rocky a besoin de lire tes e-mails : coche cette autorisation chez Google."
                )
            if not isinstance(refresh_token, str) or not isinstance(access_token, str):
                raise GmailError("Google n'a pas donné d'accès durable à cette boîte.")
            profile = google_json(
                client,
                "GET",
                PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        address = profile.get("emailAddress")
        if not isinstance(address, str) or "@" not in address:
            raise GmailError("Google n'a pas donné l'adresse de la boîte.")
        return Grant(address=address.strip().lower(), refresh_token=refresh_token)

    def access_token(self, client: httpx2.Client, refresh_token: str) -> str:
        """A fresh access token; raises ``AccessLostError`` when Google refuses the refresh token."""
        data = google_json(
            client,
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._settings.client_id or "",
                "client_secret": self._settings.client_secret or "",
            },
        )
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise GmailError("Google n'a pas délivré de jeton d'accès.")
        return token

    def revoke(self, refresh_token: str) -> None:
        """Withdraw Rocky's access at Google. A token Google no longer knows is already withdrawn."""
        with self.client() as client:
            try:
                google_json(client, "POST", REVOKE_URL, data={"token": refresh_token})
            except AccessLostError:
                return


def google_json(
    client: httpx2.Client,
    method: str,
    url: str,
    *,
    params: Mapping[str, str | int] | None = None,
    data: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One call to Google; its JSON object, or a ``GmailError`` with a French reason."""
    try:
        response = client.request(
            method,
            url,
            params=dict(params) if params else None,
            data=dict(data) if data else None,
            headers=dict(headers) if headers else None,
        )
    except httpx2.TimeoutException as error:
        raise GmailError("Google ne répond pas (délai dépassé).") from error
    except httpx2.HTTPError as error:
        logger.warning("Google request failed: %s", type(error).__name__)
        raise GmailError("Google est injoignable (erreur réseau).") from error
    if response.status_code >= 400:
        raise _refusal(response)
    if not response.content:
        return {}
    try:
        answer = response.json()
    except ValueError as error:
        raise GmailError("Google a renvoyé une réponse illisible.") from error
    if not isinstance(answer, dict):
        raise GmailError("Google a renvoyé une réponse inattendue.")
    return answer


def _refusal(response: httpx2.Response) -> GmailError:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    # The token endpoint answers {"error": "invalid_grant"}; the Gmail API {"error": {"errors": [{"reason": …}]}}.
    if error in ("invalid_grant", "invalid_token"):
        return AccessLostError(ACCESS_LOST_REASON)
    if error == "invalid_client":
        return GmailError(
            "Google refuse le client OAuth de Rocky : vérifie ROCKY_GOOGLE_CLIENT_ID et son secret."
        )
    code = _api_reason(error)
    detail = f", {code}" if code else ""
    if status == 429:
        return GmailError("Quota Gmail atteint pour le moment (HTTP 429).")
    if status >= 500:
        return GmailError(f"Gmail est en panne (HTTP {status}).")
    if status == 404:
        return GmailError("Gmail ne trouve plus ce message (HTTP 404).")
    return GmailError(f"Google a refusé la demande (HTTP {status}{detail}).")


def _api_reason(error: object) -> str | None:
    """The short reason code of a Gmail API error (``accessNotConfigured``…), never its free text."""
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        reason = errors[0].get("reason")
        if isinstance(reason, str) and reason.isascii() and reason.isalnum():
            return reason
    return None
