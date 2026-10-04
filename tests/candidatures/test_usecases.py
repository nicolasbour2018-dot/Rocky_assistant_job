"""Use cases of the applications (D1) with in-memory adapters: no SQL, no FastAPI."""

from __future__ import annotations

from datetime import date

import pytest

from rocky.candidatures.model import (
    Change,
    ChangeKind,
    Channel,
    Dossier,
    InvalidChangeError,
    LetterHeader,
    LetterOrigin,
    LetterParagraph,
    MessageOrigin,
    NewLetter,
    NewMessage,
    NewPrefill,
    NewRevision,
    NewSending,
    NextAction,
    NoLetter,
    RevisionKind,
    Stage,
)
from rocky.candidatures.rules import dossier, notes_in_force
from rocky.candidatures.usecases import (
    NOT_FOLLOWED_UP,
    NOTE_EMPTY,
    NOTHING_DONE,
    UNKNOWN_NOTE,
    add_note,
    cancel_last_change,
    change_stage,
    choose_language,
    confirm_sending,
    defer_next_action,
    letter_ready,
    mark_action_done,
    prepare_application,
    record_prefill,
    record_revisions,
    remove_note,
    set_next_action,
    skip_letter,
    validate_letter,
    validate_message,
)
from rocky.offres.decisions import (
    APPLICATION_STARTED,
    Author,
    Decision,
    DecisionValue,
    application_decision,
)
from tests.candidatures.fakes import NOW, TODAY, FakeOffers, FakeStore

ACCOUNT = 7
OFFER = 42
INTEREST = application_decision(["target_job"])
FOLLOW_UP = NextAction("Relancer", date(2026, 10, 6))


def prepare(
    store: FakeStore, offers: FakeOffers, interest: Decision | None = INTEREST
) -> int:
    return prepare_application(
        store,
        offers,
        account_id=ACCOUNT,
        offer_id=OFFER,
        interest=interest,
        now=NOW,
        today=TODAY,
    )


def state(store: FakeStore, application_id: int = 1) -> Dossier:
    return dossier(store.changes(application_id))


def set_action(store: FakeStore, action: NextAction | None) -> bool:
    return set_next_action(
        store, account_id=ACCOUNT, application_id=1, next_action=action, now=NOW
    )


def defer(store: FakeStore, days: int) -> bool:
    return defer_next_action(
        store, account_id=ACCOUNT, application_id=1, days=days, now=NOW, today=TODAY
    )


def undo(store: FakeStore, offers: FakeOffers) -> Change | None:
    return cancel_last_change(
        store, offers, account_id=ACCOUNT, application_id=1, now=NOW
    )


def test_preparing_an_undecided_offer_records_interested_with_the_automatic_reason() -> (
    None
):
    store, offers = FakeStore(), FakeOffers()

    application_id = prepare(store, offers)

    current = state(store, application_id)
    assert (current.open, current.stage) == (True, Stage.PREPARING)
    assert current.next_action == NextAction("Finir le dossier", date(2026, 10, 1))
    assert offers.recorded == [(OFFER, INTEREST)]
    assert INTEREST.reasons == (APPLICATION_STARTED, "target_job")
    assert store.rows[0].decision_id == 101
    assert store.event_types == ["candidatures.application_created"]
    assert store.events[0].payload["decision_id"] == 101


def test_preparing_a_later_offer_records_interested_too() -> None:
    store, offers = FakeStore(), FakeOffers({OFFER: DecisionValue.LATER})

    prepare(store, offers)

    assert offers.in_force[OFFER] is DecisionValue.INTERESTED


def test_preparing_an_interested_offer_records_no_new_decision() -> None:
    store, offers = FakeStore(), FakeOffers({OFFER: DecisionValue.INTERESTED})

    prepare(store, offers, interest=None)

    assert offers.recorded == []
    assert store.rows[0].decision_id is None


def test_reasons_are_needed_unless_the_offer_is_interested() -> None:
    store, offers = FakeStore(), FakeOffers()

    with pytest.raises(InvalidChangeError, match="motif"):
        prepare(store, offers, interest=None)

    assert store.rows == [] and store.events == []


def test_a_rejected_offer_is_refused() -> None:
    store, offers = FakeStore(), FakeOffers({OFFER: DecisionValue.REJECTED})

    with pytest.raises(InvalidChangeError, match="écartée"):
        prepare(store, offers)

    assert store.applications == [] and offers.recorded == []


