"""Rules of the mail collection, without effects: queries, window, reading a Gmail message, final status.

Decision ``docs/decisions/E1-collecte.md`` (Q4–Q7).
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import parseaddr
from typing import Any

from bs4 import BeautifulSoup

from rocky.messages.model import (
    Attachment,
    CollectedMessage,
    MessageUnreadableError,
    Query,
    SyncCounts,
    SyncStatus,
)

# Changes whenever a query changes: kept with every message and every collection (D14).
QUERIES_VERSION = "mail-2026-10-06.1"
# Q4: the platforms whose job alerts step E3 turns into offers, read whatever their Gmail category.
ALERT_DOMAINS = (
    "indeed.com",
    "apec.fr",
    "linkedin.com",
    "welcometothejungle.com",
    "hellowork.com",
    "cadremploi.fr",
    # H3, Q2: its alerts have a reader; filed in Promotions, the replies query leaves them out.
    "efinancialcareers.fr",
)
# Only the messages received: never the user's own sendings, drafts or chats (spam and trash are left out by Gmail).
RECEIVED_ONLY = "-in:sent -in:drafts -in:chats"
QUERIES = {
    Query.REPLIES: f"-category:promotions -category:social -category:forums {RECEIVED_ONLY}",
    Query.ALERTS: f"from:({' OR '.join(ALERT_DOMAINS)}) {RECEIVED_ONLY}",
}

# Q6: a new mailbox is read over 30 days; then from the last completed collection, with a day of margin.
FIRST_WINDOW = timedelta(days=30)
WINDOW_MARGIN = timedelta(days=1)
# Q5: each body is kept up to this many characters.
BODY_LIMIT = 500_000

INTERRUPTED_REASON = "Relevé interrompu (Rocky s'est arrêté pendant le relevé)."
TECHNICAL_REASON = "Erreur technique pendant le relevé (détail dans les journaux)."

_BLOCKS = ["p", "div", "li", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"]
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def window_start(last_completed_start: datetime | None, now: datetime) -> datetime:
    """Where a collection starts reading: never further back than the first window (Q6)."""
    oldest = now - FIRST_WINDOW
    if last_completed_start is None:
        return oldest
    return max(oldest, last_completed_start - WINDOW_MARGIN)


def gmail_query(query: Query, after: datetime) -> str:
    """The Gmail search of ``query`` for the messages received after ``after`` (to the second)."""
    return f"{QUERIES[query]} after:{int(after.timestamp())}"


def sync_status(
    counts: SyncCounts, *, listing_failure: str | None, write_failure: str | None
) -> tuple[SyncStatus, str | None]:
    """The final status of a collection and its reason (Q7)."""
    if listing_failure is not None:
        status = SyncStatus.PARTIAL if counts.new else SyncStatus.FAILED
        return status, listing_failure
    if counts.not_written:
        plural = "s" if counts.not_written > 1 else ""
        reason = f"{counts.not_written} message{plural} non écrit{plural}, repris au prochain relevé"
        return (
            SyncStatus.PARTIAL,
            f"{reason} : {write_failure}" if write_failure else reason,
        )
    return SyncStatus.COMPLETED, None


@dataclass
class _Bodies:
    text: list[str] = field(default_factory=list)
    html: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


def parse_message(raw: Mapping[str, Any]) -> CollectedMessage:
    """A Gmail message (``format=full``) as Rocky keeps it; raises ``MessageUnreadableError``."""
    gmail_id, thread_id = raw.get("id"), raw.get("threadId")
    payload = raw.get("payload")
    if not isinstance(gmail_id, str) or not gmail_id:
        raise MessageUnreadableError("message sans identifiant")
    if not isinstance(thread_id, str) or not isinstance(payload, Mapping):
        raise MessageUnreadableError(f"message {gmail_id} incomplet")
    received_at = _received_at(raw.get("internalDate"), gmail_id)
    headers = _headers(payload)
    bodies = _Bodies()
    for part in _parts(payload):
        _read_part(part, bodies)
    body_html = "\n".join(bodies.html)
    body_text = "\n".join(bodies.text) or _text_of(body_html)
    truncated = len(body_text) > BODY_LIMIT or len(body_html) > BODY_LIMIT
    sender = headers.get("from", "")
    address = parseaddr(sender)[1].strip().lower()
    labels = raw.get("labelIds")
    return CollectedMessage(
        gmail_id=gmail_id,
        thread_id=thread_id,
        received_at=received_at,
        sender=sender,
        sender_address=address if "@" in address else None,
        recipients=", ".join(v for v in (headers.get("to"), headers.get("cc")) if v),
        subject=headers.get("subject", ""),
        snippet=_clean(html.unescape(str(raw.get("snippet") or ""))),
        body_text=body_text[:BODY_LIMIT],
        body_html=body_html[:BODY_LIMIT],
        truncated=truncated,
        labels=tuple(str(label) for label in labels)
        if isinstance(labels, list)
        else (),
        attachments=tuple(bodies.attachments),
        rfc822_id=headers.get("message-id"),
    )


def _received_at(value: object, gmail_id: str) -> datetime:
    try:
        milliseconds = int(str(value))
    except ValueError as error:
        raise MessageUnreadableError(f"message {gmail_id} sans date") from error
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _headers(part: Mapping[str, Any]) -> dict[str, str]:
    """Header names in lower case; the first value of a repeated header."""
    found: dict[str, str] = {}
    for header in part.get("headers") or ():
        if isinstance(header, Mapping):
            name, value = header.get("name"), header.get("value")
            if isinstance(name, str) and isinstance(value, str):
                found.setdefault(name.lower(), _clean(value))
    return found


def _parts(part: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield part
    for child in part.get("parts") or ():
        if isinstance(child, Mapping):
            yield from _parts(child)


def _read_part(part: Mapping[str, Any], bodies: _Bodies) -> None:
    mime_type = str(part.get("mimeType") or "").lower()
    found = part.get("body")
    body: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    filename = str(part.get("filename") or "")
    if filename:
        size = body.get("size")
        bodies.attachments.append(
            Attachment(filename, mime_type, size if isinstance(size, int) else 0)
        )
        return
    if mime_type not in ("text/plain", "text/html") or not body.get("data"):
        return
    content = _decode(str(body["data"]), _charset(part))
    (bodies.text if mime_type == "text/plain" else bodies.html).append(content)


def _charset(part: Mapping[str, Any]) -> str:
    content_type = _headers(part).get("content-type")
    if not content_type:
        return "utf-8"
    message = Message()
    message["content-type"] = content_type
    return message.get_content_charset() or "utf-8"


def _decode(data: str, charset: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError) as error:
        raise MessageUnreadableError("corps du message illisible") from error
    try:
        text = raw.decode(charset, errors="replace")
    except LookupError:  # A charset Python does not know.
        text = raw.decode("utf-8", errors="replace")
    return _clean(text)


def _clean(text: str) -> str:
    """PostgreSQL refuses the NUL character in a text."""
    return text.replace("\x00", "")


def _text_of(body_html: str) -> str:
    """The text of an HTML body: a line per block, the inline elements kept on their line."""
    if not body_html:
        return ""
    soup = BeautifulSoup(body_html, "html.parser")
    for hidden in soup(["script", "style", "head"]):
        hidden.decompose()
    for line_break in soup("br"):
        line_break.replace_with("\n")
    for block in soup(_BLOCKS):
        block.append("\n")
    text = _SPACES.sub(" ", soup.get_text())
    lines = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", lines).strip()
