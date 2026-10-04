"""The language model's stage (E2, Q9, Q12), without a model: what it reads and how its answer is checked."""

from __future__ import annotations

from datetime import UTC, date, datetime

from rocky.candidatures.model import MailTarget, Stage
from rocky.messages.classification.llm import (
    ALONE_REASON,
    APPLICATION_REASON,
    CONTRADICTION_REASON,
    EXCERPT_REASON,
    INVALID_REASON,
    checked,
    identifiers,
    prompt,
)
from rocky.messages.classification.model import (
    Category,
    Level,
    MailToClassify,
    Pending,
    Proof,
    Tier,
)
from rocky.offres.decisions import Author

MESSAGE = MailToClassify(
    id=5,
    mailbox_id=1,
    thread_id="t5",
    received_at=datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
    sender="French Bee <message@beetween-software.com>",
    sender_address="message@beetween-software.com",
    subject="RETOUR CANDIDATURE AU POSTE DE Data Analyst - Data Steward H/F",
    body_text="Bonjour, après une étude approfondie, celle-ci n'a malheureusement pas été retenue.",
)
TARGETS = (
    MailTarget(
        36,
        "French bee",
        "Data Analyst - Data Steward H/F",
        Stage.SENT,
        date(2026, 9, 1),
        None,
        (),
    ),
    MailTarget(
        41, "Choisir le Service Public", "Data scientist", Stage.SENT, None, None, ()
    ),
)
FINDING = Proof(
    Tier.SIGNAL, "signal.ats", "message@beetween-software.com", "Outil de recrutement."
)
REFUSAL = "celle-ci n'a malheureusement pas été retenue"


def pending(attached: int | None = None, **kwargs: object) -> Pending:
    return Pending(candidates=TARGETS, findings=(FINDING,), attached=attached, **kwargs)  # type: ignore[arg-type]


def answer(
    category: str = "rejection", application: str = "C1", excerpt: str = REFUSAL
) -> dict[str, str]:
    return {
        "categorie": category,
        "candidature": application,
        "extrait": excerpt,
        "raison": "Refus explicite.",
    }


def test_the_model_reads_opaque_identifiers_never_the_applications_ids() -> None:
    text = prompt(MESSAGE, pending())

    assert identifiers(pending()) == {"C1": 36, "C2": 41}
    assert (
        "- C1 : French bee — Data Analyst - Data Steward H/F, envoyée le 01/09/2026"
        in text
    )
    assert "36" not in text.replace("2026", "")
    assert MESSAGE.body_text in text


def test_an_answer_quoting_the_message_is_the_decision() -> None:
    result = checked(answer(), MESSAGE, pending(attached=36))

    assert result.accepted
    verdict = result.verdict
    assert (
        verdict.category,
        verdict.application_id,
        verdict.level,
        verdict.author,
    ) == (
        Category.REJECTION,
        36,
        Level.MEDIUM,
        Author.AI,
    )
    assert verdict.proofs[0].excerpt == REFUSAL
    assert verdict.proofs[-1] == FINDING  # what the rules found stays in the proof


def test_the_quotation_is_compared_without_case_accents_nor_spaces() -> None:
    result = checked(
        answer(excerpt="CELLE-CI  n'a malheureusement pas ete retenue"),
        MESSAGE,
        pending(),
    )

    assert result.accepted


def test_a_quotation_not_in_the_message_is_refused() -> None:
    result = checked(
        answer(excerpt="Nous vous proposons un entretien mardi."),
        MESSAGE,
        pending(attached=36),
    )

    assert not result.accepted
    assert (result.verdict.category, result.verdict.level) == (None, Level.LOW)
    assert result.verdict.application_id == 36  # the rules' attachment stays, to check
    assert result.verdict.proofs[0].reason == EXCERPT_REASON
    # What the model quoted is kept, to see why it was refused.
    assert result.verdict.proofs[1].excerpt == "Nous vous proposons un entretien mardi."


def test_a_too_short_quotation_proves_nothing() -> None:
    assert not checked(answer(excerpt="retenue"), MESSAGE, pending()).accepted


def test_an_application_not_offered_is_refused() -> None:
    result = checked(answer(application="C9"), MESSAGE, pending())

    assert not result.accepted
    assert result.verdict.proofs[0].reason == APPLICATION_REASON


def test_an_answer_of_another_shape_is_refused() -> None:
    result = checked({"categorie": "rejection"}, MESSAGE, pending())

    assert not result.accepted
    assert result.verdict.proofs[0].reason == INVALID_REASON


def test_unknown_is_an_answer_to_check() -> None:
    result = checked(answer(category="unknown", application=""), MESSAGE, pending())

    assert result.accepted
    assert (result.verdict.category, result.verdict.level) == (None, Level.LOW)


def test_the_model_alone_attaching_is_to_check() -> None:
    result = checked(answer(), MESSAGE, pending())

    assert (result.verdict.application_id, result.verdict.level) == (36, Level.LOW)
    assert ALONE_REASON in {proof.reason for proof in result.verdict.proofs}


def test_the_model_against_the_rules_attaches_nothing() -> None:
    result = checked(answer(application="C2"), MESSAGE, pending(attached=36))

    assert (result.verdict.application_id, result.verdict.level) == (None, Level.LOW)
    assert CONTRADICTION_REASON in {proof.reason for proof in result.verdict.proofs}


def test_the_model_against_the_rules_sentence_is_to_check() -> None:
    result = checked(
        answer(), MESSAGE, pending(attached=36, category=Category.ACKNOWLEDGEMENT)
    )

    assert (result.verdict.category, result.verdict.level) == (
        Category.REJECTION,
        Level.LOW,
    )


def test_a_rules_attachment_to_check_stays_to_check_when_the_model_names_none() -> None:
    result = checked(
        answer(application=""), MESSAGE, pending(attached=36, attached_level=Level.LOW)
    )

    assert (result.verdict.application_id, result.verdict.level) == (36, Level.LOW)


def test_the_model_confirming_the_rules_lifts_a_doubt() -> None:
    result = checked(answer(), MESSAGE, pending(attached=36, attached_level=Level.LOW))

    assert (result.verdict.application_id, result.verdict.level) == (36, Level.MEDIUM)