def test_preparing_twice_opens_the_same_application() -> None:
    store, offers = FakeStore(), FakeOffers()

    first = prepare(store, offers)
    second = prepare(store, offers, interest=None)

    assert first == second
    assert len(store.rows) == 1 and len(offers.recorded) == 1


def test_the_user_moves_freely_and_each_move_is_traced() -> None:
    store, offers = FakeStore(), FakeOffers()
    application_id = prepare(store, offers)

    for stage in (Stage.SENT, Stage.REJECTED, Stage.INTERVIEW, Stage.READY):
        assert change_stage(
            store,
            account_id=ACCOUNT,
            application_id=application_id,
            stage=stage,
            next_action=None,
            now=NOW,
        )

    assert state(store).stage is Stage.READY
    assert store.event_types.count("candidatures.stage_changed") == 4
    assert store.events[-1].payload["from"] == "interview"


def test_the_same_stage_writes_nothing() -> None:
    store, offers = FakeStore(), FakeOffers()
    application_id = prepare(store, offers)

    assert not change_stage(
        store,
        account_id=ACCOUNT,
        application_id=application_id,
        stage=Stage.PREPARING,
        next_action=None,
        now=NOW,
    )
    assert len(store.rows) == 1


def test_a_rule_never_goes_back() -> None:
    store, offers = FakeStore(), FakeOffers()
    application_id = prepare(store, offers)
    change_stage(
        store,
        account_id=ACCOUNT,
        application_id=application_id,
        stage=Stage.INTERVIEW,
        next_action=None,
        now=NOW,
    )

    with pytest.raises(InvalidChangeError):
        change_stage(
            store,
            account_id=ACCOUNT,
            application_id=application_id,
            stage=Stage.SENT,
            next_action=None,
            now=NOW,
            author=Author.RULE,
        )


def test_next_action_set_cleared_and_deferred() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    assert set_action(store, FOLLOW_UP)
    assert not set_action(store, FOLLOW_UP)
    assert defer(store, 3)
    assert state(store).next_action == NextAction("Relancer", date(2026, 10, 9))
    assert store.events[-1].payload["deferred_days"] == 3
    assert set_action(store, None)
    with pytest.raises(InvalidChangeError, match="différer"):
        defer(store, 3)


def test_annuler_undoes_the_latest_change_then_the_creation_and_its_decision() -> None:
    store, offers = FakeStore(), FakeOffers({OFFER: DecisionValue.LATER})
    application_id = prepare(store, offers)
    change_stage(
        store,
        account_id=ACCOUNT,
        application_id=application_id,
        stage=Stage.SENT,
        next_action=FOLLOW_UP,
        now=NOW,
    )

    undone = undo(store, offers)
    assert undone is not None and undone.kind is ChangeKind.STAGE
    assert state(store).stage is Stage.PREPARING
    assert offers.cancelled == []

    undone = undo(store, offers)
    assert undone is not None and undone.kind is ChangeKind.CREATED
    assert not state(store).open
    assert offers.cancelled == [101]
    assert offers.in_force[OFFER] is DecisionValue.LATER
    assert store.events[-1].payload["decision_id"] == 101

    assert undo(store, offers) is None


def test_a_cancelled_application_takes_no_change_and_opens_again() -> None:
    store, offers = FakeStore(), FakeOffers()
    application_id = prepare(store, offers)
    cancel_last_change(
        store, offers, account_id=ACCOUNT, application_id=application_id, now=NOW
    )

    with pytest.raises(InvalidChangeError, match="annulée"):
        change_stage(
            store,
            account_id=ACCOUNT,
            application_id=application_id,
            stage=Stage.SENT,
            next_action=None,
            now=NOW,
        )
    assert prepare(store, offers) == application_id
    assert state(store, application_id).open


def test_an_application_of_another_account_is_unknown() -> None:
    store, offers = FakeStore(), FakeOffers()
    application_id = prepare(store, offers)

    with pytest.raises(LookupError):
        cancel_last_change(
            store,
            offers,
            account_id=ACCOUNT + 1,
            application_id=application_id,
            now=NOW,
        )


# The letter and the message (decision D4)

LETTER = NewLetter(
    language="fr",
    paragraphs=(
        LetterParagraph("opening", "Je postule.", LetterOrigin.GENERIC),
        LetterParagraph(
            "why_you", "Acme m'attire.", LetterOrigin.ADAPTED, "Acme m'attire."
        ),
    ),
    header=LetterHeader("Candidature au poste de Data Analyst", "Acme"),
    generic_sha256="abc",
    checks_version="test",
)


