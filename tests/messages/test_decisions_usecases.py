"""The decisions on the messages on PostgreSQL (E4), through the service as the screen uses it: a decision gives its
application's transition in its transaction (Q1), nothing leaves « Ce qui a bougé » without a gesture (Q5), a
correction undoes what the message did (Q3), the account's rules (Q7), « Créer la candidature » (Q4), the labels (Q6).

Exit criterion: « Aucun changement de statut ne passe inaperçu ».
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from rocky.candidatures.model import Stage
from rocky.candidatures.rules import INTERVIEW_DATE_TO_SET, dossier
from rocky.candidatures.sql import SqlApplicationStore, application_changes
from rocky.candidatures.usecases import change_stage, set_employer_domain
from rocky.messages.classification.model import Category, Level
from rocky.messages.classification.rules import ACCOUNT_RULE
from rocky.messages.decisions.model import Gesture, InvalidGestureError, Outcome
from rocky.messages.decisions.usecases import CORRECTED_RULE, CREATED_RULE
from rocky.messages.links import CandidaturesLink
from rocky.messages.service import MessagesService
from rocky.messages.sql import (
    SqlStore,
    mail_sender_rules,
    mail_transition_settlements,
    mail_transitions,
    message_decisions,
)
from rocky.messages.usecases import connect_mailbox
from rocky.offres.decisions import APPLIED_OUTSIDE, Author
from rocky.offres.sql import job_decisions, job_offers
from rocky.system.events import events
from tests.messages.fakes import GMAIL, NOW, cipher, sent_application, store_mail
from tests.offres.fakes import Seeker, new_seeker

REFUSAL = (
    "Bonjour, nous revenons vers vous concernant votre candidature au poste de Data Analyst - Data Steward H/F. "
    "Après une étude approfondie, nous vous informons que celle-ci n'a malheureusement pas été retenue."
)
INTERVIEW = (
    "Bonjour, suite à votre candidature au poste de Data Analyst - Data Steward H/F, nous souhaitons vous "
    "proposer un entretien la semaine prochaine."
)
# French bee answers from its own domain (high), or through an ATS by its name and the offer's title (medium).
FROM_EMPLOYER = "French bee RH <rh@frenchbee.com>"
FROM_ATS = "French bee <no-reply@ashbyhq.com>"
INMAIL = "Léa Martin via LinkedIn <messages-noreply@linkedin.com>"


@dataclass
class Box:
    engine: Engine
    service: MessagesService
    seeker: Seeker
    mailbox_id: int
    french_bee: int

    @property
    def account_id(self) -> int:
        return self.seeker.account_id

    def mail(self, sender: str, subject: str, body: str = "", **extra: Any) -> int:
        return store_mail(
            self.service.storage,
            self.mailbox_id,
            sender=sender,
            subject=subject,
            body=body,
            **extra,
        )

    def classify(self, *, again: bool = False) -> None:
        self.service.classify(self.account_id, use_model=False, again=again)

    def stage(self, application_id: int | None = None) -> Stage | None:
        with self.engine.connect() as connection:
            changes = SqlApplicationStore(connection).changes(
                application_id or self.french_bee
            )
        return dossier(changes).stage

    def next_action(self) -> tuple[str, str] | None:
        with self.engine.connect() as connection:
            action = dossier(
                SqlApplicationStore(connection).changes(self.french_bee)
            ).next_action
        return None if action is None else (action.label, action.due.isoformat())

    def moved(self) -> list[tuple[str, str, str]]:
        return [
            (
                line.transition.from_stage,
                line.transition.to_stage,
                line.transition.outcome,
            )
            for line in self.service.state(self.account_id).moved
        ]

    def moved_ids(self) -> list[int]:
        return [
            line.transition.id for line in self.service.state(self.account_id).moved
        ]

    def decision(self, message_id: int) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(message_decisions)
                .where(message_decisions.c.message_id == message_id)
                .order_by(message_decisions.c.id.desc())
                .limit(1)
            ).one()
        return dict(row._mapping)

    def count(self, table: Any) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.account_id == self.account_id)
                ).scalar_one()
            )

    def event_types(self) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(events.c.type)
                    .where(events.c.account_id == self.account_id)
                    .order_by(events.c.id)
                ).scalars()
            )

    def snapshot(self) -> tuple[object, ...]:
        """What a failed transaction must leave as it was."""
        return (
            self.stage(),
            self.next_action(),
            self.count(message_decisions),
            self.count(mail_transitions),
            self.count(mail_transition_settlements),
            self.count(application_changes),
            self.count(mail_sender_rules),
            len(self.event_types()),
        )


@pytest.fixture
def box(migrated_engine: Engine) -> Box:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)
        french_bee = sent_application(
            connection,
            seeker,
            company="French bee",
            title="Data Analyst - Data Steward H/F",
        )
    service = MessagesService(migrated_engine, settings=GMAIL, clock=lambda: NOW)
    mailbox_id, _ = connect_mailbox(
        service.storage,
        cipher(),
        account_id=seeker.account_id,
        address="camille@example.com",
        refresh_token="1//rafraichissement",
        now=NOW,
    )
    return Box(migrated_engine, service, seeker, mailbox_id, french_bee)


def _with_domain(box: Box) -> None:
    with box.engine.begin() as connection:
        set_employer_domain(
            SqlApplicationStore(connection),
            account_id=box.account_id,
            application_id=box.french_bee,
            typed="frenchbee.com",
            now=NOW,
        )


# Q1: confidence high applies, medium proposes; nothing leaves « Ce qui a bougé » without a gesture (Q5).


def test_a_refusal_of_confidence_high_moves_the_application_and_says_so(
    box: Box,
) -> None:
    _with_domain(box)
    message_id = box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)

    box.classify()

    assert box.decision(message_id)["level"] == Level.HIGH.value
    assert box.stage() is Stage.REJECTED
    assert box.moved() == [(Stage.SENT, Stage.REJECTED, Outcome.APPLIED)]
    assert box.service.pending_count(box.account_id) == 1
    with box.engine.connect() as connection:
        transition = connection.execute(select(mail_transitions)).all()
        change = connection.execute(
            select(events.c.actor, events.c.payload)
            .where(
                events.c.account_id == box.account_id,
                events.c.type == "candidatures.stage_changed",
            )
            .order_by(events.c.id.desc())
        ).first()
    assert any(
        row.message_id == message_id and row.change_id is not None for row in transition
    )
    assert change is not None
    assert change.actor == "rule"
    assert change.payload["message_id"] == message_id

    box.service.mark_seen(box.account_id, box.moved_ids()[0])

    assert box.moved() == []
    assert box.service.pending_count(box.account_id) == 0
    assert box.stage() is Stage.REJECTED


def test_every_change_by_a_rule_has_its_line_until_a_gesture(box: Box) -> None:
    """Exit criterion: each stage change written by a rule is a transition of « Ce qui a bougé »."""
    _with_domain(box)
    box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", INTERVIEW)
    box.classify()

    with box.engine.connect() as connection:
        by_rule = set(
            connection.execute(
                select(application_changes.c.id).where(
                    application_changes.c.account_id == box.account_id,
                    application_changes.c.author != Author.USER.value,
                )
            ).scalars()
        )
        recorded = set(
            connection.execute(
                select(mail_transitions.c.change_id).where(
                    mail_transitions.c.account_id == box.account_id
                )
            ).scalars()
        )
    assert by_rule
    assert by_rule <= recorded
    assert box.service.pending_count(box.account_id) == len(box.moved()) == 1
    assert box.stage() is Stage.INTERVIEW
    assert box.next_action() == (
        INTERVIEW_DATE_TO_SET,
        (NOW.date() + timedelta(days=1)).isoformat(),
    )


def test_a_refusal_of_confidence_medium_is_proposed_then_applied(box: Box) -> None:
    message_id = box.mail(FROM_ATS, "Votre candidature", REFUSAL)

    box.classify()

    assert box.decision(message_id)["level"] == Level.MEDIUM.value
    assert box.stage() is Stage.SENT
    assert box.moved() == [(Stage.SENT, Stage.REJECTED, Outcome.PROPOSED)]

    box.service.apply_proposal(box.account_id, box.moved_ids()[0])

    assert box.stage() is Stage.REJECTED
    assert box.moved() == []
    with box.engine.connect() as connection:
        settled = connection.execute(select(mail_transition_settlements)).all()
    assert any(
        row.gesture == Gesture.APPLIED.value and row.change_id for row in settled
    )


def test_a_proposal_ignored_changes_nothing(box: Box) -> None:
    box.mail(FROM_ATS, "Votre candidature", REFUSAL)
    box.classify()

    box.service.dismiss(box.account_id, box.moved_ids()[0])

    assert box.stage() is Stage.SENT
    assert box.moved() == []


def test_an_applied_transition_is_cancelled_while_it_is_the_latest_change(
    box: Box,
) -> None:
    _with_domain(box)
    box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.classify()
    transition_id = box.moved_ids()[0]

    with pytest.raises(InvalidGestureError):
        box.service.dismiss(box.account_id, transition_id)
    box.service.cancel_transition(box.account_id, transition_id)

    assert box.stage() is Stage.SENT
    assert box.moved() == []
    with pytest.raises(InvalidGestureError):
        box.service.mark_seen(box.account_id, transition_id)


def test_a_transition_the_user_changed_since_is_not_cancelled(box: Box) -> None:
    _with_domain(box)
    box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.classify()
    _move(box, Stage.INTERVIEW)

    with pytest.raises(InvalidGestureError):
        box.service.cancel_transition(box.account_id, box.moved_ids()[0])

    assert box.stage() is Stage.INTERVIEW
    assert len(box.moved()) == 1


def test_another_account_cannot_settle_a_transition(
    box: Box, migrated_engine: Engine
) -> None:
    _with_domain(box)
    box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.classify()
    with migrated_engine.begin() as connection:
        other = new_seeker(connection)

    with pytest.raises(InvalidGestureError):
        box.service.mark_seen(other.account_id, box.moved_ids()[0])


def test_classifying_again_adds_no_transition(box: Box) -> None:
    """Idempotence: a reclassification or a replayed hook moves nothing twice."""
    _with_domain(box)
    box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.mail(FROM_ATS, "Votre candidature", INTERVIEW)
    box.classify()
    before = (box.count(mail_transitions), box.count(application_changes))

    box.classify()
    box.classify(again=True)

    assert (box.count(mail_transitions), box.count(application_changes)) == before


def test_a_later_decision_replaces_the_earlier_proposal(box: Box) -> None:
    """A message classified again with another proposal: the earlier one leaves « Ce qui a bougé »."""
    message_id = box.mail(FROM_ATS, "Votre candidature", REFUSAL)
    box.classify()

    box.service.correct(
        box.account_id,
        message_id,
        category=Category.INTERVIEW,
        application_id=box.french_bee,
        remember_sender=False,
        remember_domain=False,
    )

    assert box.moved() == [(Stage.SENT, Stage.INTERVIEW, Outcome.PROPOSED)]


# Q3, Q6: corrections.


def test_a_correction_undoes_the_transition_of_the_message(box: Box) -> None:
    _with_domain(box)
    message_id = box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.classify()
    rocky_decision = box.decision(message_id)

    result = box.service.correct(
        box.account_id,
        message_id,
        category=Category.EMPLOYER_UPDATE,
        application_id=box.french_bee,
        remember_sender=False,
        remember_domain=False,
    )

    assert not result.kept
    assert box.stage() is Stage.SENT
    corrected = box.decision(message_id)
    assert corrected["author"] == Author.USER.value
    assert corrected["rule"] == CORRECTED_RULE
    assert corrected["reviews_id"] == rocky_decision["id"]
    # The correction's own transition is proposed; the undone one left « Ce qui a bougé ».
    assert box.moved() == [(Stage.SENT, Stage.IN_DISCUSSION, Outcome.PROPOSED)]


def test_a_correction_keeps_a_transition_the_user_changed_since(box: Box) -> None:
    """Q3: what the user did after the message stays."""
    _with_domain(box)
    message_id = box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.classify()
    _move(box, Stage.INTERVIEW)

    result = box.service.correct(
        box.account_id,
        message_id,
        category=Category.UNRELATED,
        application_id=None,
        remember_sender=False,
        remember_domain=False,
    )

    assert result.kept
    assert box.stage() is Stage.INTERVIEW
    assert box.moved() == []


def test_a_correction_to_another_application_is_refused_when_it_is_not_open(
    box: Box,
) -> None:
    message_id = box.mail(FROM_ATS, "Votre candidature", REFUSAL)
    box.classify()

    with pytest.raises(InvalidGestureError):
        box.service.correct(
            box.account_id,
            message_id,
            category=Category.REJECTION,
            application_id=box.french_bee + 10_000,
            remember_sender=False,
            remember_domain=False,
        )


def test_confirming_writes_a_label_and_proposes_the_transition(box: Box) -> None:
    message_id = box.mail(FROM_ATS, "Votre candidature", REFUSAL)
    box.classify()

    box.service.confirm(box.account_id, message_id)
    box.service.confirm(box.account_id, message_id)

    decision = box.decision(message_id)
    assert decision["author"] == Author.USER.value
    assert decision["category"] == Category.REJECTION.value
    assert box.moved() == [(Stage.SENT, Stage.REJECTED, Outcome.PROPOSED)]
    labels = box.service.labels(box.account_id)
    assert [
        (label.gesture, label.category, label.reviewed_category) for label in labels
    ] == [("user.confirmed", Category.REJECTION, Category.REJECTION)]


# The writes of a correction: the cancelled change, its settlement and event, the decision and its event, the proposed
# transition and its event.
@pytest.mark.parametrize("fail_at", range(1, 8))
def test_a_failure_during_a_correction_leaves_nothing_contradictory(
    box: Box, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Q3, like D1: a failure after any write of the correction leaves the state as it was."""
    _with_domain(box)
    message_id = box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    box.classify()
    before = box.snapshot()
    _fail_at(monkeypatch, fail_at)

    with pytest.raises(_InjectedError):
        box.service.correct(
            box.account_id,
            message_id,
            category=Category.EMPLOYER_UPDATE,
            application_id=box.french_bee,
            remember_sender=False,
            remember_domain=False,
        )

    assert box.snapshot() == before


