from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rocky.offres.decisions import (
    APPLICATION_STARTED,
    MAX_REASON_KEYS,
    OTHER,
    OTHER_KEY,
    REASONS,
    Decision,
    DecisionKind,
    DecisionRow,
    DecisionValue,
    InvalidDecisionError,
    application_decision,
    effective_decisions,
    make_decision,
    reason_key,
    reason_label,
    to_cancel,
)

AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def test_a_decision_keeps_its_reasons_once_and_in_order() -> None:
    decision = make_decision("rejected", ["too_senior", "location", "too_senior"])

    assert decision == Decision(DecisionValue.REJECTED, ("too_senior", "location"))


@pytest.mark.parametrize(
    ("value", "reasons", "note", "message"),
    [
        ("maybe", ["location"], None, "Décision inconnue"),
        ("rejected", [], None, "au moins un motif"),
        ("interested", ["too_senior"], None, "Motif inconnu"),
        ("later", ["other"], "   ", "Précise"),
    ],
)
def test_invalid_decisions_are_refused(
    value: str, reasons: list[str], note: str | None, message: str
) -> None:
    with pytest.raises(InvalidDecisionError, match=message):
        make_decision(value, reasons, note)


def test_other_needs_a_note_which_is_kept_trimmed() -> None:
    decision = make_decision("interested", ["other"], "  équipe très sympa ")

    assert decision.note == "équipe très sympa"


def test_every_decision_offers_other_last_and_one_key_per_reason() -> None:
    for value, reasons in REASONS.items():
        codes = [reason.code for reason in reasons]
        assert codes[-1] == OTHER
        # Keys 1–9 by rank, 0 for "other" (C7, Q10).
        assert len(codes) - 1 <= MAX_REASON_KEYS, value
        assert len(set(codes)) == len(codes)
        assert all(code.isascii() and code == code.lower() for code in codes)
        keys = [reason_key(code, rank) for rank, code in enumerate(codes, start=1)]
        assert keys[-1] == OTHER_KEY and len(set(keys)) == len(keys)


def test_rejection_reasons_follow_the_c5_annotations() -> None:
    codes = [reason.code for reason in REASONS[DecisionValue.REJECTED]]

    assert {"too_senior", "sector", "blocking_condition"} <= set(codes)
    assert "too_junior" not in codes


def decided(row_id: int, offer_id: int, value: DecisionValue) -> DecisionRow:
    return DecisionRow(
        row_id, offer_id, DecisionKind.DECISION, AT, Decision(value, ("other",), "x")
    )


def cancelled(row_id: int, offer_id: int, target: int) -> DecisionRow:
    return DecisionRow(row_id, offer_id, DecisionKind.CANCELLATION, AT, cancels=target)


def test_the_latest_decision_of_an_offer_is_in_force() -> None:
    rows = [
        decided(1, 10, DecisionValue.LATER),
        decided(2, 20, DecisionValue.REJECTED),
        decided(3, 10, DecisionValue.INTERESTED),
    ]

    effective = effective_decisions(rows)

    assert {offer: row.id for offer, row in effective.items()} == {10: 3, 20: 2}


def test_cancelling_a_change_brings_the_previous_decision_back() -> None:
    rows = [
        decided(1, 10, DecisionValue.LATER),
        decided(2, 10, DecisionValue.INTERESTED),
        cancelled(3, 10, 2),
    ]

    assert effective_decisions(rows)[10].id == 1
    assert to_cancel(rows) == rows[0]


def test_cancelling_again_goes_further_back_until_nothing_is_left() -> None:
    rows = [decided(1, 10, DecisionValue.LATER), decided(2, 20, DecisionValue.LATER)]

    assert to_cancel(rows) == rows[1]
    rows.append(cancelled(3, 20, 2))
    assert to_cancel(rows) == rows[0]
    rows.append(cancelled(4, 10, 1))
    assert to_cancel(rows) is None
    assert effective_decisions(rows) == {}


def test_labels_are_french_display_only() -> None:
    assert reason_label(DecisionValue.REJECTED, "too_senior") == "trop senior"


def test_preparing_an_application_adds_its_automatic_reason_first() -> None:
    decision = application_decision(["skills_match", "target_job"])

    assert decision == Decision(
        DecisionValue.INTERESTED, (APPLICATION_STARTED, "skills_match", "target_job")
    )
    assert reason_label(DecisionValue.INTERESTED, APPLICATION_STARTED) == (
        "candidature préparée"
    )


def test_preparing_an_application_needs_a_chosen_reason() -> None:
    with pytest.raises(InvalidDecisionError):
        application_decision([])
    with pytest.raises(InvalidDecisionError):
        application_decision(["other"])
    # The automatic reason is never ticked: the triage panel and its keys do not change (D1, Q8).
    with pytest.raises(InvalidDecisionError):
        application_decision([APPLICATION_STARTED])
    assert APPLICATION_STARTED not in {
        reason.code for reasons in REASONS.values() for reason in reasons
    }
