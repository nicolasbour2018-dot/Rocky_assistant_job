from __future__ import annotations

import pytest

from rocky.offres.decisions import (
    OTHER,
    REASONS,
    Decision,
    DecisionValue,
    InvalidDecisionError,
    make_decision,
    reason_label,
)


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


def test_every_decision_offers_other_and_at_most_nine_reasons() -> None:
    for value, reasons in REASONS.items():
        codes = [reason.code for reason in reasons]
        assert codes[-1] == OTHER
        assert len(codes) <= 9, value  # one digit key per reason
        assert len(set(codes)) == len(codes)
        assert all(code.isascii() and code == code.lower() for code in codes)


def test_labels_are_french_display_only() -> None:
    assert reason_label(DecisionValue.REJECTED, "too_senior") == "trop senior"
