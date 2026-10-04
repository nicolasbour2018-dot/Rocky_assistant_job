"""The classification on PostgreSQL (E2): every decision has its proof and its event, a message is decided once, the
language model is called within the limits and its failure decides nothing (Q12, Q13, Q18)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from rocky.candidatures import web as candidatures_web
from rocky.candidatures.model import MailTarget
from rocky.messages.classification import usecases
from rocky.messages.classification.model import (
    CLASSIFY_VERSION,
    Category,
    Level,
    Limits,
    View,
)
from rocky.messages.classification.usecases import (
    DAY_LIMIT_REASON,
    DEFAULT_LIMITS,
    HOUR_LIMIT_REASON,
    RUN_LIMIT_REASON,
    WITHOUT_MODEL_REASON,
    ClassifyBusyError,
    ClassifyReport,
    classify_messages,
)
from rocky.messages.sql import SqlStorage, mail_model_calls, message_decisions
from rocky.messages.usecases import connect_mailbox
from rocky.offres.decisions import Author
from rocky.system.events import events
from rocky.system.llm import JsonModel, LlmUnavailableError
from tests.messages.fakes import (
    NOW,
    ScriptedModel,
    cipher,
    sent_application,
    store_mail,
)
from tests.offres.fakes import new_seeker

FRENCH_BEE_REFUSAL = (
    "Bonjour, nous revenons vers vous concernant votre candidature au poste de Data Analyst - Data Steward H/F. "
    "Après une étude approfondie, nous vous informons que celle-ci n'a malheureusement pas été retenue."
)
UNCLEAR = "Hello Camille, I wanted to provide you with another quick update regarding your application."


@dataclass
class Box:
    engine: Engine
    storage: SqlStorage
    account_id: int
    mailbox_id: int
    french_bee: int

    def targets(self, account_id: int) -> Sequence[MailTarget]:
        with self.engine.connect() as connection:
            return candidatures_web.mail_targets(connection, account_id)

    def run(
        self,
        model: JsonModel | None = None,
        *,
        limits: Limits = DEFAULT_LIMITS,
        max_calls: int | None = None,
        again: bool = False,
        minutes: int = 0,
    ) -> ClassifyReport:
        return classify_messages(
            self.storage,
            account_id=self.account_id,
            targets=self.targets,
            model=model,
            clock=lambda: NOW + timedelta(minutes=minutes),
            limits=limits,
            max_calls=max_calls,
            again=again,
        )

    def decisions(self) -> list[dict[str, object]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(message_decisions)
                .where(message_decisions.c.account_id == self.account_id)
                .order_by(message_decisions.c.id)
            )
            return [dict(row._mapping) for row in rows]

    def calls(self) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(mail_model_calls.c.outcome)
                    .where(mail_model_calls.c.account_id == self.account_id)
                    .order_by(mail_model_calls.c.id)
                ).scalars()
            )

    def mail(
        self,
        sender: str,
        subject: str,
        body: str = "",
        *,
        thread: str | None = None,
        received_at: datetime = NOW,
    ) -> int:
        return store_mail(
            self.storage,
            self.mailbox_id,
            sender=sender,
            subject=subject,
            body=body,
            thread=thread,
            received_at=received_at,
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
    storage = SqlStorage(migrated_engine)
    mailbox_id, _ = connect_mailbox(
        storage,
        cipher(),
        account_id=seeker.account_id,
        address="camille@example.com",
        refresh_token="1//rafraichissement",
        now=NOW,
    )
    return Box(migrated_engine, storage, seeker.account_id, mailbox_id, french_bee)


def answer(category: str, excerpt: str, application: str = "") -> dict[str, str]:
    return {
        "categorie": category,
        "candidature": application,
        "extrait": excerpt,
        "raison": "Lu dans le message.",
    }


# Exit criterion: every decision has a readable proof, the Quora digest goes nowhere.


def test_every_decision_has_its_proof_and_its_event(box: Box) -> None:
    quora = box.mail(
        '"Sélection Quora" <french-personalized-digest@quora.com>',
        "Pourquoi la France ?",
        "Une réponse sur Quora.",
    )
    refusal = box.mail(
        "Recrutment department - French Bee <message@beetween-software.com>",
        "French Bee - RETOUR CANDIDATURE AU POSTE DE Data Analyst - Data Steward H/F",
        FRENCH_BEE_REFUSAL,
    )

    report = box.run()

    assert report.by_rules == 2 and report.waiting == 0
    by_message = {row["message_id"]: row for row in box.decisions()}
    assert (by_message[quora]["category"], by_message[quora]["application_id"]) == (
        "unrelated",
        None,
    )
    assert (by_message[refusal]["category"], by_message[refusal]["application_id"]) == (
        "rejection",
        box.french_bee,
    )
    for row in by_message.values():
        assert row["rule"] and row["excerpt"] and row["proofs"]
        assert row["classify_version"] == CLASSIFY_VERSION
        assert all(proof["reason"] and proof["excerpt"] for proof in row["proofs"])  # type: ignore[attr-defined]
    with box.engine.connect() as connection:
        written = connection.execute(
            select(events.c.subject_id, events.c.actor).where(
                events.c.type == "messages.message_classified"
            )
        ).all()
    assert {(int(subject), actor) for subject, actor in written} >= {
        (quora, "rule"),
        (refusal, "rule"),
    }


def test_the_base_refuses_a_decision_without_proof(box: Box) -> None:
    message_id = box.mail("Exemple <rh@exemple.fr>", "Objet")
    base = {
        "message_id": message_id,
        "account_id": box.account_id,
        "category": "rejection",
        "level": "medium",
        "author": "rule",
        "rule": "phrase.rejection",
        "excerpt": "Votre candidature n'est pas retenue.",
        "proofs": [
            {
                "tier": "phrase",
                "rule": "phrase.rejection",
                "excerpt": "x",
                "reason": "y",
            }
        ],
        "classify_version": CLASSIFY_VERSION,
        "decided_at": NOW,
    }
    breakages: list[dict[str, object]] = [
        {"excerpt": ""},
        {"rule": ""},
        {"proofs": []},
        {"category": None},  # nothing decided is never of medium level
    ]
    for broken in breakages:
        with pytest.raises(IntegrityError), box.engine.begin() as connection:
            connection.execute(insert(message_decisions).values(**{**base, **broken}))


def test_a_message_is_decided_once(box: Box) -> None:
    box.mail("GitHub <noreply@github.com>", "[GitHub] Security alert")

    first, second = box.run(), box.run()

    assert (first.by_rules, second.by_rules) == (1, 0)
    assert len(box.decisions()) == 1


# The language model (Q12, Q18).


def test_without_a_model_the_message_waits_with_its_reason(box: Box) -> None:
    message_id = box.mail(
        "Thales Group <recruiting@jobalerts.thalesgroup.com>",
        "Application Update",
        UNCLEAR,
    )

    report = box.run()

    assert (report.by_rules, report.waiting, report.reason) == (
        0,
        1,
        WITHOUT_MODEL_REASON,
    )
    assert box.decisions() == []
    with box.storage.transaction() as store:
        assert store.waiting(box.account_id) == 1
        assert [
            m.id for m in store.sorted_messages(box.account_id, View.WAITING, 10)
        ] == [message_id]


def test_the_model_decides_what_the_rules_leave(box: Box) -> None:
    box.mail(
        "Thales Group <recruiting@jobalerts.thalesgroup.com>",
        "Application Update",
        UNCLEAR,
    )
    model = ScriptedModel(
        answer("employer_update", "another quick update regarding your application")
    )

    report = box.run(model)

    assert (report.by_model, report.calls, report.waiting) == (1, 1, 0)
    [decision] = box.decisions()
    assert (decision["category"], decision["author"], decision["level"]) == (
        "employer_update",
        "ai",
        "medium",
    )
    assert decision["rule"] == "model"
    assert box.calls() == ["accepted"]
    assert "Candidatures envoyées" in model.prompts[0]


def test_a_refused_answer_is_a_decision_to_check(box: Box) -> None:
    box.mail(
        "Thales Group <recruiting@jobalerts.thalesgroup.com>",
        "Application Update",
        UNCLEAR,
    )

    box.run(
        ScriptedModel(
            answer("rejection", "Nous ne donnerons pas suite à votre candidature.")
        )
    )

    [decision] = box.decisions()
    assert (decision["category"], decision["level"]) == (None, "low")
    assert box.calls() == ["refused"]


def test_a_failure_decides_nothing_and_ends_the_pass(box: Box) -> None:
    for subject in ("Application Update", "Another update"):
        box.mail(
            "Thales Group <recruiting@jobalerts.thalesgroup.com>", subject, UNCLEAR
        )
    model = ScriptedModel(LlmUnavailableError("Gemini ne répond pas (délai dépassé)."))

    report = box.run(model)

    assert box.decisions() == []
    assert box.calls() == ["failed"]  # one call, never one per message
    assert (report.waiting, report.reason) == (
        2,
        "Gemini ne répond pas (délai dépassé).",
    )
    with box.storage.transaction() as store:
        assert (
            store.last_failure(box.account_id, NOW - timedelta(days=1)) == report.reason
        )


def test_the_limits_of_the_account_bound_the_calls(box: Box) -> None:
    for subject in ("Update 1", "Update 2", "Update 3"):
        box.mail(
            "Thales Group <recruiting@jobalerts.thalesgroup.com>", subject, UNCLEAR
        )
    model = ScriptedModel(
        answer("employer_update", "another quick update regarding your application")
    )
    limits = Limits(per_hour=1, per_day=2)

    first = box.run(model, limits=limits)
    same_hour = box.run(model, limits=limits, minutes=10)
    next_hour = box.run(model, limits=limits, minutes=70)
    next_day_too_soon = box.run(model, limits=limits, minutes=140)

    assert (first.calls, first.waiting, first.reason) == (1, 2, HOUR_LIMIT_REASON)
    assert (same_hour.calls, same_hour.reason) == (0, HOUR_LIMIT_REASON)
    assert (next_hour.calls, next_hour.waiting) == (1, 1)
    assert (next_day_too_soon.calls, next_day_too_soon.reason) == (0, DAY_LIMIT_REASON)
    assert len(box.calls()) == 2


def test_a_pass_can_bound_its_own_calls(box: Box) -> None:
    box.mail(
        "Thales Group <recruiting@jobalerts.thalesgroup.com>",
        "Application Update",
        UNCLEAR,
    )

    report = box.run(ScriptedModel(answer("rejection", "x" * 20)), max_calls=0)

    assert (report.calls, report.reason) == (0, RUN_LIMIT_REASON)


# Threads, classifying again, the lock.


def test_a_reply_in_the_thread_follows_its_application(box: Box) -> None:
    box.mail(
        "Recrutment department - French Bee <message@beetween-software.com>",
        "French Bee - RETOUR CANDIDATURE AU POSTE DE Data Analyst - Data Steward H/F",
        FRENCH_BEE_REFUSAL,
        thread="fil-1",
    )
    later = box.mail(
        "Jeanne <jeanne.recrute@gmail.com>",
        "Re: RETOUR CANDIDATURE",
        "Je vous propose un échange téléphonique la semaine prochaine.",
        thread="fil-1",
        received_at=NOW + timedelta(hours=2),
    )

    box.run()

    reply = next(row for row in box.decisions() if row["message_id"] == later)
    assert (reply["category"], reply["application_id"], reply["level"]) == (
        "interview",
        box.french_bee,
        "high",
    )


def test_classifying_again_appends_and_never_overwrites_the_user(box: Box) -> None:
    ruled = box.mail("GitHub <noreply@github.com>", "[GitHub] Security alert")
    by_user = box.mail("Exemple <rh@exemple.fr>", "Bonjour")
    box.run()
    with box.engine.begin() as connection:
        connection.execute(
            insert(message_decisions).values(
                message_id=by_user,
                account_id=box.account_id,
                category=Category.RECRUITER_APPROACH.value,
                level=Level.HIGH.value,
                author=Author.USER.value,
                rule="user",
                excerpt="Bonjour",
                proofs=[
                    {
                        "tier": "sender",
                        "rule": "user",
                        "excerpt": "Bonjour",
                        "reason": "Corrigé.",
                    }
                ],
                classify_version=CLASSIFY_VERSION,
                decided_at=NOW,
            )
        )

    again = box.run(again=True)

    assert again.by_rules == 1
    rows = box.decisions()
    assert [row["message_id"] for row in rows].count(ruled) == 2
    assert rows[-1]["message_id"] == ruled
    with box.storage.transaction() as store:
        assert store.current_author(by_user) is Author.USER


def test_two_passes_never_run_together(box: Box) -> None:
    with box.storage.classify_lock(box.account_id) as locked:
        assert locked
        with pytest.raises(ClassifyBusyError):
            box.run()


def test_a_pass_reads_every_batch(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance of E2: past one batch of messages, a pass still reads them all."""
    monkeypatch.setattr(usecases, "BATCH", 2)
    for subject in ("Alerte 1", "Alerte 2", "Alerte 3"):
        box.mail("GitHub <noreply@github.com>", subject)

    report = box.run()
    again = box.run(again=True)

    assert (report.by_rules, again.by_rules) == (3, 3)


