"""Use cases of the applications (D1): prepare, change the stage or the next action, cancel the latest change; and
their letter and message (D4).

Each use case runs inside one transaction opened by the caller (the stores never commit), and locks the application
first: a change, its event and the decision on the offer it goes with are written together or not at all (exit
criterion of D1). Decision ``docs/decisions/D1-dossier-statuts.md``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from rocky.candidatures.letter import letter_state
from rocky.candidatures.model import (
    FOLLOW_UP_STAGES,
    LANGUAGES,
    NOTE_MAX_LENGTH,
    PROPOSALS,
    Application,
    ApplicationStore,
    Change,
    ChangeKind,
    Channel,
    Dossier,
    InvalidChangeError,
    LetterState,
    NewChange,
    NewLetter,
    NewMessage,
    NewPrefill,
    NewRevision,
    NewSending,
    NextAction,
    OfferDecisions,
    RevisionKind,
    Stage,
)
from rocky.candidatures.rules import (
    automatic_transition_allowed,
    deferred,
    dossier,
    language_in_force,
    notes_in_force,
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
    deadline: date | None = None,
) -> int:
    """« Préparer la candidature » (Q2, Q8): opens the application of the offer, « En préparation », with the proposed
    next action (no later than the offer's ``deadline``, D6 Q8); idempotent (an open application is returned as it is).

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
    next_action = _proposed(Stage.PREPARING, today, deadline)
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
    written = _stage_change(
        store, application, current, stage, next_action, now, author
    )
    return written is not None


def _stage_change(
    store: ApplicationStore,
    application: Application,
    current: Dossier,
    stage: Stage,
    next_action: NextAction | None,
    now: datetime,
    author: Author,
) -> Change | None:
    """The stage change and its event, on an application already locked; None when it is already at ``stage``."""
    previous = current.stage
    if previous is None:
        raise LookupError(f"application {application.id} has no stage")
    if stage is previous:
        return None
    if author is not Author.USER and not automatic_transition_allowed(previous, stage):
        raise InvalidChangeError("Cette transition automatique n'est pas permise.")
    change = store.insert_change(
        application.account_id,
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
    return change


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


def adjust_cv_selection(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    layout: Mapping[str, JsonValue] | None,
    now: datetime,
) -> bool:
    """Keep the CV selection the user adjusted for this application (decision D3, Q4), with its event (the before and
    after are training data, D14); ``None`` goes back to the rules' proposal. False when nothing changes."""
    application, _ = _open(store, account_id, application_id)
    before = store.cv_selection(application.id)
    if before == layout:
        return False
    store.insert_cv_selection(account_id, application.id, layout, now)
    _event(
        store,
        application,
        "candidatures.cv_selection_changed",
        Author.USER,
        {
            "before": None if before is None else dict(before),
            "after": None if layout is None else dict(layout),
        },
    )
    return True


# The letter and the message (decision D4). The model is called before: these only write what the user validated.

NO_LETTER_YET = (
    "Valide d'abord une lettre, ou choisis « Pas de lettre pour cette candidature »."
)


def validate_letter(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    letter: NewLetter,
    now: datetime,
) -> int:
    """Keep the letter the user validated as the version in force of its language (Q11, Q17); the earlier versions
    stay. Allowed at any stage, after sending too (Q20)."""
    application, _ = _open(store, account_id, application_id)
    if not any(p.text for p in letter.paragraphs):
        raise InvalidChangeError("La lettre est vide.")
    letter_id = store.insert_letter(account_id, application.id, letter, now)
    _event(
        store,
        application,
        "candidatures.letter_validated",
        Author.USER,
        {
            "letter_id": letter_id,
            "language": letter.language,
            "origins": [p.origin.value for p in letter.paragraphs],
            "adapted_shown": sum(p.proposed is not None for p in letter.paragraphs),
            "signals": sum(len(p.signals) for p in letter.paragraphs),
            "generic_sha256": letter.generic_sha256,
            "checks_version": letter.checks_version,
        },
    )
    return letter_id


def skip_letter(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    now: datetime,
    today: date,
    deadline: date | None = None,
) -> None:
    """« Pas de lettre pour cette candidature » (Q4, Q16): kept, and an application in preparation becomes « Prête à
    envoyer » with it, in the same transaction."""
    application, current = _open(store, account_id, application_id)
    store.insert_letter(account_id, application.id, None, now)
    _event(store, application, "candidatures.letter_skipped", Author.USER, {})
    if current.stage is Stage.PREPARING:
        _ready(store, account_id, application.id, now, today, deadline)


def letter_ready(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    now: datetime,
    today: date,
    deadline: date | None = None,
) -> bool:
    """« Lettre prête : passer à l'envoi » (Q16): refused until a letter is validated or set aside. False when the
    application is already past its preparation (nothing written)."""
    application, current = _open(store, account_id, application_id)
    if letter_state(store.letters(application.id)) is LetterState.NONE:
        raise InvalidChangeError(NO_LETTER_YET)
    if current.stage is not Stage.PREPARING:
        return False
    return _ready(store, account_id, application.id, now, today, deadline)


def _ready(
    store: ApplicationStore,
    account_id: int,
    application_id: int,
    now: datetime,
    today: date,
    deadline: date | None,
) -> bool:
    return change_stage(
        store,
        account_id=account_id,
        application_id=application_id,
        stage=Stage.READY,
        next_action=_proposed(Stage.READY, today, deadline),
        now=now,
    )


def validate_message(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    message: NewMessage,
    now: datetime,
) -> int:
    """Keep the accompanying message the user validated (Q12); the earlier ones stay."""
    application, _ = _open(store, account_id, application_id)
    if not message.text.strip():
        raise InvalidChangeError("Le message est vide.")
    message_id = store.insert_message(account_id, application.id, message, now)
    _event(
        store,
        application,
        "candidatures.message_validated",
        Author.USER,
        {
            "message_id": message_id,
            "language": message.language,
            "origin": message.origin.value,
            "signals": len(message.signals),
            "checks_version": message.checks_version,
        },
    )
    return message_id


# Revisions, sending and prefilling (decision D5). The PDFs are rendered and stored, and the workstation called,
# before: these only write the rows that point at them.

ALREADY_SENT = "Cette candidature est déjà marquée envoyée : annule ce changement pour corriger l'envoi."
NOT_YOURS = "Ce document n'appartient pas à cette candidature."
# DORMANT (decision D5, acceptance of 04/10): PREFILL_STAGES, NOT_READY and ``record_prefill`` serve the prefilling
# by the Rocky workstation, kept but not run (``web.PREFILL_ENABLED``).
# The stages a form can be prefilled at (Q6): ready to send, or prefilled already (again, on another tab).
PREFILL_STAGES = frozenset({Stage.READY, Stage.PREFILLED})
NOT_READY = "Le préremplissage se fait quand la candidature est prête à envoyer."


def record_revisions(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    revisions: Sequence[NewRevision],
    now: datetime,
) -> tuple[int, ...]:
    """Keep the PDFs just generated (Q2): one revision each, with one event; the earlier ones stay."""
    application, _ = _open(store, account_id, application_id)
    if not revisions:
        raise ValueError("no revision to record")
    letters = {entry.id for entry in store.letters(application.id)}
    if any(
        r.kind is RevisionKind.LETTER and r.letter_id not in letters for r in revisions
    ):
        raise InvalidChangeError(NOT_YOURS)
    ids = tuple(
        store.insert_revision(account_id, application.id, revision, now)
        for revision in revisions
    )
    _event(
        store,
        application,
        "candidatures.revisions_generated",
        Author.USER,
        {
            "revisions": [
                {
                    "id": revision_id,
                    "kind": revision.kind.value,
                    "language": revision.language,
                    "sha256": revision.sha256,
                    "letter_id": revision.letter_id,
                }
                for revision_id, revision in zip(ids, revisions, strict=True)
            ]
        },
    )
    return ids


def confirm_sending(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    sending: NewSending,
    now: datetime,
    today: date,
) -> int:
    """« J'ai envoyé ma candidature » (Q3, Q5): the stage « Envoyée », and the sending that documents it (date,
    channel, the exact revisions and message), in the same transaction. « Relancer » falls 7 days after the date of
    sending."""
    application, current = _open(store, account_id, application_id)
    if current.stage is Stage.SENT:
        raise InvalidChangeError(ALREADY_SENT)
    if sending.sent_on > today:
        raise InvalidChangeError("La date d'envoi ne peut pas être dans le futur.")
    if sending.channel is Channel.OTHER and not (sending.channel_detail or "").strip():
        raise InvalidChangeError("Précise le canal d'envoi.")
    _check_documents(
        store,
        application.id,
        sending.cv_revision_id,
        sending.letter_revision_id,
        sending.message_id,
    )
    follow_up = PROPOSALS[Stage.SENT]
    due = sending.sent_on + timedelta(days=follow_up.days or 0)
    change = _stage_change(
        store,
        application,
        current,
        Stage.SENT,
        NextAction(follow_up.label, due),
        now,
        Author.USER,
    )
    if change is None:  # unreachable: the stage is not « Envoyée » (checked above)
        raise LookupError(f"application {application.id} is already sent")
    sending_id = store.insert_sending(
        account_id, application.id, change.id, sending, now
    )
    _event(
        store,
        application,
        "candidatures.sending_confirmed",
        Author.USER,
        {
            "sending_id": sending_id,
            "change_id": change.id,
            "sent_on": sending.sent_on.isoformat(),
            "channel": sending.channel.value,
            "cv_revision_id": sending.cv_revision_id,
            "letter_revision_id": sending.letter_revision_id,
            "message_id": sending.message_id,
        },
    )
    return sending_id


def record_prefill(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    prefill: NewPrefill,
    now: datetime,
    today: date,
) -> int:
    """DORMANT (``web.PREFILL_ENABLED``). The workstation took the form (Q6): its report is kept, and an
    application ready to send becomes « Préremplie », in the same transaction. Only the domain of the form goes to
    the journal (a link may carry a tracking token)."""
    application, current = _open(store, account_id, application_id)
    if current.stage not in PREFILL_STAGES:
        raise InvalidChangeError(NOT_READY)
    _check_documents(
        store,
        application.id,
        prefill.cv_revision_id,
        prefill.letter_revision_id,
        prefill.message_id,
    )
    prefill_id = store.insert_prefill(account_id, application.id, prefill, now)
    _event(
        store,
        application,
        "candidatures.prefilled",
        Author.USER,
        {
            "prefill_id": prefill_id,
            "domain": urlsplit(prefill.target_url).hostname or "",
            "cv_revision_id": prefill.cv_revision_id,
            "letter_revision_id": prefill.letter_revision_id,
            "message_id": prefill.message_id,
            "filled": list(prefill.filled),
            "missing": list(prefill.missing),
        },
    )
    if current.stage is Stage.READY:
        _stage_change(
            store,
            application,
            current,
            Stage.PREFILLED,
            _proposed(Stage.PREFILLED, today),
            now,
            Author.USER,
        )
    return prefill_id


def _check_documents(
    store: ApplicationStore,
    application_id: int,
    cv_revision_id: int | None,
    letter_revision_id: int | None,
    message_id: int | None,
) -> None:
    """Each document given is one of the application's own, of the right kind."""
    kinds = {r.id: r.kind for r in store.revisions(application_id)}
    for revision_id, kind in (
        (cv_revision_id, RevisionKind.CV),
        (letter_revision_id, RevisionKind.LETTER),
    ):
        if revision_id is not None and kinds.get(revision_id) is not kind:
            raise InvalidChangeError(NOT_YOURS)
    if message_id is not None and message_id not in {
        m.id for m in store.messages(application_id)
    }:
        raise InvalidChangeError(NOT_YOURS)


# The follow-up of an application (decision D6): « Fait », notes, language.

NOTHING_DONE = "Aucune prochaine action à marquer comme faite."
NOT_FOLLOWED_UP = (
    "« Fait » vient après l'envoi : avant, fais avancer le dossier par son étape."
)
NOTE_EMPTY = "Écris ta note."
NOTE_TOO_LONG = f"Une note tient en {NOTE_MAX_LENGTH} caractères au plus."
UNKNOWN_NOTE = "Cette note n'existe pas ou a déjà été retirée."


def mark_action_done(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    now: datetime,
    today: date,
) -> tuple[NextAction, NextAction | None]:
    """« Fait » (Q5): the action in force is done; the next one proposed for the stage follows it (« Relancer » at
    J+7), or none when its date is to be entered (« Préparer l'entretien »). Returns the action done and the next
    one. The action done is the one in force before this change: « Annuler » brings it back."""
    application, current = _open(store, account_id, application_id)
    if current.next_action is None:
        raise InvalidChangeError(NOTHING_DONE)
    if current.stage not in FOLLOW_UP_STAGES:
        raise InvalidChangeError(NOT_FOLLOWED_UP)
    following = _proposed(current.stage, today)
    store.insert_change(
        account_id,
        application.id,
        NewChange(ChangeKind.ACTION_DONE, next_action=following),
        author=Author.USER,
        now=now,
    )
    _event(
        store,
        application,
        "candidatures.action_done",
        Author.USER,
        {
            "done": _action_json(current.next_action),
            "next_action": _action_json(following),
        },
    )
    return current.next_action, following


def add_note(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    text: str,
    now: datetime,
) -> int:
    """A dated note (Q6), never rewritten."""
    written = text.strip()
    if not written:
        raise InvalidChangeError(NOTE_EMPTY)
    if len(written) > NOTE_MAX_LENGTH:
        raise InvalidChangeError(NOTE_TOO_LONG)
    application = _locked(store, account_id, application_id)
    note_id = store.insert_note(
        account_id, application.id, text=written, removes=None, now=now
    )
    _event(
        store, application, "candidatures.note_added", Author.USER, {"note_id": note_id}
    )
    return note_id


def remove_note(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    note_id: int,
    now: datetime,
) -> None:
    """Remove a note (Q6): a row of its own; the note stays, out of the notes in force."""
    application = _locked(store, account_id, application_id)
    if note_id not in {note.id for note in notes_in_force(store.notes(application.id))}:
        raise InvalidChangeError(UNKNOWN_NOTE)
    store.insert_note(account_id, application.id, text=None, removes=note_id, now=now)
    _event(
        store,
        application,
        "candidatures.note_removed",
        Author.USER,
        {"note_id": note_id},
    )


def choose_language(
    store: ApplicationStore,
    *,
    account_id: int,
    application_id: int,
    language: str,
    now: datetime,
) -> bool:
    """The language of the application (Q4): its CV, letter, message and PDFs. False when unchanged."""
    if language not in LANGUAGES:
        raise InvalidChangeError("Langue inconnue.")
    application = _locked(store, account_id, application_id)
    previous = language_in_force(store.language(application.id))
    if language == previous:
        return False
    store.insert_language(account_id, application.id, language, now)
    _event(
        store,
        application,
        "candidatures.language_chosen",
        Author.USER,
        {"language": language, "previous": previous},
    )
    return True


def _locked(
    store: ApplicationStore, account_id: int, application_id: int
) -> Application:
    application = store.locked_application(account_id, application_id)
    if application is None:
        raise LookupError(f"application {application_id} is not of the account")
    return application


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


def _proposed(
    stage: Stage, today: date, deadline: date | None = None
) -> NextAction | None:
    proposed = proposal(stage, today, deadline)
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
