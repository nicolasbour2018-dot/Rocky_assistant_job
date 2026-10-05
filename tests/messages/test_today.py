"""What 🏠 Aujourd'hui shows of the messages (decision F1, Q7): one line by change, the decisions to check, and the way
to 📬 Messages, where the gestures stay."""

from __future__ import annotations

from datetime import UTC, datetime

from rocky.candidatures.model import Stage
from rocky.messages.classification.model import Category
from rocky.messages.decisions.model import Moved, Outcome, Transition
from rocky.messages.service import Attention
from rocky.messages.web import attention_card
from rocky.offres.decisions import Author

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)


def moved(application_id: int, to_stage: Stage, outcome: Outcome) -> Moved:
    return Moved(
        transition=Transition(
            id=application_id,
            message_id=application_id,
            decision_id=application_id,
            application_id=application_id,
            from_stage=Stage.SENT,
            to_stage=to_stage,
            outcome=outcome,
            change_id=None,
            created_at=NOW,
        ),
        subject="Votre candidature",
        sender="rh@exemple.fr",
        received_at=NOW,
        author=Author.RULE,
        category=Category.REJECTION,
    )


def test_nothing_moved_nothing_to_check_no_block() -> None:
    assert attention_card(Attention(moved=(), to_check=0, applications={})) is None


def test_each_change_is_a_line_and_beyond_three_they_are_counted() -> None:
    attention = Attention(
        moved=(
            moved(1, Stage.REJECTED, Outcome.APPLIED),
            moved(2, Stage.INTERVIEW, Outcome.PROPOSED),
            moved(3, Stage.IN_DISCUSSION, Outcome.APPLIED),
            moved(4, Stage.REJECTED, Outcome.APPLIED),
        ),
        to_check=2,
        applications={1: "French bee — Data analyst", 2: "Covéa — Data steward"},
    )

    card = attention_card(attention)

    assert card is not None
    assert card.title == "📬 Ce qui a bougé"
    assert card.lines == (
        "French bee — Data analyst : Envoyée → Refusée",
        "Covéa — Data steward : Envoyée → Entretien (proposé)",
        "Candidature : Envoyée → En discussion",
        "… et 1 autre changement.",
        "2 messages à vérifier : Rocky n'est pas sûr de son classement.",
    )
    assert card.action is not None and card.action.url == "/messages"


def test_decisions_to_check_alone_lead_to_their_view() -> None:
    card = attention_card(Attention(moved=(), to_check=1, applications={}))

    assert card is not None
    assert card.title == "📬 Messages à vérifier"
    assert card.action is not None and card.action.url == "/messages?vue=a-verifier"
