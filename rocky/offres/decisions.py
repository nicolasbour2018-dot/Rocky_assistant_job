"""Decisions on offers and their reasons (decisions B4 and C7).

Only the English codes are stored: a decision is the label of the future training dataset (D14, C7 Q1). French
labels exist for display only, so rewording a label never changes the data. Error messages are shown to the user
(French).

Decisions are appended, never changed (C7, Q8): a new decision on an offer replaces the previous one, and a
cancellation appends a row that cancels one decision. ``effective_decisions`` gives what is in force.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

OTHER = "other"
# Set by « Préparer la candidature » (D1, Q8), never ticked in the triage panel.
APPLICATION_STARTED = "application_started"
# Set by « Créer la candidature » from a message (decision E4, Q4, Q12): the user applied outside Rocky.
APPLIED_OUTSIDE = "applied_outside"
# Keyboard key of "other" in the reasons panel; the other reasons take 1–9 by rank.
OTHER_KEY = "0"
MAX_REASON_KEYS = 9


class DecisionValue(StrEnum):
    INTERESTED = "interested"
    REJECTED = "rejected"
    LATER = "later"


class DecisionKind(StrEnum):
    DECISION = "decision"
    CANCELLATION = "cancellation"


class Author(StrEnum):
    """Who decided (plan §3). Only the user decides in C7 (Q2); rules and the AI may later."""

    USER = "user"
    RULE = "rule"
    AI = "ai"


DECISION_LABELS = {
    DecisionValue.INTERESTED: "Intéressé",
    DecisionValue.REJECTED: "Écarté",
    DecisionValue.LATER: "Plus tard",
}
# Keyboard key of each decision in the triage screen.
DECISION_KEYS = {
    DecisionValue.INTERESTED: "i",
    DecisionValue.REJECTED: "e",
    DecisionValue.LATER: "p",
}
REASON_QUESTIONS = {
    DecisionValue.INTERESTED: "Pourquoi intéressé ?",
    DecisionValue.REJECTED: "Pourquoi écartée ?",
    DecisionValue.LATER: "Pourquoi plus tard ?",
}


@dataclass(frozen=True)
class Reason:
    code: str
    label: str


# C7, Q10: the reasons most given in the C5 annotations (seniority, sector, blocking condition) are rejection reasons.
REASONS: dict[DecisionValue, tuple[Reason, ...]] = {
    DecisionValue.INTERESTED: (
        Reason("target_job", "métier visé"),
        Reason("skills_match", "compétences alignées"),
        Reason("company_appeal", "entreprise ou secteur attirant"),
        Reason("location", "lieu ou télétravail"),
        Reason("salary", "salaire"),
        Reason("growth", "évolution ou apprentissage"),
        Reason(OTHER, "autre"),
    ),
    DecisionValue.REJECTED: (
        Reason("not_the_job", "pas le métier"),
        Reason("too_senior", "trop senior"),
        Reason("missing_skills", "compétences manquantes"),
        Reason("sector", "secteur ou domaine"),
        Reason("company", "entreprise"),
        Reason("location", "lieu ou télétravail"),
        Reason("contract", "contrat"),
        Reason("salary", "salaire"),
        Reason("blocking_condition", "condition bloquante (visa, langue, permis…)"),
        Reason(OTHER, "autre"),
    ),
    DecisionValue.LATER: (
        Reason("reread", "à relire à tête reposée"),
        Reason("missing_info", "infos manquantes"),
        Reason("application_to_prepare", "candidature à préparer"),
        Reason("distant_deadline", "date limite lointaine"),
        Reason(OTHER, "autre"),
    ),
}


# Reasons that a gesture sets by itself: known to the labels, absent from the panels (their keys 1–9 never move).
AUTOMATIC_REASONS: dict[DecisionValue, tuple[Reason, ...]] = {
    DecisionValue.INTERESTED: (
        Reason(APPLICATION_STARTED, "candidature préparée"),
        Reason(APPLIED_OUTSIDE, "candidature faite hors de Rocky"),
    ),
}


class InvalidDecisionError(ValueError):
    """The decision cannot be recorded as given; the message is shown to the user."""


@dataclass(frozen=True)
class Decision:
    value: DecisionValue
    reasons: tuple[str, ...]
    note: str | None = None


@dataclass(frozen=True)
class DecisionRow:
    """One stored row: a decision, or the cancellation of the decision ``cancels``."""

    id: int
    offer_id: int
    kind: DecisionKind
    decided_at: datetime
    decision: Decision | None = None
    cancels: int | None = None


def reason_label(value: DecisionValue, code: str) -> str:
    reasons = (*REASONS[value], *AUTOMATIC_REASONS.get(value, ()))
    return next(reason.label for reason in reasons if reason.code == code)


def reason_key(code: str, rank: int) -> str:
    """The key that ticks a reason: its rank (1–9), "0" for "other"."""
    return OTHER_KEY if code == OTHER else str(rank)


def make_decision(
    value: str, reasons: Iterable[str], note: str | None = None
) -> Decision:
    """A valid decision: known value, at least one reason of that value, a note when "other" is chosen."""
    try:
        decision_value = DecisionValue(value)
    except ValueError as error:
        raise InvalidDecisionError("Décision inconnue.") from error
    allowed = {reason.code for reason in REASONS[decision_value]}
    codes = tuple(dict.fromkeys(reasons))
    if not codes:
        raise InvalidDecisionError("Choisis au moins un motif.")
    if any(code not in allowed for code in codes):
        raise InvalidDecisionError("Motif inconnu pour cette décision.")
    text = (note or "").strip() or None
    if OTHER in codes and text is None:
        raise InvalidDecisionError("Précise le motif « autre ».")
    return Decision(decision_value, codes, text)


def application_decision(reasons: Iterable[str], note: str | None = None) -> Decision:
    """« Intéressé » written by « Préparer la candidature » (D1, Q8): the reasons chosen (at least one, as in the
    triage), led by ``application_started``."""
    chosen = make_decision(DecisionValue.INTERESTED, reasons, note)
    return Decision(chosen.value, (APPLICATION_STARTED, *chosen.reasons), chosen.note)


def outside_decision() -> Decision:
    """« Intéressé » written by « Créer la candidature » from a message (decision E4, Q12): the user applied already,
    outside Rocky; no reason is asked."""
    return Decision(DecisionValue.INTERESTED, (APPLIED_OUTSIDE,))


def _standing(rows: Iterable[DecisionRow]) -> list[DecisionRow]:
    """Decisions not cancelled, in the order they were made."""
    ordered = sorted(rows, key=lambda row: row.id)
    cancelled = {
        row.cancels for row in ordered if row.kind is DecisionKind.CANCELLATION
    }
    return [
        row
        for row in ordered
        if row.kind is DecisionKind.DECISION and row.id not in cancelled
    ]


def effective_decisions(rows: Iterable[DecisionRow]) -> dict[int, DecisionRow]:
    """The decision in force for each offer: its latest decision not cancelled (Q8).

    Cancelling a change brings the previous decision back; cancelling the only one leaves the offer to examine.
    """
    return {row.offer_id: row for row in _standing(rows)}


def to_cancel(rows: Iterable[DecisionRow]) -> DecisionRow | None:
    """The decision that « Annuler » cancels: the latest decision of the account not cancelled yet (Q8)."""
    standing = _standing(rows)
    return standing[-1] if standing else None
