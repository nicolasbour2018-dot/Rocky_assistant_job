"""Use cases of the applications (D1): prepare, change the stage or the next action, cancel the latest change.

Each use case runs inside one transaction opened by the caller (the stores never commit), and locks the application
first: a change, its event and the decision on the offer it goes with are written together or not at all (exit
criterion of D1). Decision ``docs/decisions/D1-dossier-statuts.md``.
"""

from __future__ import annotations

from datetime import date, datetime

from rocky.candidatures.model import (
    Application,
    ApplicationStore,
    Change,
    ChangeKind,
    Dossier,
    InvalidChangeError,
    NewChange,
    NextAction,
    OfferDecisions,
    Stage,
)
from rocky.candidatures.rules import (
    automatic_transition_allowed,
    deferred,
    dossier,
    proposal,
    to_cancel,
)
from rocky.offres.decisions import Author, Decision, DecisionValue
from rocky.system.events import Actor, JsonValue, NewEvent

REJECTED_OFFER = "Cette offre est écartée : change d'abord ta décision pour préparer une candidature."
REASONS_NEEDED = "Choisis au moins un motif d'intérêt."


def needs_reasons(in_force: DecisionValue | None) -> bool:
    """« Préparer » writes « Intéressé » with reasons unless the offer is already « Intéressé » (Q8)."""
    return in_force is not DecisionValue.INTERESTED


def prepare_application(
    store: ApplicationStore,
    offers: OfferDecisions,
    *,
    account_id: int,
    offer_id: int,
    interest: Decision | None,
    now: datetime,
    today: date,
) -> int:
    """« Préparer la candidature » (Q2, Q8): opens the application of the offer, « En préparation », with the proposed
    next action; idempotent (an open application is returned as it is).

    On an offer without decision or « Plus tard », ``interest`` (``application_decision``) is recorded with it; an
    offer « Écarté » is refused.
    """
    in_force = offers.decision_in_force(account_id, offer_id)
    if in_force is DecisionValue.REJECTED:
        raise InvalidChangeError(REJECTED_OFFER)
    application = store.application_for_offer(account_id, offer_id, now)
    if dossier(store.changes(application.id)).open:
        return application.id
    decision_id = None
    if needs_reasons(in_force):
        if interest is None:
            raise InvalidChangeError(REASONS_NEEDED)
        decision_id = offers.record_interested(account_id, offer_id, interest, now)
    next_action = _proposed(Stage.PREPARING, today)
    store.insert_change(
        account_id,
        application.id,
        NewChange(
            ChangeKind.CREATED,
            stage=Stage.PREPARING,
            next_action=next_action,
            decision_id=decision_id,
        ),
        author=Author.USER,
        now=now,
    )
    _event(
        store,
        application,
        "candidatures.application_created",
        Author.USER,
        {
            "offer_id": offer_id,
            "stage": Stage.PREPARING.value,
            "next_action": _action_json(next_action),
            "decision_id": decision_id,
        },
    )
    return application.id


def change_stage(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    stage: Stage,
    next_action: NextAction | None,
    now: datetime,
    author: Author = Author.USER,
) -> bool:
    """Move the application to ``stage`` with ``next_action`` (the proposal, as the user left it).

    The user moves freely (Q5); a rule or the AI never goes backwards nor out of an outcome. False when the application
    is already at that stage (nothing written).
    """
    application, current = _open(store, account_id, application_id)
    previous = current.stage
    if previous is None:
        raise LookupError(f"application {application_id} has no stage")
    if stage is previous:
        return False
    if author is not Author.USER and not automatic_transition_allowed(previous, stage):
        raise InvalidChangeError("Cette transition automatique n'est pas permise.")
    store.insert_change(
        account_id,
        application.id,
        NewChange(ChangeKind.STAGE, stage=stage, next_action=next_action),
        author=author,
        now=now,
    )
    _event(
        store,
        application,
        "candidatures.stage_changed",
        author,
        {
            "from": previous.value,
            "to": stage.value,
            "next_action": _action_json(next_action),
        },
    )
    return True


