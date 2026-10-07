"""Rules of the applications (D1): the state computed from the changes, proposals, deferral, automatic transitions."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from rocky.candidatures.model import (
    Change,
    ChangeKind,
    Channel,
    InvalidChangeError,
    LetterState,
    NextAction,
    NoteRow,
    Revision,
    RevisionKind,
    Sending,
    Stage,
)
from rocky.candidatures.rules import (
    Step,
    Tab,
    automatic_transition_allowed,
    deferred,
    dossier,
    employer_domain,
    is_due,
    is_overdue,
    is_stale_revision,
    journey,
    language_in_force,
    last_done,
    latest_revisions,
    make_next_action,
    notes_in_force,
    proposal,
    proposed_channel,
    revision_filename,
    sending_in_force,
    sent_change,
    stage_tab,
    tabs_of,
    to_cancel,
)
from rocky.offres.decisions import Author

AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TODAY = date(2026, 9, 29)
FINISH = NextAction("Finir le dossier", date(2026, 10, 1))
FOLLOW_UP = NextAction("Relancer", date(2026, 10, 6))


def change(
    id_: int,
    kind: ChangeKind,
    stage: Stage | None = None,
    action: NextAction | None = None,
    cancels: int | None = None,
) -> Change:
    return Change(
        id=id_,
        application_id=1,
        kind=kind,
        author=Author.USER,
        changed_at=AT,
        stage=stage,
        next_action=action,
        cancels=cancels,
    )


CREATED = change(1, ChangeKind.CREATED, Stage.PREPARING, FINISH)
SENT = change(2, ChangeKind.STAGE, Stage.SENT, FOLLOW_UP)


def test_no_change_is_no_application() -> None:
    state = dossier([])

    assert (state.open, state.stage, state.next_action) == (False, None, None)
    assert to_cancel([]) is None


def test_the_latest_changes_give_the_stage_and_the_next_action() -> None:
    later = NextAction("Relancer", date(2026, 10, 9))
    rows = [CREATED, SENT, change(3, ChangeKind.NEXT_ACTION, action=later)]

    state = dossier(rows)

    assert (state.open, state.stage, state.next_action) == (True, Stage.SENT, later)
    assert state.creation == CREATED


def test_a_stage_change_sets_the_next_action_too_even_to_none() -> None:
    rows = [CREATED, change(2, ChangeKind.STAGE, Stage.WITHDRAWN)]

    assert dossier(rows).next_action is None


def test_cleared_next_action() -> None:
    rows = [CREATED, change(2, ChangeKind.NEXT_ACTION)]

    assert dossier(rows).next_action is None
    assert dossier(rows).stage is Stage.PREPARING


def test_cancelling_a_stage_change_brings_back_the_stage_and_the_action() -> None:
    rows = [CREATED, SENT, change(3, ChangeKind.CANCELLATION, cancels=2)]

    state = dossier(rows)

    assert (state.stage, state.next_action) == (Stage.PREPARING, FINISH)


def test_annuler_goes_back_through_the_history() -> None:
    rows = [CREATED, SENT, change(3, ChangeKind.CANCELLATION, cancels=2)]

    assert to_cancel([CREATED, SENT]) == SENT
    assert to_cancel(rows) == CREATED


def test_a_cancelled_creation_closes_the_application() -> None:
    rows = [CREATED, change(2, ChangeKind.CANCELLATION, cancels=1)]

    state = dossier(rows)

    assert (state.open, state.stage, state.next_action, state.creation) == (
        False,
        None,
        None,
        None,
    )
    assert to_cancel(rows) is None


def test_a_new_creation_opens_the_application_again() -> None:
    again = change(3, ChangeKind.CREATED, Stage.PREPARING, FINISH)
    rows = [CREATED, change(2, ChangeKind.CANCELLATION, cancels=1), again]

    state = dossier(rows)

    assert (state.open, state.creation) == (True, again)


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (Stage.PREPARING, ("Finir le dossier", date(2026, 10, 1))),
        (Stage.READY, ("Envoyer la candidature", date(2026, 10, 1))),
        (Stage.PREFILLED, ("Confirmer l'envoi", date(2026, 9, 30))),
        (Stage.SENT, ("Relancer", date(2026, 10, 6))),
        (Stage.IN_DISCUSSION, ("Relancer", date(2026, 10, 6))),
        (Stage.INTERVIEW, ("Préparer l'entretien", None)),
        (Stage.OFFER, ("Répondre à l'offre", date(2026, 10, 2))),
        (Stage.REJECTED, None),
        (Stage.WITHDRAWN, None),
        (Stage.NO_RESPONSE, None),
    ],
)
def test_proposals(stage: Stage, expected: tuple[str, date | None] | None) -> None:
    assert proposal(stage, TODAY) == expected


def test_a_next_action_needs_both_fields_or_none() -> None:
    assert make_next_action("  ", None) is None
    assert make_next_action(" Relancer ", TODAY) == NextAction("Relancer", TODAY)
    with pytest.raises(InvalidChangeError, match="date"):
        make_next_action("Préparer l'entretien", None)
    with pytest.raises(InvalidChangeError, match="prochaine action"):
        make_next_action("", TODAY)


def test_deferring_starts_from_the_due_date() -> None:
    assert deferred(FOLLOW_UP, 3, TODAY).due == date(2026, 10, 9)


def test_deferring_an_overdue_action_starts_from_today() -> None:
    overdue = NextAction("Relancer", date(2026, 9, 20))

    assert is_overdue(overdue, TODAY)
    assert deferred(overdue, 1, TODAY) == NextAction("Relancer", date(2026, 9, 30))
    assert not is_overdue(deferred(overdue, 1, TODAY), TODAY)


def test_only_the_offered_delays() -> None:
    with pytest.raises(InvalidChangeError):
        deferred(FOLLOW_UP, 2, TODAY)


@pytest.mark.parametrize(
    ("current", "proposed", "allowed"),
    [
        (Stage.SENT, Stage.IN_DISCUSSION, True),
        (Stage.SENT, Stage.INTERVIEW, True),
        (Stage.SENT, Stage.REJECTED, True),
        (Stage.INTERVIEW, Stage.SENT, False),  # a late acknowledgement never goes back
        (Stage.SENT, Stage.SENT, False),
        (Stage.REJECTED, Stage.INTERVIEW, False),  # never out of an outcome
        (Stage.REJECTED, Stage.NO_RESPONSE, False),
    ],
)
def test_automatic_transitions_never_go_back_nor_leave_an_outcome(
    current: Stage, proposed: Stage, allowed: bool
) -> None:
    assert automatic_transition_allowed(current, proposed) is allowed


@pytest.mark.parametrize(
    ("stage", "current", "done", "sent"),
    [
        (Stage.PREPARING, Step.CV, set(), False),
        (Stage.READY, Step.SEND, {Step.CV}, False),
        (Stage.PREFILLED, Step.SEND, {Step.CV}, False),
        (Stage.SENT, Step.FOLLOW, {Step.CV, Step.SEND}, True),
        (Stage.IN_DISCUSSION, Step.FOLLOW, {Step.CV, Step.SEND}, True),
        (Stage.INTERVIEW, Step.FOLLOW, {Step.CV, Step.SEND}, True),
        (Stage.OFFER, Step.FOLLOW, {Step.CV, Step.SEND}, True),
    ],
)
def test_the_journey_of_an_open_application_follows_its_stage(
    stage: Stage, current: Step, done: set[Step], sent: bool
) -> None:
    found = journey(stage)

    assert (found.current, set(found.done), found.sent, found.closed) == (
        current,
        done,
        sent,
        False,
    )
    assert Step.LETTER not in found.done  # no letter decided yet


@pytest.mark.parametrize("letter", [LetterState.VALIDATED, LetterState.SKIPPED])
def test_a_letter_validated_or_set_aside_is_done(letter: LetterState) -> None:
    preparing = journey(Stage.PREPARING, letter)
    ready = journey(Stage.READY, letter)
    sent = journey(Stage.SENT, letter)

    # Still in preparation: « Lettre prête » (or « Pas de lettre ») is the next gesture (decision D4, Q16).
    assert (preparing.current, set(preparing.done)) == (
        Step.LETTER,
        {Step.CV, Step.LETTER},
    )
    assert (ready.current, set(ready.done)) == (Step.SEND, {Step.CV, Step.LETTER})
    assert set(sent.done) == {Step.CV, Step.LETTER, Step.SEND}


@pytest.mark.parametrize(
    "stage", [None, Stage.REJECTED, Stage.WITHDRAWN, Stage.NO_RESPONSE]
)
def test_a_cancelled_or_finished_application_opens_on_its_follow_up(
    stage: Stage | None,
) -> None:
    found = journey(stage)

    assert found.closed
    assert found.current is Step.FOLLOW


# Revisions and sendings (decision D5).


def revision(id_: int, kind: RevisionKind, language: str = "fr") -> Revision:
    return Revision(
        id=id_,
        application_id=1,
        kind=kind,
        language=language,
        path=f"comptes/1/candidatures/{id_}.pdf",
        sha256=f"sha{id_}",
        inputs_sha256=f"inputs{id_}",
        letter_id=None if kind is RevisionKind.CV else 1,
        created_at=AT,
    )


def sending(id_: int, change_id: int) -> Sending:
    return Sending(
        id=id_,
        application_id=1,
        change_id=change_id,
        sent_on=TODAY,
        channel=Channel.LINKEDIN,
        channel_detail=None,
        cv_revision_id=None,
        letter_revision_id=None,
        message_id=None,
        created_at=AT,
    )


def test_the_latest_revision_of_each_kind_in_the_language_is_proposed() -> None:
    revisions = [
        revision(1, RevisionKind.CV),
        revision(2, RevisionKind.LETTER),
        revision(3, RevisionKind.CV),
        revision(4, RevisionKind.CV, "en"),
    ]

    assert latest_revisions(revisions, "fr") == {
        RevisionKind.CV: revisions[2],
        RevisionKind.LETTER: revisions[1],
    }
    assert latest_revisions(revisions, "en") == {RevisionKind.CV: revisions[3]}


def test_a_revision_is_stale_once_its_inputs_differ() -> None:
    cv = revision(1, RevisionKind.CV)

    assert not is_stale_revision(cv, "inputs1")
    assert is_stale_revision(cv, "inputs2")
    assert is_stale_revision(cv, None)


def test_the_file_name_the_recruiter_sees() -> None:
    assert (
        revision_filename(RevisionKind.CV, "Camille  Martin", "fr")
        == "CV_Camille_Martin_FR.pdf"
    )
    assert revision_filename(RevisionKind.LETTER, "", "en") == "Lettre_EN.pdf"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.linkedin.com/jobs/view/123", Channel.LINKEDIN),
        ("https://fr.indeed.com/viewjob?jk=1", Channel.INDEED),
        (
            "https://www.welcometothejungle.com/fr/companies/a/jobs/b",
            Channel.WELCOME_TO_THE_JUNGLE,
        ),
        ("https://www.apec.fr/candidat/offre.html", Channel.APEC),
        ("https://www.hellowork.com/fr-fr/emplois/1.html", Channel.HELLOWORK),
        ("https://candidat.francetravail.fr/offres/1", Channel.FRANCE_TRAVAIL),
        ("mailto:jobs@acme.fr", Channel.EMAIL),
        ("https://jobs.acme.fr/apply", Channel.COMPANY_SITE),
        # A domain merely containing a platform's name is not that platform.
        ("https://notlinkedin.com/x", Channel.COMPANY_SITE),
        ("", Channel.COMPANY_SITE),
    ],
)
def test_the_channel_is_proposed_from_the_link(url: str, expected: Channel) -> None:
    assert proposed_channel(url) is expected


def test_the_sending_in_force_is_that_of_the_latest_change_sent() -> None:
    first_sent = change(2, ChangeKind.STAGE, Stage.SENT, FOLLOW_UP)
    cancelled = change(3, ChangeKind.CANCELLATION, cancels=2)
    sent_again = change(4, ChangeKind.STAGE, Stage.SENT, FOLLOW_UP)
    sendings = [sending(1, 2), sending(2, 4)]

    assert sending_in_force([CREATED, first_sent], sendings) == sendings[0]
    assert sending_in_force([CREATED, first_sent, cancelled], sendings) is None
    assert (
        sending_in_force([CREATED, first_sent, cancelled, sent_again], sendings)
        == sendings[1]
    )


def test_a_change_sent_before_d5_has_no_sending() -> None:
    assert sent_change([CREATED, SENT]) == SENT
    assert sending_in_force([CREATED, SENT], []) is None
    assert sent_change([CREATED]) is None


# The screen 📝 Candidatures and the follow-up (decision D6).


def test_the_proposal_stops_at_the_deadline_before_the_sending() -> None:
    deadline = date(2026, 9, 30)

    assert proposal(Stage.PREPARING, TODAY, deadline) == ("Finir le dossier", deadline)
    assert proposal(Stage.READY, TODAY, deadline) == (
        "Envoyer la candidature",
        deadline,
    )
    # After the sending, the deadline is no limit; a deadline past or far changes nothing.
    assert proposal(Stage.SENT, TODAY, deadline) == ("Relancer", date(2026, 10, 6))
    assert proposal(Stage.PREPARING, TODAY, date(2026, 9, 28)) == (
        "Finir le dossier",
        date(2026, 10, 1),
    )
    assert proposal(Stage.PREPARING, TODAY, date(2026, 12, 1)) == (
        "Finir le dossier",
        date(2026, 10, 1),
    )
    assert proposal(Stage.PREPARING, TODAY, TODAY) == ("Finir le dossier", TODAY)


def test_a_done_action_sets_the_next_one() -> None:
    relaunch_again = NextAction("Relancer", date(2026, 10, 13))
    done = change(3, ChangeKind.ACTION_DONE, action=relaunch_again)

    assert dossier([CREATED, SENT, done]).next_action == relaunch_again
    # « Annuler » brings back the action done.
    cancelled = change(4, ChangeKind.CANCELLATION, cancels=3)
    assert dossier([CREATED, SENT, done, cancelled]).next_action == FOLLOW_UP
    assert to_cancel([CREATED, SENT, done]) == done
    # The screen says what « Fait » did, while it is the latest change in force.
    assert last_done([CREATED, SENT, done]) == (FOLLOW_UP, relaunch_again)
    assert last_done([CREATED, SENT, done, cancelled]) is None
    assert last_done([CREATED, SENT]) is None


@pytest.mark.parametrize(
    ("stage", "tab"),
    [
        (Stage.PREPARING, Tab.PREPARING),
        (Stage.READY, Tab.READY),
        (Stage.PREFILLED, Tab.READY),
        (Stage.SENT, Tab.FOLLOW_UP),
        (Stage.IN_DISCUSSION, Tab.FOLLOW_UP),
        (Stage.INTERVIEW, Tab.FOLLOW_UP),
        (Stage.OFFER, Tab.FOLLOW_UP),
        (Stage.REJECTED, Tab.CLOSED),
        (Stage.WITHDRAWN, Tab.CLOSED),
        (Stage.NO_RESPONSE, Tab.CLOSED),
    ],
)
def test_each_stage_has_its_tab(stage: Stage, tab: Tab) -> None:
    assert stage_tab(stage) is tab


def test_an_action_due_today_or_overdue_is_to_do() -> None:
    assert is_due(NextAction("Relancer", TODAY), TODAY)
    assert is_due(NextAction("Relancer", date(2026, 9, 1)), TODAY)
    assert not is_due(NextAction("Relancer", date(2026, 9, 30)), TODAY)
    assert not is_due(None, TODAY)
    assert tabs_of(Stage.SENT, NextAction("Relancer", TODAY), TODAY) == {
        Tab.FOLLOW_UP,
        Tab.TO_DO,
    }
    assert tabs_of(Stage.SENT, None, TODAY) == {Tab.FOLLOW_UP}


def test_the_notes_in_force_leave_out_the_removed_ones() -> None:
    rows = [
        NoteRow(1, 1, "Appel de Julie", None, AT),
        NoteRow(2, 1, "Entretien à préparer", None, AT),
        NoteRow(3, 1, None, 1, AT),
    ]

    assert [(note.id, note.text) for note in notes_in_force(rows)] == [
        (2, "Entretien à préparer")
    ]


def test_french_until_a_language_is_chosen() -> None:
    assert language_in_force(None) == "fr"
    assert language_in_force("en") == "en"


@pytest.mark.parametrize(
    ("typed", "kept"),
    [
        ("covea.fr", "covea.fr"),
        ("  RH@Recrutement.Covea.FR ", "recrutement.covea.fr"),
        ("https://www.covea.fr/carrieres", "covea.fr"),
        ("", None),
    ],
)
def test_the_employer_domain_as_rocky_keeps_it(typed: str, kept: str | None) -> None:
    assert employer_domain(typed) == kept


@pytest.mark.parametrize("typed", ["covea", "covea .fr", "http://", "a@b"])
def test_a_wrong_employer_domain_is_refused(typed: str) -> None:
    with pytest.raises(InvalidChangeError):
        employer_domain(typed)
