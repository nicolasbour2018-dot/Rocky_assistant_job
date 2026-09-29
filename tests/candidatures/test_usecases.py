"""Use cases of the applications (D1) with in-memory adapters: no SQL, no FastAPI."""

from __future__ import annotations

from datetime import date

import pytest

from rocky.candidatures.model import (
    Change,
    ChangeKind,
    Dossier,
    InvalidChangeError,
    NextAction,
    Stage,
)
from rocky.candidatures.rules import dossier
from rocky.candidatures.usecases import (
    cancel_last_change,
    change_stage,
    defer_next_action,
    prepare_application,
    set_next_action,
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
