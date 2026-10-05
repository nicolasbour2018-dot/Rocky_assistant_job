"""What 🏠 Aujourd'hui shows of the applications (decision F1, Q5): follow-ups due, applications to finish."""

from __future__ import annotations

from datetime import date, timedelta

from rocky.candidatures.model import NextAction, Stage
from rocky.candidatures.rules import tabs_of
from rocky.candidatures.today import due_actions, follow_up_card, unfinished_card
from rocky.candidatures.web import Row
from rocky.offres.model import OfferHeading

TODAY = date(2026, 10, 5)


def row(
    row_id: int, stage: Stage, *, due_in: int | None = None, company: str = "Acme"
) -> Row:
    action = (
        None
        if due_in is None
        else NextAction("Relancer", TODAY + timedelta(days=due_in))
    )
    return Row(
        row_id,
        OfferHeading(row_id, f"Data analyst {row_id}", company, "Paris"),
        stage,
        action,
        action is not None and action.due < TODAY,
        None,
        tabs_of(stage, action, TODAY),
    )


def test_follow_ups_due_are_the_sent_applications_whose_action_is_due() -> None:
    rows = [
        row(1, Stage.SENT, due_in=0),
        row(2, Stage.SENT, due_in=3),  # not due yet
        row(3, Stage.INTERVIEW, due_in=-2),
        row(4, Stage.PREPARING, due_in=-1),  # not sent: a dossier to finish
    ]

    card = follow_up_card(rows, TODAY)

    assert card is not None
    assert card.lines == (
        "Acme — Data analyst 3 : Relancer (en retard depuis le 03/10)",
        "Acme — Data analyst 1 : Relancer (aujourd'hui)",
    )
    assert card.action is not None and card.action.url == "/candidatures"


def test_no_follow_up_block_when_nothing_is_due() -> None:
    assert follow_up_card([row(1, Stage.SENT, due_in=1)], TODAY) is None


def test_dossiers_to_finish_are_the_applications_not_sent_and_beyond_three_are_counted() -> (
    None
):
    rows = [
        row(1, Stage.READY, due_in=2),
        row(2, Stage.PREPARING),
        row(3, Stage.PREPARING, due_in=-1),
        row(4, Stage.PREFILLED, due_in=0),
        row(5, Stage.READY, due_in=5),
        row(6, Stage.SENT, due_in=0),
    ]

    card = unfinished_card(rows, TODAY)

    assert card is not None
    assert card.lines == (
        "Acme — Data analyst 3 : Relancer (en retard depuis le 04/10)",
        "Acme — Data analyst 4 : Relancer (aujourd'hui)",
        "Acme — Data analyst 1 : Relancer (le 07/10)",
        "… et 2 autres.",
    )
    assert card.action is not None
    assert card.action.url == "/candidatures?vue=preparation"


def test_ready_applications_alone_lead_to_the_ready_tab() -> None:
    card = unfinished_card([row(1, Stage.READY)], TODAY)

    assert card is not None
    assert card.lines == ("Acme — Data analyst 1 : Prête à envoyer",)
    assert card.action is not None and card.action.url == "/candidatures?vue=pretes"


def test_the_drawer_leads_to_each_application_whose_action_is_due() -> None:
    actions = due_actions(
        [
            row(1, Stage.SENT, due_in=0),
            row(2, Stage.SENT, due_in=3),
            row(3, Stage.PREPARING, due_in=-1, company="Covéa"),
        ]
    )

    assert [(action.label, action.url) for action in actions] == [
        ("Covéa — Data analyst 3 : Relancer", "/candidatures/3"),
        ("Acme — Data analyst 1 : Relancer", "/candidatures/1"),
    ]
