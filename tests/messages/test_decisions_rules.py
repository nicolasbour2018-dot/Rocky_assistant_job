"""The rules of the decisions on the messages (E4): the stage a category gives (Q2), applied, proposed or nothing (Q1,
Q10), what a correction may teach (Q7), the groups of a list (Q8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rocky.candidatures.model import Stage
from rocky.messages.classification.model import (
    Category,
    Level,
    Proof,
    SortedMessage,
    StoredDecision,
    Tier,
)
from rocky.messages.decisions.model import MessageRef, Outcome, TransitionPlan
from rocky.messages.decisions.rules import (
    cited_employer,
    domain_offered,
    gmail_link,
    grouped,
    paris_day,
    plan_transition,
    rule_offered,
    rule_possible,
    target_stage,
)
from rocky.offres.decisions import Author

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("category", "current", "expected"),
    [
        (Category.REJECTION, Stage.SENT, Stage.REJECTED),
        (Category.INTERVIEW, Stage.SENT, Stage.INTERVIEW),
        (Category.ASSESSMENT, Stage.IN_DISCUSSION, Stage.INTERVIEW),
        (Category.OFFER, Stage.INTERVIEW, Stage.OFFER),
        (Category.EMPLOYER_UPDATE, Stage.SENT, Stage.IN_DISCUSSION),
        (Category.ACKNOWLEDGEMENT, Stage.PREFILLED, Stage.SENT),
        (Category.ACKNOWLEDGEMENT, Stage.SENT, None),
        (Category.PLATFORM_NOTICE, Stage.SENT, None),
        (Category.RECRUITER_APPROACH, Stage.SENT, None),
        (Category.JOB_ALERT, Stage.SENT, None),
        (Category.UNRELATED, Stage.SENT, None),
    ],
)
def test_each_category_gives_its_stage(
    category: Category, current: Stage, expected: Stage | None
) -> None:
    """Q2: an acknowledgement only proves the sending of an application « Préremplie »."""
    assert target_stage(category, current) is expected


def test_a_rule_of_confidence_high_applies_and_medium_proposes() -> None:
    """Q1."""
    assert plan_transition(
        Category.REJECTION, Level.HIGH, Author.RULE, Stage.SENT
    ) == TransitionPlan(Outcome.APPLIED, Stage.REJECTED)
    assert plan_transition(
        Category.REJECTION, Level.MEDIUM, Author.RULE, Stage.SENT
    ) == TransitionPlan(Outcome.PROPOSED, Stage.REJECTED)
    assert plan_transition(
        Category.REJECTION, Level.MEDIUM, Author.AI, Stage.SENT
    ) == TransitionPlan(Outcome.PROPOSED, Stage.REJECTED)


def test_nothing_is_proposed_for_a_decision_to_check_or_without_category() -> None:
    """Q1: « À vérifier » gives nothing."""
    assert plan_transition(Category.REJECTION, Level.LOW, Author.AI, Stage.SENT) is None
    assert plan_transition(None, Level.LOW, Author.RULE, Stage.SENT) is None


def test_the_users_decision_is_always_proposed() -> None:
    """A correction or a confirmation proposes its transition: one more gesture applies it."""
    assert plan_transition(
        Category.INTERVIEW, Level.HIGH, Author.USER, Stage.SENT
    ) == TransitionPlan(Outcome.PROPOSED, Stage.INTERVIEW)


def test_leaving_an_outcome_is_proposed_going_backwards_is_nothing() -> None:
    """Q10."""
    assert plan_transition(
        Category.REJECTION, Level.HIGH, Author.RULE, Stage.NO_RESPONSE
    ) == TransitionPlan(Outcome.PROPOSED, Stage.REJECTED)
    assert plan_transition(
        Category.INTERVIEW, Level.MEDIUM, Author.RULE, Stage.REJECTED
    ) == TransitionPlan(Outcome.PROPOSED, Stage.INTERVIEW)
    assert (
        plan_transition(
            Category.EMPLOYER_UPDATE, Level.HIGH, Author.RULE, Stage.INTERVIEW
        )
        is None
    )
    assert (
        plan_transition(Category.REJECTION, Level.LOW, Author.RULE, Stage.NO_RESPONSE)
        is None
    )


def test_nothing_moves_an_application_already_at_the_stage() -> None:
    assert (
        plan_transition(Category.REJECTION, Level.HIGH, Author.RULE, Stage.REJECTED)
        is None
    )
    assert (
        plan_transition(Category.INTERVIEW, Level.HIGH, Author.USER, Stage.INTERVIEW)
        is None
    )


def test_a_rule_is_offered_for_an_exact_address_never_for_a_platform() -> None:
    """Q7: the InMail of a recruiter (``messages-noreply@linkedin.com``) or a newsletter, never an alert or relay
    address nor an ATS; and only for a category without application."""
    assert rule_offered("messages-noreply@linkedin.com", Category.RECRUITER_APPROACH)
    assert rule_offered("news@orderandchaos.example", Category.UNRELATED)
    assert not rule_offered("jobalerts-noreply@linkedin.com", Category.UNRELATED)
    assert not rule_offered("emploi@emails.hellowork.com", Category.UNRELATED)
    assert not rule_offered("r-c-1@reply.hellowork.com", Category.UNRELATED)
    assert not rule_offered("no-reply@ashbyhq.com", Category.UNRELATED)
    assert not rule_offered("rh@frenchbee.com", Category.REJECTION)
    assert not rule_offered(None, Category.UNRELATED)
    assert rule_possible("rh@frenchbee.com")


def test_the_domain_is_learnt_from_an_employer_never_a_public_mail_service() -> None:
    """Q7."""
    assert domain_offered("rh@talent.frenchbee.com") == "frenchbee.com"
    assert domain_offered("recruteuse@gmail.com") is None
    assert domain_offered("camille@orange.fr") is None
    assert domain_offered("no-reply@ashbyhq.com") is None
    assert domain_offered("jobs-noreply@linkedin.com") is None
    assert domain_offered(None) is None


def _ref() -> MessageRef:
    return MessageRef(
        id=1,
        mailbox_address="camille@example.com",
        gmail_id="18f0a1",
        received_at=NOW,
        sender="Hellowork <emploi@emails.hellowork.com>",
        sender_address="emploi@emails.hellowork.com",
        subject="Votre candidature est arrivée chez ATHEIA",
    )


def test_the_offer_of_a_message_points_to_the_message_in_gmail() -> None:
    """Q4: never an empty address."""
    assert (
        gmail_link(_ref())
        == "https://mail.google.com/mail/u/camille%40example.com/#all/18f0a1"
    )


def test_the_day_is_the_users_in_paris() -> None:
    assert (
        paris_day(datetime(2026, 10, 5, 22, 30, tzinfo=UTC)).isoformat() == "2026-10-06"
    )


def _decision(
    category: Category | None,
    application_id: int | None,
    proofs: tuple[Proof, ...] = (),
) -> StoredDecision:
    return StoredDecision(
        id=1,
        message_id=1,
        category=category,
        application_id=application_id,
        level=Level.MEDIUM,
        author=Author.RULE,
        proofs=proofs or (Proof(Tier.PHRASE, "phrase.rejection", "x", "y"),),
        version="v",
        decided_at=NOW,
    )


def test_the_cited_employer_is_read_in_the_proofs() -> None:
    """E2 Q22: the employer a platform names is the excerpt of ``employer.cited``."""
    decision = _decision(
        Category.ACKNOWLEDGEMENT,
        None,
        (
            Proof(Tier.PLATFORM, "relay.arrived", "arrivée chez ATHEIA", "r"),
            Proof(Tier.PLATFORM, "employer.cited", "ATHEIA", "Employeur cité."),
        ),
    )
    assert cited_employer(decision) == "ATHEIA"
    assert cited_employer(_decision(Category.REJECTION, 3)) is None
    assert cited_employer(None) is None


def _message(
    message_id: int, minutes: int, category: Category | None, application_id: int | None
) -> SortedMessage:
    return SortedMessage(
        id=message_id,
        mailbox_address="camille@example.com",
        received_at=NOW - timedelta(minutes=minutes),
        sender="x",
        subject=str(message_id),
        found_by=(),
        decision=None if category is None else _decision(category, application_id),
    )


def test_the_messages_of_an_application_are_grouped_the_most_decisive_first() -> None:
    """Q8: one group per application in the order of its latest message; a message without one is alone."""
    reminder = _message(1, 0, Category.PLATFORM_NOTICE, 7)
    alert = _message(2, 5, Category.JOB_ALERT, None)
    refusal = _message(3, 10, Category.REJECTION, 7)
    acknowledgement = _message(4, 20, Category.ACKNOWLEDGEMENT, 7)
    waiting = _message(5, 30, None, None)
    other = _message(6, 40, Category.ACKNOWLEDGEMENT, 8)

    groups = grouped([reminder, alert, refusal, acknowledgement, waiting, other])

    assert [(group.head.id, [m.id for m in group.others]) for group in groups] == [
        (3, [1, 4]),
        (2, []),
        (5, []),
        (6, []),
    ]
