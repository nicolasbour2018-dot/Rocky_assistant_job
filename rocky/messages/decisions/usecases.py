"""Use cases of the decisions on the messages (step E4): what follows a decision, the gestures of « Ce qui a bougé »,
the corrections, the rules per sender and « Créer la candidature ».

Decision ``docs/decisions/E4-decisions-ecran.md``. Each use case runs inside one transaction opened by the caller (the
stores never commit): a decision about a message, the transition of its application and their events are written
together or not at all. The message's row is held first, so two gestures on one message run one after the other.
"""

from __future__ import annotations

from datetime import datetime

from rocky.messages.classification.model import (
    Category,
    Level,
    MailToClassify,
    Proof,
    StoredDecision,
    Tier,
    Verdict,
)
from rocky.messages.decisions.model import (
    Corrected,
    DecisionStore,
    Gesture,
    InvalidGestureError,
    MessageRef,
    Offers,
    Outcome,
    Transition,
)
from rocky.messages.decisions.rules import (
    ATTACHABLE,
    domain_offered,
    gmail_link,
    plan_transition,
    quoted,
    rule_offered,
)
from rocky.offres.decisions import Author
from rocky.offres.imports.rules import check_link
from rocky.system.clock import paris_day
from rocky.system.events import Actor, JsonValue, NewEvent

# The rules of the user's decisions (Q6): their proof names the gesture.
CORRECTED_RULE = "user.corrected"
CONFIRMED_RULE = "user.confirmed"
CREATED_RULE = "user.created"

UNKNOWN_MESSAGE = "Ce message n'existe pas."
UNKNOWN_MOVE = "Ce changement n'est plus à traiter."
NOT_PROPOSED = "Ce changement a déjà été appliqué : « Vu » ou « Annuler »."
NOT_APPLIED = "Ce changement n'était qu'une proposition : « Appliquer » ou « Ignorer »."
NOT_LAST = (
    "La candidature a changé depuis : annule ce changement depuis son dossier "
    "(« Annuler le dernier changement »)."
)
UNKNOWN_APPLICATION = "Cette candidature n'existe pas ou a été annulée."
NOTHING_TO_CONFIRM = (
    "Rocky n'a rien décidé pour ce message : choisis sa catégorie avec « Corriger »."
)
COMPANY_NEEDED = "Indique l'employeur."
TITLE_NEEDED = "Indique l'intitulé du poste."
UNKNOWN_RULE = "Cette règle n'existe plus."


def follow_decision(
    store: DecisionStore,
    account_id: int,
    message: MailToClassify,
    decision_id: int,
    verdict: Verdict,
    now: datetime,
) -> None:
    """A decision of the classification was just written: the transition of its application (Q1), in its transaction."""
    _follow(store, account_id, message.id, decision_id, verdict, now)


def _follow(
    store: DecisionStore,
    account_id: int,
    message_id: int,
    decision_id: int,
    verdict: Verdict,
    now: datetime,
) -> int | None:
    """The transition ``verdict`` gives (applied or proposed), recorded with its decision; the earlier proposals of
    the message it does not repeat are replaced. Returns the transition's id (an earlier identical proposal stays and
    is returned), or None."""
    applications = store.applications()
    current = (
        None
        if verdict.application_id is None or verdict.category is None
        else applications.stage(account_id, verdict.application_id)
    )
    plan = (
        None
        if current is None
        else plan_transition(verdict.category, verdict.level, verdict.author, current)
    )
    kept: int | None = None
    for earlier in store.transitions_of_message(message_id):
        if not earlier.pending or earlier.outcome is not Outcome.PROPOSED:
            continue
        if (
            plan is not None
            and plan.outcome is Outcome.PROPOSED
            and earlier.application_id == verdict.application_id
            and earlier.to_stage is plan.stage
        ):
            kept = earlier.id
            continue
        _settle(store, account_id, earlier, Gesture.REPLACED, None, now, Actor.SYSTEM)
    if plan is None or current is None or verdict.application_id is None:
        return None
    if kept is not None:
        return kept
    change_id = None
    if plan.outcome is Outcome.APPLIED:
        change_id = applications.move(
            account_id,
            verdict.application_id,
            plan.stage,
            author=verdict.author,
            message_id=message_id,
            now=now,
            today=paris_day(now),
        )
        if change_id is None:
            return None
    transition_id = store.add_transition(
        account_id,
        decision_id=decision_id,
        message_id=message_id,
        application_id=verdict.application_id,
        from_stage=current,
        to_stage=plan.stage,
        outcome=plan.outcome,
        change_id=change_id,
        now=now,
    )
    _event(
        store,
        account_id,
        message_id,
        "messages.transition_recorded",
        Actor(verdict.author.value),
        {
            "transition_id": transition_id,
            "decision_id": decision_id,
            "application_id": verdict.application_id,
            "from": current.value,
            "to": plan.stage.value,
            "outcome": plan.outcome.value,
            "change_id": change_id,
        },
    )
    return transition_id


