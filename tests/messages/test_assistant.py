"""What the assistant 🐾 knows of a message (decision G4, Q11, Q31): never its body."""

from __future__ import annotations

from datetime import UTC, datetime

from rocky.messages.assistant import application_facts, message_sheet
from rocky.messages.classification.model import (
    Category,
    Level,
    Proof,
    SortedMessage,
    StoredDecision,
    Tier,
)
from rocky.messages.decisions.model import MessageRef
from rocky.messages.service import CorrectionView
from rocky.offres.decisions import Author

# 00:30 in Paris on 07/10.
RECEIVED = datetime(2026, 10, 6, 22, 30, tzinfo=UTC)
DECISION = StoredDecision(
    id=1,
    message_id=5,
    category=Category.INTERVIEW,
    application_id=9,
    level=Level.HIGH,
    author=Author.RULE,
    proofs=(
        Proof(Tier.DOMAIN, "domain", "Nous souhaitons vous rencontrer", "invitation"),
    ),
    version="e2",
    decided_at=RECEIVED,
)
MESSAGE = MessageRef(
    id=5,
    mailbox_address="camille@example.com",
    gmail_id="g-5",
    received_at=RECEIVED,
    sender="Valeo RH",
    sender_address="rh@valeo.example",
    subject="Votre candidature",
    body_text="Le corps entier du message, jamais donné au modèle.",
)


def test_a_message_gives_its_sender_classification_and_excerpt_never_its_body() -> None:
    sheet = message_sheet(
        CorrectionView(
            message=MESSAGE,
            decision=DECISION,
            applications={9: "Valeo — Data analyst"},
            rule_possible=False,
            domain=None,
            cited_employer=None,
        )
    )

    lines = [fact.line for fact in sheet.facts]
    assert lines == [
        "[message.expediteur] Expéditeur : Valeo RH",
        "[message.objet] Objet : Votre candidature",
        "[message.date] Reçu le : 07/10/2026",
        "[message.classement] Classement de Rocky : Entretien (confiance haute)",
        (
            "[message.justification] Ce qui justifie le classement : "
            "« Nous souhaitons vous rencontrer » (invitation)"
        ),
        "[message.candidature] Candidature liée : Valeo — Data analyst",
    ]
    assert sheet.facts[-1].link == "/candidatures/9"
    assert all("corps entier" not in line for line in lines)
    assert sheet.title == "Message de Valeo RH"


def test_the_messages_of_an_application_are_listed_with_their_excerpt() -> None:
    facts = application_facts(
        [
            SortedMessage(
                5,
                "camille@example.com",
                RECEIVED,
                "Valeo RH",
                "Votre candidature",
                (),
                DECISION,
            ),
            SortedMessage(
                6, "camille@example.com", RECEIVED, "Valeo RH", "Relance", (), None
            ),
        ]
    )

    assert [fact.line for fact in facts] == [
        (
            "[candidature.message_1] Message lié : reçu le 07/10/2026 de Valeo RH, « Votre candidature » : "
            "Entretien (confiance haute) ; extrait : « Nous souhaitons vous rencontrer »"
        ),
        "[candidature.message_2] Message lié : reçu le 07/10/2026 de Valeo RH, « Relance » : pas encore classé",
    ]