# The writes of a decision of confidence high: the decision and its event, the change, the transition and its event.
@pytest.mark.parametrize("fail_at", range(1, 6))
def test_a_failure_while_following_a_decision_writes_neither(
    box: Box, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Q1: the decision, the change of the application and the transition are written together or not at all."""
    _with_domain(box)
    box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    before = box.snapshot()
    _fail_at(monkeypatch, fail_at)

    with pytest.raises(_InjectedError):
        box.classify()

    assert box.snapshot() == before


def test_the_failure_points_cover_every_write(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two tests above inject a failure after each write: there is none after the last one they cover."""
    _with_domain(box)
    message_id = box.mail(FROM_EMPLOYER, "Votre candidature chez French bee", REFUSAL)
    _fail_at(monkeypatch, 6)
    box.classify()
    monkeypatch.undo()
    _fail_at(monkeypatch, 8)
    box.service.correct(
        box.account_id,
        message_id,
        category=Category.EMPLOYER_UPDATE,
        application_id=box.french_bee,
        remember_sender=False,
        remember_domain=False,
    )
    assert box.stage() is Stage.SENT


# Q7: rules per sender, domains.


def test_a_rule_for_a_sender_classifies_its_messages(box: Box) -> None:
    """The InMail of a recruiter through LinkedIn's notifications (E2, known case)."""
    first = box.mail(
        INMAIL,
        "Léa vous a envoyé un message",
        "Bonjour Camille, un poste de data analyst ?",
    )
    earlier = box.mail(INMAIL, "Léa vous a envoyé un message", "Je reviens vers vous.")
    box.classify()
    assert box.decision(earlier)["category"] == Category.UNRELATED.value

    result = box.service.correct(
        box.account_id,
        first,
        category=Category.RECRUITER_APPROACH,
        application_id=None,
        remember_sender=True,
        remember_domain=False,
    )
    later = box.mail(INMAIL, "Léa vous a envoyé un message", "Toujours d'accord ?")
    box.classify()

    assert result.rule_address == "messages-noreply@linkedin.com"
    assert box.decision(earlier)["category"] == Category.RECRUITER_APPROACH.value
    assert box.decision(later)["category"] == Category.RECRUITER_APPROACH.value
    assert box.decision(later)["rule"] == ACCOUNT_RULE
    assert [
        rule.sender_address for rule in box.service.state(box.account_id).rules
    ] == ["messages-noreply@linkedin.com"]

    rule_id = box.service.state(box.account_id).rules[0].id
    box.service.remove_rule(box.account_id, rule_id)

    assert box.service.state(box.account_id).rules == ()
    assert "messages.sender_rule_removed" in box.event_types()


def test_no_rule_is_made_for_a_platform_or_an_employer_category(box: Box) -> None:
    message_id = box.mail(FROM_ATS, "Votre candidature", REFUSAL)
    box.classify()

    result = box.service.correct(
        box.account_id,
        message_id,
        category=Category.UNRELATED,
        application_id=None,
        remember_sender=True,
        remember_domain=False,
    )

    assert result.rule_address is None
    assert box.count(mail_sender_rules) == 0


def test_a_correction_may_learn_the_employers_domain(box: Box) -> None:
    message_id = box.mail(
        "Julie <julie@talent.frenchbee.com>", "Votre profil", "Bonjour Camille"
    )
    box.classify()

    result = box.service.correct(
        box.account_id,
        message_id,
        category=Category.EMPLOYER_UPDATE,
        application_id=box.french_bee,
        remember_sender=False,
        remember_domain=True,
    )

    assert result.domain == "frenchbee.com"
    with box.engine.connect() as connection:
        assert (
            SqlApplicationStore(connection).employer_domain(box.french_bee)
            == "frenchbee.com"
        )


# Q4, Q12: an application made outside Rocky.


def test_an_application_is_created_from_an_acknowledgement(box: Box) -> None:
    subject = "Votre candidature est arrivée chez ATHEIA"
    first = box.mail("Hellowork <emploi@emails.hellowork.com>", subject)
    second = box.mail(
        "Hellowork <emploi@emails.hellowork.com>",
        subject,
        received_at=NOW - timedelta(days=1),
    )
    box.classify()
    assert box.decision(first)["application_id"] is None

    with box.engine.connect() as connection:
        profile = box.seeker.profile(connection)
    application_id = box.service.create_application(
        box.account_id,
        first,
        company="ATHEIA",
        title="Data Analyst",
        link="",
        profile=profile,
    )
    again = box.service.create_application(
        box.account_id,
        first,
        company="ATHEIA",
        title="Data Analyst",
        link="",
        profile=profile,
    )

    assert again == application_id
    assert box.stage(application_id) is Stage.SENT
    decision = box.decision(first)
    assert (decision["application_id"], decision["author"], decision["rule"]) == (
        application_id,
        Author.USER.value,
        CREATED_RULE,
    )
    assert decision["category"] == Category.ACKNOWLEDGEMENT.value
    # The other message citing ATHEIA is attached by the rules once the application exists.
    assert box.decision(second)["application_id"] == application_id
    with box.engine.connect() as connection:
        offers = connection.execute(
            select(job_offers.c.origin, job_offers.c.url, job_offers.c.company).where(
                job_offers.c.account_id == box.account_id,
                job_offers.c.origin == "message",
            )
        ).all()
        reasons = (
            connection.execute(
                select(job_decisions.c.reasons).where(
                    job_decisions.c.account_id == box.account_id
                )
            )
            .scalars()
            .all()
        )
    assert len(offers) == 1
    assert offers[0].url.startswith(
        "https://mail.google.com/mail/u/camille%40example.com/#all/"
    )
    assert offers[0].company == "ATHEIA"
    assert [APPLIED_OUTSIDE] in [list(value) for value in reasons]


def test_creating_an_application_needs_its_employer_and_title(box: Box) -> None:
    message_id = box.mail(
        "Hellowork <emploi@emails.hellowork.com>",
        "Votre candidature est arrivée chez ATHEIA",
    )
    box.classify()
    with box.engine.connect() as connection:
        profile = box.seeker.profile(connection)

    for company, title in (("", "Data Analyst"), ("ATHEIA", " ")):
        with pytest.raises(InvalidGestureError):
            box.service.create_application(
                box.account_id,
                message_id,
                company=company,
                title=title,
                link="",
                profile=profile,
            )
    assert box.count(job_offers) == 1  # the French bee offer of the fixture alone


def test_the_dossier_lists_its_messages(box: Box) -> None:
    box.mail(FROM_ATS, "Votre candidature", REFUSAL)
    box.mail(INMAIL, "Léa vous a envoyé un message", "Bonjour")
    box.classify()

    messages = box.service.application_messages(box.account_id, box.french_bee)

    assert [message.subject for message in messages] == ["Votre candidature"]


# Helpers


def _move(box: Box, stage: Stage) -> None:
    with box.engine.begin() as connection:
        change_stage(
            SqlApplicationStore(connection),
            account_id=box.account_id,
            application_id=box.french_bee,
            stage=stage,
            next_action=None,
            now=NOW,
        )


class _InjectedError(Exception):
    pass


def _fail_at(monkeypatch: pytest.MonkeyPatch, n: int) -> None:
    """Raise at the ``n``-th write of the decisions (their SQL, or a change of the application)."""
    counter = iter(range(1, 1000))
    writes: list[tuple[type, str]] = [
        (SqlStore, "add_decision"),
        (SqlStore, "add_transition"),
        (SqlStore, "settle"),
        (SqlStore, "append_event"),
        (SqlStore, "add_sender_rule"),
        (CandidaturesLink, "move"),
        (CandidaturesLink, "cancel"),
    ]
    for owner, name in writes:
        original: Callable[..., Any] = getattr(owner, name)

        def wrapped(
            *args: Any, __original: Callable[..., Any] = original, **kwargs: Any
        ) -> Any:
            result = __original(*args, **kwargs)
            if next(counter) == n:
                raise _InjectedError
            return result

        monkeypatch.setattr(owner, name, wrapped)