# The gestures of « Ce qui a bougé » (Q5).


def mark_seen(
    store: DecisionStore, *, account_id: int, transition_id: int, now: datetime
) -> None:
    """« Vu »: the transition leaves « Ce qui a bougé »; an applied one stays applied."""
    transition = _pending(store, account_id, transition_id)
    _settle(store, account_id, transition, Gesture.SEEN, None, now, Actor.USER)


def dismiss(
    store: DecisionStore, *, account_id: int, transition_id: int, now: datetime
) -> None:
    """« Ignorer » a proposal: the application keeps its stage."""
    transition = _pending(store, account_id, transition_id)
    if transition.outcome is not Outcome.PROPOSED:
        raise InvalidGestureError(NOT_PROPOSED)
    _settle(store, account_id, transition, Gesture.DISMISSED, None, now, Actor.USER)


def apply_proposal(
    store: DecisionStore, *, account_id: int, transition_id: int, now: datetime
) -> int | None:
    """« Appliquer » a proposal: the user moves the application (freely, D1 Q5), the message named in its event.
    Returns the change's id, None when the application was already at that stage (the proposal is then « Vu »)."""
    transition = _pending(store, account_id, transition_id)
    if transition.outcome is not Outcome.PROPOSED:
        raise InvalidGestureError(NOT_PROPOSED)
    applications = store.applications()
    if applications.stage(account_id, transition.application_id) is None:
        raise InvalidGestureError(UNKNOWN_APPLICATION)
    change_id = applications.move(
        account_id,
        transition.application_id,
        transition.to_stage,
        author=Author.USER,
        message_id=transition.message_id,
        now=now,
        today=paris_day(now),
    )
    gesture = Gesture.SEEN if change_id is None else Gesture.APPLIED
    _settle(store, account_id, transition, gesture, change_id, now, Actor.USER)
    return change_id


def cancel_transition(
    store: DecisionStore, *, account_id: int, transition_id: int, now: datetime
) -> None:
    """« Annuler » an applied transition, while it is still the application's latest change (D1, Q6)."""
    transition = _pending(store, account_id, transition_id)
    if transition.outcome is not Outcome.APPLIED or transition.change_id is None:
        raise InvalidGestureError(NOT_APPLIED)
    if not store.applications().cancel(
        account_id, transition.application_id, transition.change_id, now
    ):
        raise InvalidGestureError(NOT_LAST)
    _settle(
        store,
        account_id,
        transition,
        Gesture.CANCELLED,
        transition.change_id,
        now,
        Actor.USER,
    )


# The gestures on a message (Q6).


