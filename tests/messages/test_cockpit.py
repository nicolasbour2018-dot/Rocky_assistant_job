"""What 📬 Messages gives 🧭 Cockpit (decision G3): lines of the feed (one by change, the decisions to check, the alerts
read), the sentence of an answer, the state of the mailboxes and a lost mailbox as a problem."""

from __future__ import annotations

from datetime import UTC, datetime

from rocky.candidatures.model import Stage
from rocky.messages.classification.model import Category
from rocky.messages.cockpit import (
    answer_sentences,
    attention_lines,
    journal_lines,
    lost_cards,
    mailbox_status,
)
from rocky.messages.decisions.model import Moved, Outcome, Transition
from rocky.messages.model import Mailbox, MailboxStatus
from rocky.messages.service import Attention, MailboxView
from rocky.offres.decisions import Author
from rocky.system.events import Actor, StoredEvent

NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)


def moved(
    application_id: int, to_stage: Stage, outcome: Outcome, hour: int = 9
) -> Moved:
    moment = NOW.replace(hour=hour)
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
            created_at=moment,
        ),
        subject="Votre candidature",
        sender="rh@exemple.fr",
        received_at=moment,
        author=Author.RULE,
        category=Category.REJECTION,
    )


def test_each_change_is_a_line_and_the_decisions_to_check_a_state() -> None:
    attention = Attention(
        moved=(
            moved(1, Stage.REJECTED, Outcome.APPLIED),
            moved(2, Stage.INTERVIEW, Outcome.PROPOSED),
        ),
        to_check=2,
        applications={1: "Data analyst chez French bee"},
    )

    lines = attention_lines(attention, NOW)

    assert [line.text for line in lines] == [
        "Data analyst chez French bee : Envoyée → Refusée.",
        "Candidature : Envoyée → Entretien (proposé).",
        "2 messages à vérifier : Rocky n'est pas sûr de son classement.",
    ]
    assert [line.standing for line in lines] == [False, False, True]
    assert lines[0].link is not None and lines[0].link.url == "/messages"


def test_the_latest_answer_of_a_person_is_the_sentence() -> None:
    attention = Attention(
        moved=(
            moved(1, Stage.INTERVIEW, Outcome.APPLIED, hour=8),
            moved(2, Stage.OFFER, Outcome.APPLIED, hour=10),
            moved(3, Stage.REJECTED, Outcome.APPLIED, hour=11),
        ),
        to_check=0,
        applications={2: "Data steward chez Covéa"},
    )

    assert [s.text for s in answer_sentences(attention)] == [
        "Du nouveau pour Data steward chez Covéa : offre."
    ]
    assert answer_sentences(Attention((), 0, {})) == []


def test_the_alerts_and_the_sorted_messages_are_one_line_a_day() -> None:
    def event(kind: str, hour: int, **payload: object) -> StoredEvent:
        return StoredEvent(hour, NOW.replace(hour=hour), kind, Actor.RULE, payload)  # type: ignore[arg-type]

    lines = journal_lines(
        [
            event("messages.alert_read", 8, platform="linkedin", created=3),
            event("messages.alert_read", 9, platform="hellowork", created=1),
            event("messages.message_classified", 10),
        ]
    )

    assert [(line.text, line.at.hour) for line in lines] == [
        ("2 alertes lues (Hellowork, LinkedIn) : 4 offres ajoutées.", 9),
        ("1 message classé.", 10),
    ]


def view(status: MailboxStatus) -> MailboxView:
    return MailboxView(Mailbox(1, 1, "n@exemple.fr", status, NOW, None), None)


def test_a_lost_mailbox_is_a_problem_with_its_gesture() -> None:
    cards = lost_cards([view(MailboxStatus.ACCESS_LOST)])

    assert len(cards) == 1 and cards[0].problem
    assert (
        cards[0].action is not None and cards[0].action.label == "Reconnecter la boîte"
    )
    assert lost_cards([view(MailboxStatus.CONNECTED)]) == []


def test_the_state_of_the_mailboxes() -> None:
    assert mailbox_status([], configured=False) == []
    none = mailbox_status([], configured=True)
    assert (
        none[0].text == "Aucune boîte Gmail connectée." and none[0].action is not None
    )
    lost = mailbox_status([view(MailboxStatus.ACCESS_LOST)], configured=True)
    assert lost[0].problem
    assert lost[0].text == "1 boîte Gmail, jamais relevée."