def test_the_default_view_holds_what_asks_to_be_read(box: Box) -> None:
    """Q19, Q20: the acknowledgements and the platform's notices leave « À regarder », but « Finalisez… »."""
    refusal = box.mail(
        "Recrutement <rh@exemple.fr>",
        "Votre candidature",
        "Nous ne donnerons pas suite à votre candidature.",
    )
    acknowledged = box.mail(
        "Hellowork Candidature <contact@emails.hellowork.com>",
        "Votre candidature est arrivée chez GEODIS",
    )
    to_finish = box.mail(
        "Hellowork Candidature <contact@emails.hellowork.com>",
        "Finalisez votre candidature sur le site de Valeo",
    )
    closed = box.mail(
        "Hellowork <emploi@emails.hellowork.com>",
        "L'offre de Data Analyst Financier H/F n'est plus disponible",
    )
    box.run()

    def shown(view: View) -> set[int]:
        with box.storage.transaction() as store:
            return {
                message.id
                for message in store.sorted_messages(box.account_id, view, 50)
            }

    assert shown(View.TO_LOOK_AT) == {refusal, to_finish}
    assert shown(View.ACKNOWLEDGEMENTS) == {acknowledged}
    assert shown(View.PLATFORM) == {to_finish, closed}
    with box.storage.transaction() as store:
        assert store.acknowledgements(box.account_id) == 1