def test_a_validated_letter_is_kept_and_journaled_without_moving_the_stage() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    validate_letter(store, account_id=ACCOUNT, application_id=1, letter=LETTER, now=NOW)

    assert state(store).stage is Stage.PREPARING
    assert store.event_types[-1] == "candidatures.letter_validated"
    assert store.events[-1].payload["origins"] == ["generic", "adapted"]
    with pytest.raises(InvalidChangeError, match="vide"):
        validate_letter(
            store,
            account_id=ACCOUNT,
            application_id=1,
            letter=NewLetter("fr", (), LETTER.header, "abc", "test"),
            now=NOW,
        )


def test_no_letter_makes_a_prepared_application_ready_at_once() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    skip_letter(store, account_id=ACCOUNT, application_id=1, now=NOW, today=TODAY)

    assert state(store).stage is Stage.READY
    assert state(store).next_action is not None
    assert isinstance(store.letters(1)[-1], NoLetter)
    assert store.event_types[-2:] == [
        "candidatures.letter_skipped",
        "candidatures.stage_changed",
    ]


def test_letter_ready_waits_for_a_letter() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    with pytest.raises(InvalidChangeError, match="Valide d'abord une lettre"):
        letter_ready(store, account_id=ACCOUNT, application_id=1, now=NOW, today=TODAY)
    validate_letter(store, account_id=ACCOUNT, application_id=1, letter=LETTER, now=NOW)

    assert letter_ready(
        store, account_id=ACCOUNT, application_id=1, now=NOW, today=TODAY
    )
    assert state(store).stage is Stage.READY
    # Already past its preparation: nothing more is written.
    assert not letter_ready(
        store, account_id=ACCOUNT, application_id=1, now=NOW, today=TODAY
    )


def test_a_validated_message_is_kept_and_journaled() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)
    message = NewMessage("fr", "Bonjour.", MessageOrigin.EDITED, "Salut.", (), "test")

    validate_message(
        store, account_id=ACCOUNT, application_id=1, message=message, now=NOW
    )

    assert store.messages(1)[-1].text == "Bonjour."
    assert store.event_types[-1] == "candidatures.message_validated"


# Revisions, sending and prefilling (decision D5).


def ready(store: FakeStore, offers: FakeOffers) -> tuple[int, int]:
    """A prepared application with a validated letter, made ready; its CV and letter generated once."""
    prepare(store, offers)
    letter_id = validate_letter(
        store, account_id=ACCOUNT, application_id=1, letter=LETTER, now=NOW
    )
    letter_ready(store, account_id=ACCOUNT, application_id=1, now=NOW, today=TODAY)
    cv, letter = record_revisions(
        store,
        account_id=ACCOUNT,
        application_id=1,
        revisions=[
            NewRevision(RevisionKind.CV, "fr", "c/cv.pdf", "s1", "html1"),
            NewRevision(RevisionKind.LETTER, "fr", "c/l.pdf", "s2", "l1", letter_id),
        ],
        now=NOW,
    )
    return cv, letter


def send(store: FakeStore, sending: NewSending) -> int:
    return confirm_sending(
        store,
        account_id=ACCOUNT,
        application_id=1,
        sending=sending,
        now=NOW,
        today=TODAY,
    )


def test_generated_revisions_are_kept_with_one_event() -> None:
    store, offers = FakeStore(), FakeOffers()

    cv, letter = ready(store, offers)

    assert [r.id for r in store.revisions(1)] == [cv, letter]
    assert store.event_types[-1] == "candidatures.revisions_generated"
    generated = store.events[-1].payload["revisions"]
    assert isinstance(generated, list)
    assert [r["kind"] for r in generated if isinstance(r, dict)] == [
        "cv",
        "letter",
    ]


def test_a_letter_revision_needs_a_letter_of_the_application() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    with pytest.raises(InvalidChangeError, match="appartient"):
        record_revisions(
            store,
            account_id=ACCOUNT,
            application_id=1,
            revisions=[NewRevision(RevisionKind.LETTER, "fr", "p", "s", "i", 99)],
            now=NOW,
        )
    assert store.revisions(1) == []


