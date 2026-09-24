"""Decisions on offers and their reasons (decision B4; kept for C7).

Only the English codes are stored: they are the labels of the future training dataset (D14). French labels exist
for display only, so rewording a label never changes the data. Error messages are shown to the user (French).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

OTHER = "other"


class DecisionValue(StrEnum):
    INTERESTED = "interested"
    REJECTED = "rejected"
    LATER = "later"


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
        Reason("too_junior", "trop junior"),
        Reason("missing_skills", "compétences manquantes"),
        Reason("location", "lieu ou télétravail"),
        Reason("contract", "contrat"),
        Reason("salary", "salaire"),
        Reason("company", "entreprise ou secteur"),
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


class InvalidDecisionError(ValueError):
    """The decision cannot be recorded as given; the message is shown to the user."""


@dataclass(frozen=True)
class Decision:
    value: DecisionValue
    reasons: tuple[str, ...]
    note: str | None = None


def reason_label(value: DecisionValue, code: str) -> str:
    return next(reason.label for reason in REASONS[value] if reason.code == code)


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
