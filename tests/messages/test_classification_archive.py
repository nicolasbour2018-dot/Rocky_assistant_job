"""The rules replayed on the labelled sample of the archive A1 (E2, Q7): the old Rocky's mistakes are gone, no
confident decision attaches the wrong application, and the categories agree with the labels.

The sample (``data/archive_sample.csv``) keeps the sender, subject and snippet of 92 messages, anonymised; the old
Rocky read no body, so the rules read the snippet as the body. Labels: ``category`` and ``application`` (id in
``data/archive_applications.csv``), proposed by the agent; ``checked`` marks the lines Nicolas read. Provenance in
``data/README.md``.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from email.utils import parseaddr
from functools import cache
from pathlib import Path

import pytest

from rocky.candidatures.model import MailTarget, Stage
from rocky.messages.classification.model import (
    Context,
    Level,
    MailToClassify,
    Pending,
    Verdict,
)
from rocky.messages.classification.rules import classify

DATA = Path(__file__).parent / "data"
RECEIVED = datetime(2026, 9, 1, tzinfo=UTC)


@cache
def context() -> Context:
    """The archive's applications that may receive mail (never « En préparation », Q11)."""
    with (DATA / "archive_applications.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return Context(
        tuple(
            MailTarget(
                application_id=int(row["id"]),
                company=row["company"],
                title=row["title"],
                stage=Stage(row["stage"]),
                sent_on=None,
                employer_domain=None,
                links=tuple(
                    link for link in (row["url"], row["application_url"]) if link
                ),
            )
            for row in rows
            if row["stage"] != Stage.PREPARING.value
        )
    )


@cache
def sample() -> dict[int, dict[str, str]]:
    with (DATA / "archive_sample.csv").open(newline="") as handle:
        return {int(row["id"]): row for row in csv.DictReader(handle)}


def classified(message_id: int) -> Verdict | Pending:
    row = sample()[message_id]
    address = parseaddr(row["sender"])[1].lower()
    return classify(
        MailToClassify(
            id=message_id,
            mailbox_id=1,
            thread_id=f"fil-{message_id}",
            received_at=RECEIVED,
            sender=row["sender"],
            sender_address=address or None,
            subject=row["subject"],
            body_text=row["snippet"],
        ),
        context(),
    )


@pytest.mark.parametrize(
    "message_id",
    [800, 595, 144, 40, 710, 876, 881, 717, 730, 747, 329, 335, 364],
    ids=lambda message_id: f"archive-{message_id}",
)
def test_the_old_rockys_wrong_attachments_are_gone(message_id: int) -> None:
    """The Quora digest (French bee), METRO's refusal and Lobellia (Ministère de la justice), Google Agenda and OVH
    (Choisir le Service Public), CASDEN (La banque Postale), FreePrints (Free-Work), OneSchool Global (Liberty
    Global), Facebook, a receipt, a Google alert: all attached by fragments of names in the old Rocky."""
    found = classified(message_id)

    assert isinstance(found, Verdict)
    assert found.application_id is None


def test_no_confident_decision_attaches_another_application() -> None:
    wrong = [
        (message_id, found.application_id, row["application"])
        for message_id, row in sample().items()
        if isinstance(found := classified(message_id), Verdict)
        and found.level is not Level.LOW
        and found.application_id is not None
        and str(found.application_id) != row["application"]
    ]

    assert wrong == []


def test_the_confident_categories_agree_with_the_labels() -> None:
    confident = [
        (message_id, found, row)
        for message_id, row in sample().items()
        if isinstance(found := classified(message_id), Verdict)
        and found.level is not Level.LOW
    ]
    disagreeing = [
        (message_id, found.category, row["category"])
        for message_id, found, row in confident
        if (found.category or "") != row["category"]
    ]

    assert len(confident) >= 0.8 * len(sample())
    assert len(disagreeing) <= 0.05 * len(confident), disagreeing


def test_the_model_reads_few_messages() -> None:
    """Q5, Q17: only what carries a sign of the search and that the rules leave goes to the model."""
    pending = [
        message_id
        for message_id in sample()
        if isinstance(classified(message_id), Pending)
    ]

    assert len(pending) <= 0.15 * len(sample()), pending
