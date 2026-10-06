"""Applications on PostgreSQL (D1): constraints of the appended changes, and the exit criterion — a failure injected
while cancelling leaves no contradictory state.

The exit criterion runs in real transactions (``migrated_engine``), as a route does: each use case in
``engine.begin()``, a failure rolls the whole transaction back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pytest
from sqlalchemy import Connection, Engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from rocky.candidatures import api as candidatures_api
from rocky.candidatures.api import OffresDecisions
from rocky.candidatures.model import (
    Change,
    ChangeKind,
    Channel,
    Dossier,
    LetterHeader,
    LetterOrigin,
    LetterParagraph,
    LetterVersion,
    NewChange,
    NewLetter,
    NewPrefill,
    NewRevision,
    NewSending,
    NextAction,
    NoLetter,
    RevisionKind,
    Stage,
)
from rocky.candidatures.rules import dossier, notes_in_force, sending_in_force
from rocky.candidatures.sql import (
    SqlApplicationStore,
    application_changes,
    application_languages,
    application_letters,
    application_notes,
    application_sendings,
    applications,
)
from rocky.candidatures.usecases import (
    add_note,
    cancel_last_change,
    change_stage,
    choose_language,
    confirm_sending,
    mark_action_done,
    prepare_application,
    record_prefill,
    record_revisions,
    set_employer_domain,
    skip_letter,
)
from rocky.offres import api as offres_api
from rocky.offres.decisions import (
    Author,
    Decision,
    DecisionValue,
    application_decision,
)
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore, job_decisions
from rocky.offres.usecases import record_decision, record_offer
from rocky.system.events import NewEvent, events, events_about
from tests.offres.fakes import NOW, TODAY, Seeker, new_seeker, posting

INTEREST = application_decision(["target_job"])
LATER = Decision(DecisionValue.LATER, ("reread",))
FOLLOW_UP = NextAction("Relancer", date(2026, 10, 6))


class InjectedFailureError(Exception):
    """The injected failure."""


class FailingStore(SqlApplicationStore):
    """Fails right after one write of the cancellation: its row, or its event."""

    def __init__(self, connection: Connection, point: str) -> None:
        super().__init__(connection)
        self.point = point

    def insert_change(
        self,
        account_id: int,
        application_id: int,
        change: NewChange,
        *,
        author: Author,
        now: datetime,
    ) -> Change:
        row = super().insert_change(
            account_id, application_id, change, author=author, now=now
        )
        if self.point == "change" and change.kind is ChangeKind.CANCELLATION:
            raise InjectedFailureError
        return row

    def append_event(self, event: NewEvent) -> None:
        super().append_event(event)
        if self.point == "event" and event.type == "candidatures.change_cancelled":
            raise InjectedFailureError


class FailingOffers(OffresDecisions):
    """Fails right after the decision on the offer is cancelled (its row and its event written)."""

    def __init__(self, connection: Connection, point: str) -> None:
        super().__init__(connection)
        self.point = point

    def cancel(self, account_id: int, decision_id: int, now: datetime) -> bool:
        cancelled = super().cancel(account_id, decision_id, now)
        if self.point == "decision":
            raise InjectedFailureError
        return cancelled


@dataclass(frozen=True)
class Snapshot:
    state: Dossier
    decision: DecisionValue | None
    changes: int
    decisions: int
    journal: tuple[str, ...]


@dataclass(frozen=True)
class Case:
    engine: Engine
    seeker: Seeker
    offer_id: int
    application_id: int

    @property
    def account_id(self) -> int:
        return self.seeker.account_id

    def snapshot(self) -> Snapshot:
        with self.engine.connect() as connection:
            rows = SqlApplicationStore(connection).changes(self.application_id)
            decisions = connection.execute(
                select(func.count())
                .select_from(job_decisions)
                .where(job_decisions.c.account_id == self.account_id)
            ).scalar_one()
            journal = connection.execute(
                select(events.c.type)
                .where(events.c.account_id == self.account_id)
                .order_by(events.c.id)
            ).scalars()
            return Snapshot(
                dossier(rows),
                offres_api.decision_in_force(
                    connection, self.account_id, self.offer_id
                ),
                len(rows),
                decisions,
                tuple(journal),
            )

    def cancel(self, point: str | None = None) -> Change | None:
        with self.engine.begin() as connection:
            store = (
                SqlApplicationStore(connection)
                if point is None
                else FailingStore(connection, point)
            )
            offers = (
                OffresDecisions(connection)
                if point is None
                else FailingOffers(connection, point)
            )
            return cancel_last_change(
                store,
                offers,
                account_id=self.account_id,
                application_id=self.application_id,
                now=NOW,
            )

    def done(self, store: SqlApplicationStore | None = None) -> None:
        with self.engine.begin() as connection:
            mark_action_done(
                store or SqlApplicationStore(connection),
                account_id=self.account_id,
                application_id=self.application_id,
                now=NOW,
                today=TODAY,
            )

    def move(self, stage: Stage, action: NextAction | None) -> None:
        with self.engine.begin() as connection:
            change_stage(
                SqlApplicationStore(connection),
                account_id=self.account_id,
                application_id=self.application_id,
                stage=stage,
                next_action=action,
                now=NOW,
            )


def recorded(connection: Connection, seeker: Seeker, external_id: str) -> int:
    return record_offer(
        SqlStore(connection),
        account_id=seeker.account_id,
        offer=posting(external_id),
        inputs=scoring_inputs(seeker.profile(connection)),
        origin=Origin.WATCH,
        track_ids=[seeker.tracks["Data"]],
        now=NOW,
        today=TODAY,
    ).offer_id


def prepared(engine: Engine, previous: Decision | None = LATER) -> Case:
    """An offer decided « Plus tard », then « Préparer la candidature », committed."""
    with engine.begin() as connection:
        seeker = new_seeker(connection)
        offer_id = recorded(connection, seeker, "d1")
        if previous is not None:
            record_decision(
                SqlStore(connection),
                account_id=seeker.account_id,
                offer_id=offer_id,
                decision=previous,
                track_id=None,
                now=NOW,
            )
    with engine.begin() as connection:
        application_id = prepare_application(
            SqlApplicationStore(connection),
            OffresDecisions(connection),
            account_id=seeker.account_id,
            offer_id=offer_id,
            interest=INTEREST,
            now=NOW,
            today=TODAY,
        )
    return Case(engine, seeker, offer_id, application_id)


# Exit criterion of D1.


@pytest.mark.parametrize("point", ["change", "decision", "event"])
def test_a_failure_while_cancelling_the_creation_changes_nothing(
    migrated_engine: Engine, point: str
) -> None:
    case = prepared(migrated_engine)
    before = case.snapshot()
    assert before.state.open and before.decision is DecisionValue.INTERESTED

    with pytest.raises(InjectedFailureError):
        case.cancel(point)

    assert case.snapshot() == before


@pytest.mark.parametrize("point", ["change", "event"])
def test_a_failure_while_cancelling_a_stage_change_changes_nothing(
    migrated_engine: Engine, point: str
) -> None:
    case = prepared(migrated_engine)
    case.move(Stage.SENT, FOLLOW_UP)
    before = case.snapshot()
    assert (before.state.stage, before.state.next_action) == (Stage.SENT, FOLLOW_UP)

    with pytest.raises(InjectedFailureError):
        case.cancel(point)

    assert case.snapshot() == before


def test_without_failure_the_cancellation_undoes_the_application_and_its_decision(
    migrated_engine: Engine,
) -> None:
    case = prepared(migrated_engine)
    case.move(Stage.SENT, FOLLOW_UP)
    before = case.snapshot()

    undone = case.cancel()
    assert undone is not None and undone.kind is ChangeKind.STAGE
    middle = case.snapshot()
    assert middle.state.stage is Stage.PREPARING
    assert middle.decision is DecisionValue.INTERESTED

    undone = case.cancel()
    assert undone is not None and undone.kind is ChangeKind.CREATED
    after = case.snapshot()
    assert not after.state.open
    assert after.decision is DecisionValue.LATER  # the decision before « Préparer »
    assert after.changes == before.changes + 2  # nothing deleted
    assert after.journal[len(before.journal) :] == (
        "candidatures.change_cancelled",
        "offres.decision_cancelled",
        "candidatures.change_cancelled",
    )


def test_every_change_has_its_event(migrated_engine: Engine) -> None:
    case = prepared(migrated_engine)
    case.move(Stage.READY, None)
    case.move(Stage.SENT, FOLLOW_UP)
    case.cancel()

    with migrated_engine.connect() as connection:
        changes = connection.execute(
            select(func.count())
            .select_from(application_changes)
            .where(application_changes.c.application_id == case.application_id)
        ).scalar_one()
        traced = connection.execute(
            select(func.count())
            .select_from(events)
            .where(
                events.c.subject_type == "application",
                events.c.subject_id == str(case.application_id),
            )
        ).scalar_one()
    assert changes == traced == 4


def test_preparing_again_reopens_the_same_application(migrated_engine: Engine) -> None:
    case = prepared(migrated_engine, previous=None)
    case.cancel()
    assert case.snapshot().decision is None

    with migrated_engine.begin() as connection:
        again = prepare_application(
            SqlApplicationStore(connection),
            OffresDecisions(connection),
            account_id=case.account_id,
            offer_id=case.offer_id,
            interest=INTEREST,
            now=NOW,
            today=TODAY,
        )

    assert again == case.application_id
    assert case.snapshot().state.open


# Constraints of the base.


def test_one_application_per_offer(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "one")
    store = SqlApplicationStore(db)

    first = store.application_for_offer(seeker.account_id, offer_id, NOW)
    assert store.application_for_offer(seeker.account_id, offer_id, NOW) == first

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(applications).values(
                account_id=seeker.account_id, offer_id=offer_id, created_at=NOW
            )
        )


def test_a_change_is_cancelled_once(db: Connection) -> None:
    seeker = new_seeker(db)
    store = SqlApplicationStore(db)
    application = store.application_for_offer(
        seeker.account_id, recorded(db, seeker, "once"), NOW
    )
    created = store.insert_change(
        seeker.account_id,
        application.id,
        NewChange(ChangeKind.CREATED, stage=Stage.PREPARING),
        author=Author.USER,
        now=NOW,
    )
    cancellation = NewChange(ChangeKind.CANCELLATION, cancels=created.id)
    store.insert_change(
        seeker.account_id, application.id, cancellation, author=Author.USER, now=NOW
    )

    with pytest.raises(IntegrityError), db.begin_nested():
        store.insert_change(
            seeker.account_id,
            application.id,
            cancellation,
            author=Author.USER,
            now=NOW,
        )


@pytest.mark.parametrize(
    "change",
    [
        NewChange(ChangeKind.STAGE),  # a stage change without stage
        NewChange(ChangeKind.NEXT_ACTION, stage=Stage.SENT),
        NewChange(ChangeKind.CANCELLATION, cancels=None),
        NewChange(ChangeKind.NEXT_ACTION, decision_id=1),
    ],
)
def test_the_base_refuses_an_inconsistent_change(
    db: Connection, change: NewChange
) -> None:
    seeker = new_seeker(db)
    store = SqlApplicationStore(db)
    application = store.application_for_offer(
        seeker.account_id, recorded(db, seeker, "bad"), NOW
    )

    with pytest.raises(IntegrityError), db.begin_nested():
        store.insert_change(
            seeker.account_id, application.id, change, author=Author.USER, now=NOW
        )


def test_the_base_refuses_a_cancellation_that_sets_an_action(db: Connection) -> None:
    seeker = new_seeker(db)
    store = SqlApplicationStore(db)
    application = store.application_for_offer(
        seeker.account_id, recorded(db, seeker, "alone"), NOW
    )
    created = store.insert_change(
        seeker.account_id,
        application.id,
        NewChange(ChangeKind.CREATED, stage=Stage.PREPARING),
        author=Author.USER,
        now=NOW,
    )

    with pytest.raises(IntegrityError), db.begin_nested():
        store.insert_change(
            seeker.account_id,
            application.id,
            NewChange(
                ChangeKind.CANCELLATION, cancels=created.id, next_action=FOLLOW_UP
            ),
            author=Author.USER,
            now=NOW,
        )


def test_an_application_of_another_account_is_not_found(db: Connection) -> None:
    seeker, other = new_seeker(db), new_seeker(db)
    store = SqlApplicationStore(db)
    application = store.application_for_offer(
        seeker.account_id, recorded(db, seeker, "mine"), NOW
    )

    assert store.locked_application(other.account_id, application.id) is None
    assert store.locked_application(seeker.account_id, application.id) == application


def test_the_latest_cv_selection_of_an_application_is_in_force(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = record_offer(
        SqlStore(db),
        account_id=seeker.account_id,
        offer=posting("d3-selection"),
        inputs=scoring_inputs(seeker.profile(db)),
        origin=Origin.WATCH,
        track_ids=[seeker.tracks["Data"]],
        now=NOW,
        today=TODAY,
    ).offer_id
    store = SqlApplicationStore(db)
    application = store.application_for_offer(seeker.account_id, offer_id, NOW)
    assert store.cv_selection(application.id) is None

    first = {"groups": [], "transversal": [1], "projects": [2]}
    second = {"groups": [], "transversal": [], "projects": [3]}
    store.insert_cv_selection(seeker.account_id, application.id, first, NOW)
    store.insert_cv_selection(seeker.account_id, application.id, second, NOW)
    assert store.cv_selection(application.id) == second

    store.insert_cv_selection(seeker.account_id, application.id, None, NOW)
    assert store.cv_selection(application.id) is None


# « Pas de lettre » and « Prête à envoyer » are written together (decision D4, Q16).


class FailingLetterStore(SqlApplicationStore):
    """Fails right after one write of « Pas de lettre »: its row, its event, the stage change or its event."""

    def __init__(self, connection: Connection, point: str) -> None:
        super().__init__(connection)
        self.point = point

    def insert_letter(
        self,
        account_id: int,
        application_id: int,
        letter: NewLetter | None,
        now: datetime,
    ) -> int:
        letter_id = super().insert_letter(account_id, application_id, letter, now)
        if self.point == "letter":
            raise InjectedFailureError
        return letter_id

    def insert_change(
        self,
        account_id: int,
        application_id: int,
        change: NewChange,
        *,
        author: Author,
        now: datetime,
    ) -> Change:
        row = super().insert_change(
            account_id, application_id, change, author=author, now=now
        )
        if self.point == "stage":
            raise InjectedFailureError
        return row

    def append_event(self, event: NewEvent) -> None:
        super().append_event(event)
        if (self.point, event.type) in {
            ("letter_event", "candidatures.letter_skipped"),
            ("stage_event", "candidatures.stage_changed"),
        }:
            raise InjectedFailureError


def skipped(case: Case, point: str | None = None) -> None:
    with case.engine.begin() as connection:
        store = (
            SqlApplicationStore(connection)
            if point is None
            else FailingLetterStore(connection, point)
        )
        skip_letter(
            store,
            account_id=case.account_id,
            application_id=case.application_id,
            now=NOW,
            today=TODAY,
        )


def letters_of(case: Case) -> int:
    with case.engine.connect() as connection:
        return len(SqlApplicationStore(connection).letters(case.application_id))


@pytest.mark.parametrize("point", ["letter", "letter_event", "stage", "stage_event"])
def test_a_failure_while_choosing_no_letter_changes_nothing(
    migrated_engine: Engine, point: str
) -> None:
    case = prepared(migrated_engine)
    before = (case.snapshot(), letters_of(case))

    with pytest.raises(InjectedFailureError):
        skipped(case, point)

    assert (case.snapshot(), letters_of(case)) == before


def test_without_failure_no_letter_makes_the_application_ready(
    migrated_engine: Engine,
) -> None:
    case = prepared(migrated_engine)

    skipped(case)

    assert case.snapshot().state.stage is Stage.READY
    assert letters_of(case) == 1


def test_a_letter_comes_back_as_it_was_validated(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "l1")
    store = SqlApplicationStore(db)
    application = store.application_for_offer(seeker.account_id, offer_id, NOW)
    letter = NewLetter(
        language="en",
        paragraphs=(
            LetterParagraph(
                "why_you",
                "Acme appeals to me.",
                LetterOrigin.EDITED,
                "Acme thrills me.",
                ("Formule convenue : « thrilled ».",),
            ),
        ),
        header=LetterHeader("Application", "Hiring team\nAcme"),
        generic_sha256="abc",
        checks_version="test",
    )

    store.insert_letter(seeker.account_id, application.id, letter, NOW)
    store.insert_letter(seeker.account_id, application.id, None, NOW)

    stored, nothing = store.letters(application.id)
    assert isinstance(stored, LetterVersion) and isinstance(nothing, NoLetter)
    assert (stored.paragraphs, stored.header) == (letter.paragraphs, letter.header)
    with pytest.raises(IntegrityError):
        db.execute(
            insert(application_letters).values(
                application_id=application.id,
                account_id=seeker.account_id,
                kind="letter",
                language="fr",
                created_at=NOW,
            )
        )


# A sending and a prefilled form are written with their stage change (decision D5, Q5, Q6).


class FailingSendStore(SqlApplicationStore):
    """Fails right after one write: the stage change, the sending or the prefill row, or one of their events."""

    def __init__(self, connection: Connection, point: str) -> None:
        super().__init__(connection)
        self.point = point

    def insert_change(
        self,
        account_id: int,
        application_id: int,
        change: NewChange,
        *,
        author: Author,
        now: datetime,
    ) -> Change:
        row = super().insert_change(
            account_id, application_id, change, author=author, now=now
        )
        if self.point == "stage":
            raise InjectedFailureError
        return row

    def insert_sending(
        self,
        account_id: int,
        application_id: int,
        change_id: int,
        sending: NewSending,
        now: datetime,
    ) -> int:
        sending_id = super().insert_sending(
            account_id, application_id, change_id, sending, now
        )
        if self.point == "sending":
            raise InjectedFailureError
        return sending_id

    def insert_prefill(
        self, account_id: int, application_id: int, prefill: NewPrefill, now: datetime
    ) -> int:
        prefill_id = super().insert_prefill(account_id, application_id, prefill, now)
        if self.point == "prefill":
            raise InjectedFailureError
        return prefill_id

    def append_event(self, event: NewEvent) -> None:
        super().append_event(event)
        if (self.point, event.type) in {
            ("stage_event", "candidatures.stage_changed"),
            ("sending_event", "candidatures.sending_confirmed"),
            ("prefill_event", "candidatures.prefilled"),
        }:
            raise InjectedFailureError


def ready_with_cv(engine: Engine) -> tuple[Case, int]:
    """A committed application « Prête à envoyer » (without letter), its CV generated once."""
    case = prepared(engine)
    skipped(case)
    with engine.begin() as connection:
        (cv,) = record_revisions(
            SqlApplicationStore(connection),
            account_id=case.account_id,
            application_id=case.application_id,
            revisions=[NewRevision(RevisionKind.CV, "fr", "c/1/cv.pdf", "s", "i")],
            now=NOW,
        )
    return case, cv


def store_for(connection: Connection, point: str | None) -> SqlApplicationStore:
    return (
        SqlApplicationStore(connection)
        if point is None
        else FailingSendStore(connection, point)
    )


def sent(case: Case, cv: int, point: str | None = None) -> None:
    with case.engine.begin() as connection:
        confirm_sending(
            store_for(connection, point),
            account_id=case.account_id,
            application_id=case.application_id,
            sending=NewSending(TODAY, Channel.LINKEDIN, None, cv),
            now=NOW,
            today=TODAY,
        )


def prefilled(case: Case, cv: int, point: str | None = None) -> None:
    with case.engine.begin() as connection:
        record_prefill(
            store_for(connection, point),
            account_id=case.account_id,
            application_id=case.application_id,
            prefill=NewPrefill("https://jobs.acme.fr/a", cv, None, None, ("Nom",), ()),
            now=NOW,
            today=TODAY,
        )


def sending_rows(case: Case) -> tuple[int, int]:
    with case.engine.connect() as connection:
        store = SqlApplicationStore(connection)
        return (
            len(store.sendings(case.application_id)),
            len(store.prefills(case.application_id)),
        )


@pytest.mark.parametrize("point", ["stage", "stage_event", "sending", "sending_event"])
def test_a_failure_while_confirming_a_sending_changes_nothing(
    migrated_engine: Engine, point: str
) -> None:
    case, cv = ready_with_cv(migrated_engine)
    before = (case.snapshot(), sending_rows(case))

    with pytest.raises(InjectedFailureError):
        sent(case, cv, point)

    assert (case.snapshot(), sending_rows(case)) == before


@pytest.mark.parametrize("point", ["prefill", "prefill_event", "stage", "stage_event"])
def test_a_failure_while_recording_a_prefill_changes_nothing(
    migrated_engine: Engine, point: str
) -> None:
    case, cv = ready_with_cv(migrated_engine)
    before = (case.snapshot(), sending_rows(case))

    with pytest.raises(InjectedFailureError):
        prefilled(case, cv, point)

    assert (case.snapshot(), sending_rows(case)) == before


def test_without_failure_the_sending_is_in_force_until_cancelled(
    migrated_engine: Engine,
) -> None:
    case, cv = ready_with_cv(migrated_engine)
    prefilled(case, cv)
    assert case.snapshot().state.stage is Stage.PREFILLED

    sent(case, cv)

    with migrated_engine.connect() as connection:
        store = SqlApplicationStore(connection)
        in_force = sending_in_force(
            store.changes(case.application_id), store.sendings(case.application_id)
        )
    assert in_force is not None and in_force.cv_revision_id == cv
    assert case.snapshot().state.stage is Stage.SENT

    # « Annuler » the change « Envoyée »: the sending is no longer in force, nothing else is written.
    case.cancel()
    with migrated_engine.connect() as connection:
        store = SqlApplicationStore(connection)
        assert (
            sending_in_force(
                store.changes(case.application_id), store.sendings(case.application_id)
            )
            is None
        )
        assert len(store.sendings(case.application_id)) == 1
    assert case.snapshot().state.stage is Stage.PREFILLED


def test_a_sending_documents_one_change_and_names_its_channel(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "d5")
    store = SqlApplicationStore(db)
    application = store.application_for_offer(seeker.account_id, offer_id, NOW)
    change = store.insert_change(
        seeker.account_id,
        application.id,
        NewChange(ChangeKind.CREATED, stage=Stage.SENT),
        author=Author.USER,
        now=NOW,
    )
    store.insert_sending(
        seeker.account_id,
        application.id,
        change.id,
        NewSending(TODAY, Channel.OTHER, "Salon"),
        NOW,
    )
    assert store.sendings(application.id)[0].channel_detail == "Salon"

    for values in (
        {"change_id": change.id, "channel": "linkedin"},  # one sending per change
        {"change_id": change.id + 10**9, "channel": "linkedin"},  # an unknown change
        {"change_id": change.id, "channel": "other"},  # « Autre » without detail
    ):
        nested = db.begin_nested()
        with pytest.raises(IntegrityError):
            db.execute(
                insert(application_sendings).values(
                    application_id=application.id,
                    account_id=seeker.account_id,
                    sent_on=TODAY,
                    created_at=NOW,
                    **values,
                )
            )
        nested.rollback()


def test_a_letter_revision_names_its_letter_version(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "d5-letter")
    store = SqlApplicationStore(db)
    application = store.application_for_offer(seeker.account_id, offer_id, NOW)
    cv = NewRevision(RevisionKind.CV, "en", "c/x.pdf", "s", "i")

    revision_id = store.insert_revision(seeker.account_id, application.id, cv, NOW)

    (stored,) = store.revisions(application.id)
    assert (stored.id, stored.kind, stored.language) == (
        revision_id,
        RevisionKind.CV,
        "en",
    )
    with pytest.raises(IntegrityError):
        store.insert_revision(
            seeker.account_id,
            application.id,
            NewRevision(RevisionKind.LETTER, "fr", "c/y.pdf", "s", "i"),
            NOW,
        )


# The follow-up (decision D6): « Fait » is a change like the others, cancelled under the same guarantee.


@pytest.mark.parametrize("point", ["change", "event"])
def test_a_failure_while_cancelling_fait_changes_nothing(
    migrated_engine: Engine, point: str
) -> None:
    case = prepared(migrated_engine)
    case.move(Stage.SENT, FOLLOW_UP)
    case.done()
    before = case.snapshot()
    assert before.state.next_action == NextAction("Relancer", date(2026, 10, 6))

    with pytest.raises(InjectedFailureError):
        case.cancel(point)

    assert case.snapshot() == before


class FailingDoneStore(SqlApplicationStore):
    """Fails right after the event of « Fait »: its change was written."""

    def append_event(self, event: NewEvent) -> None:
        super().append_event(event)
        if event.type == "candidatures.action_done":
            raise InjectedFailureError


def test_a_failure_while_marking_fait_changes_nothing(migrated_engine: Engine) -> None:
    case = prepared(migrated_engine)
    case.move(Stage.SENT, FOLLOW_UP)
    before = case.snapshot()

    with pytest.raises(InjectedFailureError), migrated_engine.begin() as connection:
        mark_action_done(
            FailingDoneStore(connection),
            account_id=case.account_id,
            application_id=case.application_id,
            now=NOW,
            today=TODAY,
        )

    assert case.snapshot() == before


def follow_up_application(db: Connection) -> tuple[int, int, SqlApplicationStore]:
    seeker = new_seeker(db)
    store = SqlApplicationStore(db)
    application = store.application_for_offer(
        seeker.account_id, recorded(db, seeker, "suivi"), NOW
    )
    return seeker.account_id, application.id, store


def test_notes_come_back_and_a_removal_is_written_once(db: Connection) -> None:
    account_id, application_id, store = follow_up_application(db)
    note_id = store.insert_note(
        account_id, application_id, text="Appel de Julie", removes=None, now=NOW
    )
    store.insert_note(account_id, application_id, text=None, removes=note_id, now=NOW)

    assert notes_in_force(store.notes(application_id)) == []
    with pytest.raises(IntegrityError), db.begin_nested():
        store.insert_note(
            account_id, application_id, text=None, removes=note_id, now=NOW
        )


@pytest.mark.parametrize(
    ("text", "removes"), [(None, None), ("", None), ("x" * 4001, None), ("x", 1)]
)
def test_the_base_refuses_an_inconsistent_note(
    db: Connection, text: str | None, removes: int | None
) -> None:
    account_id, application_id, _ = follow_up_application(db)

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(application_notes).values(
                application_id=application_id,
                account_id=account_id,
                text=text,
                removes_id=removes,
                created_at=NOW,
            )
        )


def test_the_latest_language_is_in_force(db: Connection) -> None:
    account_id, application_id, store = follow_up_application(db)
    assert store.language(application_id) is None

    store.insert_language(account_id, application_id, "en", NOW)
    store.insert_language(account_id, application_id, "fr", NOW)

    assert store.language(application_id) == "fr"
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(application_languages).values(
                application_id=application_id,
                account_id=account_id,
                language="de",
                chosen_at=NOW,
            )
        )


def test_the_journal_of_an_application_is_read_by_its_subject(
    migrated_engine: Engine,
) -> None:
    case = prepared(migrated_engine)
    case.move(Stage.SENT, FOLLOW_UP)
    with migrated_engine.begin() as connection:
        store = SqlApplicationStore(connection)
        add_note(
            store,
            account_id=case.account_id,
            application_id=case.application_id,
            text="Relancé par téléphone",
            now=NOW,
        )
        choose_language(
            store,
            account_id=case.account_id,
            application_id=case.application_id,
            language="en",
            now=NOW,
        )

    with migrated_engine.connect() as connection:
        found = events_about(
            connection, case.account_id, "application", str(case.application_id)
        )
        other = events_about(
            connection,
            case.account_id + 10_000,
            "application",
            str(case.application_id),
        )

    assert [event.type for event in found] == [
        "candidatures.application_created",
        "candidatures.stage_changed",
        "candidatures.note_added",
        "candidatures.language_chosen",
    ]
    assert found[-1].payload == {"language": "en", "previous": "fr"}
    assert other == []


def test_the_mail_targets_are_the_applications_sent(migrated_engine: Engine) -> None:
    """Decision E2, Q11: from « Préremplie » on; with the offer's links and the employer's domain (Q3)."""
    case = prepared(migrated_engine)
    with migrated_engine.connect() as connection:
        assert candidatures_api.mail_targets(connection, case.seeker.account_id) == []
    case.move(Stage.SENT, None)
    with migrated_engine.begin() as connection:
        set_employer_domain(
            SqlApplicationStore(connection),
            account_id=case.seeker.account_id,
            application_id=case.application_id,
            typed="exemple.fr",
            now=NOW,
        )

    with migrated_engine.connect() as connection:
        [found] = candidatures_api.mail_targets(connection, case.seeker.account_id)
        labels = candidatures_api.application_labels(
            connection, case.seeker.account_id, [case.application_id]
        )

    assert (found.application_id, found.company, found.stage) == (
        case.application_id,
        "Exemple",
        Stage.SENT,
    )
    assert found.employer_domain == "exemple.fr"
    assert found.links == ("https://apec.example/offres/d1",)
    assert labels == {case.application_id: "Exemple — Data analyst (H/F)"}
