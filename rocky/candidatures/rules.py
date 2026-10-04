"""Rules of the applications (D1): pure functions, without SQL nor side effect."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from rocky.candidatures.model import (
    DEFER_DAYS,
    FORWARD,
    ISSUES,
    PROPOSALS,
    Change,
    ChangeKind,
    Dossier,
    InvalidChangeError,
    LetterState,
    NextAction,
    Stage,
)

# The changes that set the next action: a creation and a stage change set it too (None: no action).
_SETS_ACTION = frozenset({ChangeKind.CREATED, ChangeKind.STAGE, ChangeKind.NEXT_ACTION})


def standing(rows: Iterable[Change]) -> list[Change]:
    """The changes not cancelled, in the order they were made."""
    ordered = sorted(rows, key=lambda row: row.id)
    cancelled = {row.cancels for row in ordered if row.kind is ChangeKind.CANCELLATION}
    return [
        row
        for row in ordered
        if row.kind is not ChangeKind.CANCELLATION and row.id not in cancelled
    ]


def dossier(rows: Iterable[Change]) -> Dossier:
    """The stage and the next action in force: those of the latest changes not cancelled.

    « Annuler » always cancels the latest change in force (``to_cancel``): a cancelled creation has no later change in
    force, and a new creation opens the application again (Q7).
    """
    changes = standing(rows)
    creation = next(
        (row for row in reversed(changes) if row.kind is ChangeKind.CREATED), None
    )
    stage = next((row.stage for row in reversed(changes) if row.stage), None)
    setter = next((row for row in reversed(changes) if row.kind in _SETS_ACTION), None)
    return Dossier(
        open=creation is not None,
        stage=stage if creation is not None else None,
        next_action=setter.next_action
        if setter is not None and creation is not None
        else None,
        creation=creation,
    )


def to_cancel(rows: Iterable[Change]) -> Change | None:
    """The change that « Annuler » cancels: the latest one of the application still in force (Q6)."""
    changes = standing(rows)
    return changes[-1] if changes else None


def proposal(stage: Stage, today: date) -> tuple[str, date | None] | None:
    """The next action proposed on reaching ``stage`` (Q3): its label and its date (None: a date to enter); None for
    an outcome."""
    proposed = PROPOSALS.get(stage)
    if proposed is None:
        return None
    due = None if proposed.days is None else today + timedelta(days=proposed.days)
    return proposed.label, due


def make_next_action(label: str | None, due: date | None) -> NextAction | None:
    """A next action as entered: both fields, or neither (no action)."""
    text = (label or "").strip()
    if not text and due is None:
        return None
    if not text:
        raise InvalidChangeError("Indique la prochaine action.")
    if due is None:
        raise InvalidChangeError("Indique la date de la prochaine action.")
    return NextAction(text, due)


def deferred(action: NextAction, days: int, today: date) -> NextAction:
    """The action put off by ``days``, from its date or from today when it is overdue (Q3)."""
    if days not in DEFER_DAYS:
        raise InvalidChangeError("Report inconnu.")
    return NextAction(action.label, max(action.due, today) + timedelta(days=days))


def is_overdue(action: NextAction | None, today: date) -> bool:
    return action is not None and action.due < today


def automatic_transition_allowed(current: Stage, proposed: Stage) -> bool:
    """Whether a rule or the AI (messages, E4) may move an application from ``current`` to ``proposed`` (Q5).

    Never backwards, never out of an outcome; the user moves freely.
    """
    if current in ISSUES:
        return False
    if proposed in ISSUES:
        return True
    return FORWARD.index(proposed) > FORWARD.index(current)


# The journey of the application's page (decision D3, Q25; D4, Q16): 1. CV, 2. Letter, 3. Sending.


class Step(StrEnum):
    CV = "cv"
    LETTER = "lettre"
    SEND = "envoi"


@dataclass(frozen=True)
class Journey:
    """Where the application stands on its page: the step to work on, the steps done, sent or closed."""

    current: Step | None  # None once sent, or closed
    done: frozenset[Step]
    sent: bool
    closed: bool  # an outcome reached, or the creation cancelled


_SENT_OR_BEYOND = frozenset(
    {Stage.SENT, Stage.IN_DISCUSSION, Stage.INTERVIEW, Stage.OFFER}
)


def journey(stage: Stage | None, letter: LetterState = LetterState.NONE) -> Journey:
    """``stage``: the stage in force, None for an application whose creation is cancelled. The letter is done once
    one is validated or « Pas de lettre » chosen (D4, Q16); « Lettre prête » or « Pas de lettre » then leads to
    « Prête à envoyer ». An application made ready before D4 shows its letter not done."""
    if stage is None or stage in ISSUES:
        return Journey(None, frozenset(), sent=False, closed=True)
    letter_done = (
        frozenset({Step.LETTER}) if letter is not LetterState.NONE else frozenset()
    )
    if stage is Stage.PREPARING:
        if letter is LetterState.NONE:
            return Journey(Step.CV, frozenset(), sent=False, closed=False)
        return Journey(
            Step.LETTER, frozenset({Step.CV}) | letter_done, sent=False, closed=False
        )
    if stage in _SENT_OR_BEYOND:
        return Journey(
            None, frozenset({Step.CV, Step.SEND}) | letter_done, sent=True, closed=False
        )
    return Journey(
        Step.SEND, frozenset({Step.CV}) | letter_done, sent=False, closed=False
    )