def correct(
    store: DecisionStore,
    *,
    account_id: int,
    message_id: int,
    category: Category,
    application_id: int | None,
    now: datetime,
    remember_sender: bool = False,
    remember_domain: bool = False,
) -> Corrected:
    """« Corriger »: the user's decision about the message (a label, D14), after undoing the transition the message
    gave while it is the application's latest change (Q3); its own transition is proposed. « Toujours pour cet
    expéditeur » and « Retenir le domaine » (Q7) are written with it."""
    message, current = _locked(store, account_id, message_id)
    if (
        application_id is not None
        and store.applications().stage(account_id, application_id) is None
    ):
        raise InvalidGestureError(UNKNOWN_APPLICATION)
    kept = _undo(store, account_id, message.id, now)
    verdict = _user_verdict(
        category, application_id, message, CORRECTED_RULE, "Corrigé par toi."
    )
    decision_id = _decide(store, account_id, message, verdict, current, now)
    proposal_id = _follow(store, account_id, message.id, decision_id, verdict, now)
    rule_address = None
    if remember_sender and rule_offered(message.sender_address, category):
        rule_address = (message.sender_address or "").lower()
        _add_rule(store, account_id, rule_address, category, decision_id, now)
    domain = None
    if remember_domain and application_id is not None:
        domain = domain_offered(message.sender_address)
        if domain is not None:
            store.applications().learn_domain(account_id, application_id, domain, now)
    return Corrected(decision_id, kept, proposal_id, rule_address, domain)


def confirm(
    store: DecisionStore, *, account_id: int, message_id: int, now: datetime
) -> int | None:
    """« Juste »: the user confirms Rocky's decision (a label, D14); its transition, if any, is proposed. Returns the
    decision's id, None when the decision in force is already the user's."""
    message, current = _locked(store, account_id, message_id)
    if current is None or current.category is None:
        raise InvalidGestureError(NOTHING_TO_CONFIRM)
    if current.author is Author.USER:
        return None
    verdict = _user_verdict(
        current.category,
        current.application_id,
        message,
        CONFIRMED_RULE,
        "Confirmé par toi.",
    )
    decision_id = _decide(store, account_id, message, verdict, current, now)
    _follow(store, account_id, message.id, decision_id, verdict, now)
    return decision_id


def create_application(
    store: DecisionStore,
    offers: Offers,
    *,
    account_id: int,
    message_id: int,
    company: str,
    title: str,
    link: str,
    now: datetime,
) -> int:
    """« Créer la candidature » (Q4): the minimal offer, the application at « Envoyée » and the message attached to it
    (the user's decision), in one transaction. Idempotent: the same message gives the same offer and application.
    Raises ``InvalidGestureError`` or ``InvalidLinkError``."""
    message, current = _locked(store, account_id, message_id)
    company = " ".join(company.split())
    title = " ".join(title.split())
    if not company:
        raise InvalidGestureError(COMPANY_NEEDED)
    if not title:
        raise InvalidGestureError(TITLE_NEEDED)
    address = check_link(link) if link.strip() else gmail_link(message)
    offer_id = offers.record_message_offer(
        account_id,
        message_id=message.id,
        company=company,
        title=title,
        link=address,
        now=now,
        today=paris_day(now),
    )
    applications = store.applications()
    application_id = applications.open_outside(
        account_id, offer_id, paris_day(message.received_at), now
    )
    if (
        current is not None
        and current.author is Author.USER
        and current.application_id == application_id
    ):
        return application_id
    _undo(store, account_id, message.id, now)
    category = (
        current.category
        if current is not None and current.category in ATTACHABLE
        else Category.ACKNOWLEDGEMENT
    )
    verdict = _user_verdict(
        category,
        application_id,
        message,
        CREATED_RULE,
        f"Candidature créée par toi depuis ce message ({company}).",
    )
    decision_id = _decide(store, account_id, message, verdict, current, now)
    _follow(store, account_id, message.id, decision_id, verdict, now)
    return application_id


def remove_sender_rule(
    store: DecisionStore, *, account_id: int, rule_id: int, now: datetime
) -> str:
    """Remove a rule of the account (Q7): a row of its own. Returns its address."""
    rule = next(
        (rule for rule in store.sender_rule_list(account_id) if rule.id == rule_id),
        None,
    )
    if rule is None:
        raise InvalidGestureError(UNKNOWN_RULE)
    store.remove_sender_rule(account_id, rule, now)
    store.append_event(
        NewEvent(
            type="messages.sender_rule_removed",
            actor=Actor.USER,
            subject_type="mail_sender_rule",
            subject_id=str(rule.id),
            payload={
                "sender_address": rule.sender_address,
                "category": rule.category.value,
            },
            account_id=account_id,
        )
    )
    return rule.sender_address