def test_a_sending_documents_the_stage_change_with_the_exact_revisions() -> None:
    store, offers = FakeStore(), FakeOffers()
    cv, letter = ready(store, offers)
    yesterday = date(2026, 9, 28)

    send(store, NewSending(yesterday, Channel.LINKEDIN, None, cv, letter))

    current = state(store)
    assert current.stage is Stage.SENT
    # « Relancer » 7 days after the date of sending, not after today.
    assert current.next_action == NextAction("Relancer", date(2026, 10, 5))
    (sending,) = store.sendings(1)
    assert sending.change_id == store.changes(1)[-1].id
    assert (sending.cv_revision_id, sending.letter_revision_id) == (cv, letter)
    assert store.event_types[-2:] == [
        "candidatures.stage_changed",
        "candidatures.sending_confirmed",
    ]


def test_a_sending_without_document_of_rocky_is_explicit() -> None:
    store, offers = FakeStore(), FakeOffers()
    ready(store, offers)

    send(store, NewSending(TODAY, Channel.OTHER, "Salon de l'emploi"))

    assert store.sendings(1)[0].cv_revision_id is None


@pytest.mark.parametrize(
    ("sending", "message"),
    [
        (NewSending(date(2026, 9, 30), Channel.LINKEDIN), "futur"),
        (NewSending(TODAY, Channel.OTHER, "  "), "Précise"),
        (
            NewSending(TODAY, Channel.EMAIL, None, 2),
            "appartient",
        ),  # a letter given as the CV
        (NewSending(TODAY, Channel.EMAIL, None, None, 99), "appartient"),
        (NewSending(TODAY, Channel.EMAIL, message_id=5), "appartient"),
    ],
)
def test_a_sending_is_refused_with_its_reason(
    sending: NewSending, message: str
) -> None:
    store, offers = FakeStore(), FakeOffers()
    ready(store, offers)
    before = len(store.rows)

    with pytest.raises(InvalidChangeError, match=message):
        send(store, sending)

    assert (len(store.rows), store.sendings(1)) == (before, [])


def test_an_application_sent_already_is_corrected_by_cancelling() -> None:
    store, offers = FakeStore(), FakeOffers()
    ready(store, offers)
    send(store, NewSending(TODAY, Channel.LINKEDIN))

    with pytest.raises(InvalidChangeError, match="annule"):
        send(store, NewSending(TODAY, Channel.INDEED))


def prefill(cv: int, letter: int | None = None) -> NewPrefill:
    return NewPrefill(
        "https://jobs.acme.fr/apply?token=secret",
        cv,
        letter,
        None,
        ("Nom",),
        ("Lettre",),
    )


def test_a_prefilled_form_makes_the_application_prefilled() -> None:
    store, offers = FakeStore(), FakeOffers()
    cv, letter = ready(store, offers)

    record_prefill(
        store,
        account_id=ACCOUNT,
        application_id=1,
        prefill=prefill(cv, letter),
        now=NOW,
        today=TODAY,
    )

    assert state(store).stage is Stage.PREFILLED
    assert state(store).next_action == NextAction(
        "Confirmer l'envoi", date(2026, 9, 30)
    )
    assert store.event_types[-2:] == [
        "candidatures.prefilled",
        "candidatures.stage_changed",
    ]
    # Only the domain is journaled: a link may carry a tracking token.
    assert store.events[-2].payload["domain"] == "jobs.acme.fr"
    assert "secret" not in str(store.events[-2].payload)

    # Again from « Préremplie »: kept, the stage does not move.
    record_prefill(
        store,
        account_id=ACCOUNT,
        application_id=1,
        prefill=prefill(cv),
        now=NOW,
        today=TODAY,
    )
    assert len(store.prefills(1)) == 2
    assert store.event_types[-1] == "candidatures.prefilled"


def test_a_form_is_prefilled_only_when_the_application_is_ready() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)
    cv = record_revisions(
        store,
        account_id=ACCOUNT,
        application_id=1,
        revisions=[NewRevision(RevisionKind.CV, "fr", "p", "s", "i")],
        now=NOW,
    )[0]

    with pytest.raises(InvalidChangeError, match="prête à envoyer"):
        record_prefill(
            store,
            account_id=ACCOUNT,
            application_id=1,
            prefill=prefill(cv),
            now=NOW,
            today=TODAY,
        )
    assert store.prefills(1) == []


# The follow-up (decision D6).


def sent(store: FakeStore, offers: FakeOffers) -> None:
    prepare(store, offers)
    change_stage(
        store,
        account_id=ACCOUNT,
        application_id=1,
        stage=Stage.SENT,
        next_action=FOLLOW_UP,
        now=NOW,
    )


