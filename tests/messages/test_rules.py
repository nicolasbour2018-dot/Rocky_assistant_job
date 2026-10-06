"""Rules of the mail collection (decision E1, Q4–Q7): queries, window, reading a message, final status."""

from __future__ import annotations

import base64
import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from rocky.messages.alerts.rules import READERS
from rocky.messages.model import (
    Attachment,
    MessageUnreadableError,
    Query,
    SyncCounts,
    SyncStatus,
)
from rocky.messages.rules import (
    ALERT_DOMAINS,
    BODY_LIMIT,
    QUERIES,
    gmail_query,
    parse_message,
    sync_status,
    window_start,
)
from tests.messages.fakes import raw_message

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def test_the_replies_leave_out_promotions_social_and_forums_but_alerts_keep_them() -> (
    None
):
    replies, alerts = QUERIES[Query.REPLIES], QUERIES[Query.ALERTS]

    for category in ("promotions", "social", "forums"):
        assert f"-category:{category}" in replies
        assert "category" not in alerts
    assert "from:(indeed.com OR apec.fr OR linkedin.com" in alerts
    for query in (replies, alerts):
        assert "-in:sent -in:drafts -in:chats" in query


def test_every_alert_with_a_reader_is_found_by_the_alerts_query() -> None:
    # H3, Q2: an alert filed in Promotions is only found by the alerts query (eFinancialCareers was missing).
    for address in READERS:
        host = address.rpartition("@")[2]
        assert any(
            host == domain or host.endswith(f".{domain}") for domain in ALERT_DOMAINS
        ), address


def test_a_query_reads_from_the_start_of_the_window_to_the_second() -> None:
    after = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

    assert gmail_query(Query.ALERTS, after).endswith(f" after:{int(after.timestamp())}")


def test_a_new_mailbox_is_read_over_30_days_then_from_the_last_completed_collection() -> (
    None
):
    assert window_start(None, NOW) == NOW - timedelta(days=30)
    last = NOW - timedelta(hours=1)
    assert window_start(last, NOW) == last - timedelta(days=1)
    # Never further back than the first window, however old the last completed collection.
    assert window_start(NOW - timedelta(days=90), NOW) == NOW - timedelta(days=30)


def test_a_recruiter_reply_is_read_with_its_headers_and_both_bodies() -> None:
    message = parse_message(raw_message("message_reply.json"))

    assert message.gmail_id == "18f0a1b2c3d4e5f6"
    assert message.thread_id == "18f0a1b2c3d4e5f6"
    assert message.received_at == datetime.fromtimestamp(1_759_400_000, tz=UTC)
    assert message.sender == "Jeanne Martin <recrutement@exemple-conseil.fr>"
    assert message.sender_address == "recrutement@exemple-conseil.fr"
    assert message.recipients == "Camille Dupont <camille.dupont@example.com>"
    assert message.subject == "Votre candidature : Data Analyst"
    assert message.body_text.startswith(
        "Bonjour Camille,\n\nMerci pour votre candidature"
    )
    assert "<b>Data Analyst</b>" in message.body_html
    assert message.labels == ("INBOX", "CATEGORY_PERSONAL", "UNREAD")
    assert message.attachments == ()
    assert message.rfc822_id == "<CAexemple-reponse-1@mail.exemple-conseil.fr>"
    assert message.truncated is False


def test_an_html_only_alert_gets_a_text_without_scripts_nor_styles() -> None:
    message = parse_message(raw_message("message_alert_html_only.json"))

    assert "Data Analyst H/F – Exemple SAS – Paris (75)" in message.body_text
    assert "track()" not in message.body_text
    assert "color:red" not in message.body_text
    assert 'href="https://fr.indeed.com/rc/clk?jk=0a1b2c3d4e5f6789' in message.body_html
    assert message.snippet.startswith("3 nouvelles offres pour « Data analyst »")


def test_a_latin1_text_is_decoded_and_an_attachment_keeps_only_its_name() -> None:
    message = parse_message(raw_message("message_latin1_attachment.json"))

    assert "fiche de poste détaillée.\nÀ bientôt." in message.body_text
    assert message.attachments == (
        Attachment("fiche-de-poste.pdf", "application/pdf", 104857),
    )
    assert message.recipients == (
        "camille.dupont@example.com, manager@societe-fictive.fr"
    )
    assert message.snippet.endswith("d'Exemple.")
    assert message.rfc822_id is None


def test_a_body_beyond_the_limit_is_cut_and_marked() -> None:
    raw = raw_message("message_alert_html_only.json")
    big = "<p>" + "x" * (BODY_LIMIT + 10) + "</p>"
    raw["payload"]["body"]["data"] = base64.urlsafe_b64encode(big.encode()).decode()

    message = parse_message(raw)

    assert message.truncated is True
    assert len(message.body_html) == BODY_LIMIT
    assert len(message.body_text) <= BODY_LIMIT


def test_a_nul_character_never_reaches_the_database() -> None:
    raw = raw_message("message_reply.json")
    raw["payload"]["headers"][2]["value"] = "Objet\x00 coupé"

    assert parse_message(raw).subject == "Objet coupé"


def test_an_unknown_charset_falls_back_to_utf8() -> None:
    raw = raw_message("message_latin1_attachment.json")
    raw["payload"]["parts"][0]["headers"][0]["value"] = "text/plain; charset=x-inconnu"

    assert "Madame, Monsieur" in parse_message(raw).body_text


def _without(key: str) -> dict[str, Any]:
    raw = copy.deepcopy(raw_message("message_reply.json"))
    del raw[key]
    return raw


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (_without("id"), "sans identifiant"),
        (_without("payload"), "incomplet"),
        (_without("internalDate"), "sans date"),
    ],
    ids=["no-id", "no-payload", "no-date"],
)
def test_a_message_rocky_cannot_read_says_why(raw: dict[str, Any], reason: str) -> None:
    with pytest.raises(MessageUnreadableError, match=reason):
        parse_message(raw)


def test_a_collection_is_completed_partial_or_failed_with_its_reason() -> None:
    assert sync_status(
        SyncCounts(listed=3, new=3), listing_failure=None, write_failure=None
    ) == (SyncStatus.COMPLETED, None)
    assert sync_status(
        SyncCounts(listed=3, new=1, not_written=2),
        listing_failure=None,
        write_failure="message 18f incomplet",
    ) == (
        SyncStatus.PARTIAL,
        "2 messages non écrits, repris à la prochaine collecte : message 18f incomplet",
    )
    assert sync_status(
        SyncCounts(),
        listing_failure="Gmail est en panne (HTTP 503).",
        write_failure=None,
    ) == (SyncStatus.FAILED, "Gmail est en panne (HTTP 503).")
    assert sync_status(
        SyncCounts(listed=2, new=2),
        listing_failure="Gmail est en panne (HTTP 503).",
        write_failure=None,
    ) == (SyncStatus.PARTIAL, "Gmail est en panne (HTTP 503).")
