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

from rocky.candidatures.model import (
    Change,
    ChangeKind,
    Dossier,
    NewChange,
    NextAction,
    Stage,
)
from rocky.candidatures.rules import dossier
from rocky.candidatures.sql import (
    SqlApplicationStore,
    application_changes,
    applications,
)
from rocky.candidatures.usecases import (
    cancel_last_change,
    change_stage,
    prepare_application,
)
from rocky.candidatures.web import OffresDecisions
from rocky.offres import web as offres_web
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
from rocky.system.events import NewEvent, events
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
                offres_web.decision_in_force(
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