def done(store: FakeStore) -> NextAction | None:
    finished, following = mark_action_done(
        store, account_id=ACCOUNT, application_id=1, now=NOW, today=TODAY
    )
    assert finished.label  # the action that was in force
    return following


def test_preparing_stops_the_proposed_action_at_the_deadline() -> None:
    store = FakeStore()

    prepare_application(
        store,
        FakeOffers(),
        account_id=ACCOUNT,
        offer_id=OFFER,
        interest=INTEREST,
        now=NOW,
        today=TODAY,
        deadline=date(2026, 9, 30),
    )

    assert state(store).next_action == NextAction("Finir le dossier", date(2026, 9, 30))


def test_fait_records_the_action_done_and_proposes_the_next_one() -> None:
    store, offers = FakeStore(), FakeOffers()
    sent(store, offers)

    following = done(store)

    assert following == NextAction("Relancer", date(2026, 10, 6))  # J+7 from today
    assert store.rows[-1].kind is ChangeKind.ACTION_DONE
    assert state(store).stage is Stage.SENT
    assert store.event_types[-1] == "candidatures.action_done"
    assert store.events[-1].payload == {
        "done": {"label": "Relancer", "due": "2026-10-06"},
        "next_action": {"label": "Relancer", "due": "2026-10-06"},
    }


def test_fait_is_undone_by_annuler() -> None:
    store, offers = FakeStore(), FakeOffers()
    sent(store, offers)
    set_action(store, NextAction("Relancer", date(2026, 10, 2)))
    done(store)

    cancelled = undo(store, offers)

    assert cancelled is not None and cancelled.kind is ChangeKind.ACTION_DONE
    assert state(store).next_action == NextAction("Relancer", date(2026, 10, 2))


def test_fait_at_an_interview_leaves_the_next_date_to_enter() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)
    change_stage(
        store,
        account_id=ACCOUNT,
        application_id=1,
        stage=Stage.INTERVIEW,
        next_action=NextAction("Préparer l'entretien", date(2026, 10, 3)),
        now=NOW,
    )

    assert done(store) is None
    assert state(store).next_action is None


def test_fait_needs_an_action_and_a_sent_application() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    with pytest.raises(InvalidChangeError, match=NOT_FOLLOWED_UP):
        done(store)
    set_action(store, None)
    with pytest.raises(InvalidChangeError, match=NOTHING_DONE):
        done(store)


def test_a_note_is_added_and_removed_never_rewritten() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    note_id = add_note(
        store, account_id=ACCOUNT, application_id=1, text="  Appel de Julie  ", now=NOW
    )
    remove_note(store, account_id=ACCOUNT, application_id=1, note_id=note_id, now=NOW)

    assert [(row.text, row.removes) for row in store.note_rows] == [
        ("Appel de Julie", None),
        (None, note_id),
    ]
    assert notes_in_force(store.notes(1)) == []
    assert store.event_types[-2:] == [
        "candidatures.note_added",
        "candidatures.note_removed",
    ]
    with pytest.raises(InvalidChangeError, match=UNKNOWN_NOTE):
        remove_note(
            store, account_id=ACCOUNT, application_id=1, note_id=note_id, now=NOW
        )
    with pytest.raises(InvalidChangeError, match=NOTE_EMPTY):
        add_note(store, account_id=ACCOUNT, application_id=1, text="  ", now=NOW)


def test_a_note_does_not_move_annuler() -> None:
    store, offers = FakeStore(), FakeOffers()
    sent(store, offers)
    add_note(
        store, account_id=ACCOUNT, application_id=1, text="Relancé par tél.", now=NOW
    )

    cancelled = undo(store, offers)

    assert cancelled is not None and cancelled.stage is Stage.SENT
    assert len(notes_in_force(store.notes(1))) == 1


def test_the_language_is_chosen_once_and_journalized() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    def choose(code: str) -> bool:
        return choose_language(
            store, account_id=ACCOUNT, application_id=1, language=code, now=NOW
        )

    assert not choose("fr")  # French already, nothing written
    assert choose("en")
    assert store.language(1) == "en"
    assert store.events[-1].payload == {"language": "en", "previous": "fr"}
    with pytest.raises(InvalidChangeError):
        choose("de")


def test_the_follow_up_of_another_account_is_not_found() -> None:
    store, offers = FakeStore(), FakeOffers()
    prepare(store, offers)

    with pytest.raises(LookupError):
        add_note(store, account_id=99, application_id=1, text="x", now=NOW)