def _add_rule(
    store: DecisionStore,
    account_id: int,
    address: str,
    category: Category,
    decision_id: int,
    now: datetime,
) -> None:
    for rule in store.sender_rule_list(account_id):
        if rule.sender_address == address:
            if rule.category is category:
                return
            store.remove_sender_rule(account_id, rule, now)
    rule_id = store.add_sender_rule(
        account_id, address, category, decision_id=decision_id, now=now
    )
    store.append_event(
        NewEvent(
            type="messages.sender_rule_added",
            actor=Actor.USER,
            subject_type="mail_sender_rule",
            subject_id=str(rule_id),
            payload={
                "sender_address": address,
                "category": category.value,
                "decision_id": decision_id,
            },
            account_id=account_id,
        )
    )


def _locked(
    store: DecisionStore, account_id: int, message_id: int
) -> tuple[MessageRef, StoredDecision | None]:
    message = store.message(account_id, message_id)
    if message is None:
        raise LookupError(UNKNOWN_MESSAGE)
    store.lock_message(message.id)
    return message, store.current_decision(message.id)


def _undo(
    store: DecisionStore, account_id: int, message_id: int, now: datetime
) -> bool:
    """Q3: the transitions the message gave are undone while they are their application's latest change; the
    proposals are settled. True when one stays, the user having changed the application since."""
    kept = False
    applications = store.applications()
    for transition in store.transitions_of_message(message_id):
        if transition.undone:
            continue
        change_id = transition.change_id
        undone = None
        if change_id is not None and applications.in_force(
            account_id, transition.application_id, change_id
        ):
            undone = applications.cancel(
                account_id, transition.application_id, change_id, now
            )
            kept = kept or not undone
        if undone or transition.pending:
            _settle(
                store,
                account_id,
                transition,
                Gesture.CORRECTED,
                change_id if undone else None,
                now,
                Actor.USER,
            )
    return kept


def _user_verdict(
    category: Category,
    application_id: int | None,
    message: MessageRef,
    rule: str,
    reason: str,
) -> Verdict:
    return Verdict(
        category,
        application_id,
        Level.HIGH,
        Author.USER,
        (Proof(Tier.USER, rule, quoted(message), reason),),
    )


def _decide(
    store: DecisionStore,
    account_id: int,
    message: MessageRef,
    verdict: Verdict,
    reviewed: StoredDecision | None,
    now: datetime,
) -> int:
    reviews_id = None if reviewed is None else reviewed.id
    decision_id = store.add_decision(
        account_id, message.id, verdict, now, reviews_id=reviews_id
    )
    _event(
        store,
        account_id,
        message.id,
        "messages.message_classified",
        Actor.USER,
        {
            "decision_id": decision_id,
            "category": None if verdict.category is None else verdict.category.value,
            "application_id": verdict.application_id,
            "level": verdict.level.value,
            "rule": verdict.proofs[0].rule,
            "reviews_id": reviews_id,
        },
    )
    return decision_id


def _pending(store: DecisionStore, account_id: int, transition_id: int) -> Transition:
    transition = store.transition(account_id, transition_id)
    if transition is None or not transition.pending:
        raise InvalidGestureError(UNKNOWN_MOVE)
    return transition


def _settle(
    store: DecisionStore,
    account_id: int,
    transition: Transition,
    gesture: Gesture,
    change_id: int | None,
    now: datetime,
    actor: Actor,
) -> None:
    if gesture in transition.settled:
        return
    store.settle(account_id, transition.id, gesture, change_id=change_id, now=now)
    _event(
        store,
        account_id,
        transition.message_id,
        "messages.transition_settled",
        actor,
        {
            "transition_id": transition.id,
            "gesture": gesture.value,
            "application_id": transition.application_id,
            "change_id": change_id,
        },
    )


def _event(
    store: DecisionStore,
    account_id: int,
    message_id: int,
    type_: str,
    actor: Actor,
    payload: dict[str, JsonValue],
) -> None:
    store.append_event(
        NewEvent(
            type=type_,
            actor=actor,
            subject_type="email_message",
            subject_id=str(message_id),
            payload=payload,
            account_id=account_id,
        )
    )
