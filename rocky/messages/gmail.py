"""Gmail read only, over its REST API (decision E1): list the identifiers of a search, read one whole message.

One HTTP client and one access token per collection; ``oauth.google_json`` turns every failure into a French reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx2

from rocky.messages.model import GmailError, MailReader
from rocky.messages.oauth import GoogleOAuth, google_json

API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
PAGE_SIZE = 500
# A search of more pages than this is cut, and the collection says so (20 000 messages: never seen in a window).
MAX_PAGES = 40


class GmailReader:
    """``MailReader`` on an open client and a valid access token."""

    def __init__(self, client: httpx2.Client, access_token: str) -> None:
        self._client = client
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def list_ids(self, query: str) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {"q": query, "maxResults": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            data = google_json(
                self._client,
                "GET",
                f"{API_URL}/messages",
                params=params,
                headers=self._headers,
            )
            for item in data.get("messages") or ():
                identifier = item.get("id") if isinstance(item, dict) else None
                if isinstance(identifier, str) and identifier:
                    ids.append(identifier)
            next_token = data.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                return ids
            page_token = next_token
        raise GmailError(
            f"Recherche Gmail trop longue (plus de {MAX_PAGES * PAGE_SIZE} messages)."
        )

    def get(self, gmail_id: str) -> dict[str, object]:
        if not (gmail_id.isascii() and gmail_id.isalnum()):
            raise GmailError("Identifiant de message Gmail inattendu.")
        return google_json(
            self._client,
            "GET",
            f"{API_URL}/messages/{gmail_id}",
            params={"format": "full"},
            headers=self._headers,
        )


class GoogleGmail:
    """``Gmail``: a reader per collection, on a refresh token."""

    def __init__(self, oauth: GoogleOAuth) -> None:
        self._oauth = oauth

    @contextmanager
    def reader(self, refresh_token: str) -> Iterator[MailReader]:
        with self._oauth.client() as client:
            yield GmailReader(client, self._oauth.access_token(client, refresh_token))