def set_next_action(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    next_action: NextAction | None,
    now: datetime,
    deferred_days: int | None = None,
) -> bool:
    """Set (or clear, with None) the next action (Q3). False when it is unchanged (nothing written)."""
    application, current = _open(store, account_id, application_id)
    if next_action == current.next_action:
        return False
    store.insert_change(
        account_id,
        application.id,
        NewChange(ChangeKind.NEXT_ACTION, next_action=next_action),
        author=Author.USER,
        now=now,
    )
    _event(
        store,
        application,
        "candidatures.next_action_set",
        Author.USER,
        {
            "next_action": _action_json(next_action),
            "previous": _action_json(current.next_action),
            "deferred_days": deferred_days,
        },
    )
    return True


def defer_next_action(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    days: int,
    now: datetime,
    today: date,
) -> bool:
    """« Différer » the next action by ``days`` (1, 3 or 7; from today when it is overdue)."""
    _, current = _open(store, account_id, application_id)
    if current.next_action is None:
        raise InvalidChangeError("Aucune prochaine action à différer.")
    return set_next_action(
        store,
        account_id=account_id,
        application_id=application_id,
        next_action=deferred(current.next_action, days, today),
        now=now,
        deferred_days=days,
    )


def cancel_last_change(
    store: ApplicationStore,
    offers: OfferDecisions,
    *,
    account_id: int,
    application_id: int,
    now: datetime,
) -> Change | None:
    """« Annuler » (Q6): cancels the latest change of the application still in force, with its event; the previous
    stage and next action come back. Cancelling the creation also cancels the « Intéressé » written with it (Q9).

    Returns the cancelled change, or None when nothing is left to cancel.
    """
    application = store.locked_application(account_id, application_id)
    if application is None:
        raise LookupError(f"application {application_id} is not of the account")
    rows = store.changes(application.id)
    target = to_cancel(rows)
    if target is None:
        return None
    cancellation = store.insert_change(
        account_id,
        application.id,
        NewChange(ChangeKind.CANCELLATION, cancels=target.id),
        author=Author.USER,
        now=now,
    )
    decision_cancelled = False
    if target.kind is ChangeKind.CREATED and target.decision_id is not None:
        decision_cancelled = offers.cancel(account_id, target.decision_id, now)
    restored = dossier([*rows, cancellation])
    _event(
        store,
        application,
        "candidatures.change_cancelled",
        Author.USER,
        {
            "change_id": target.id,
            "kind": target.kind.value,
            "open": restored.open,
            "stage": None if restored.stage is None else restored.stage.value,
            "next_action": _action_json(restored.next_action),
            "decision_id": target.decision_id if decision_cancelled else None,
        },
    )
    return target


def _open(
    store: ApplicationStore, account_id: int, application_id: int
) -> tuple[Application, Dossier]:
    application = store.locked_application(account_id, application_id)
    if application is None:
        raise LookupError(f"application {application_id} is not of the account")
    current = dossier(store.changes(application.id))
    if not current.open:
        raise InvalidChangeError("Cette candidature a été annulée.")
    return application, current


def _proposed(stage: Stage, today: date) -> NextAction | None:
    proposed = proposal(stage, today)
    if proposed is None or proposed[1] is None:
        return None
    return NextAction(proposed[0], proposed[1])


def _action_json(action: NextAction | None) -> JsonValue:
    if action is None:
        return None
    return {"label": action.label, "due": action.due.isoformat()}


def _event(
    store: ApplicationStore,
    application: Application,
    type_: str,
    author: Author,
    payload: dict[str, JsonValue],
) -> None:
    store.append_event(
        NewEvent(
            type=type_,
            actor=Actor(author.value),
            subject_type="application",
            subject_id=str(application.id),
            payload=payload,
            account_id=application.account_id,
        )
    )
