"""The watch on PostgreSQL (exit criterion of C6): a simulated failure leaves an explicit final status, and no offer
without its tracks or its score."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pytest
from sqlalchemy import Engine, select

from rocky.offres.scoring.rules import score as real_score
from rocky.offres.sources.model import (
    Availability,
    CollectedOffer,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sql import SqlStorage, SqlStore, job_offers, offer_tracks
from rocky.offres.usecases import record_offer as real_record
from rocky.offres.watch.model import RunStatus, Trigger, WatchBusyError
from rocky.offres.watch.rules import (
    INTERRUPTED_REASON,
    NO_SOURCE_REASON,
    NO_TRACK_REASON,
)
from rocky.offres.watch.service import DatabaseProfiles
from rocky.offres.watch.usecases import (
    WatchResult,
    recover_interrupted,
    rescore_account,
    run_watch,
)
from rocky.profil.rules import make_track
from rocky.system.events import events
from tests.offres.fakes import (
    HALF_PAST_MIDNIGHT,
    NOW,
    TODAY,
    Seeker,
    new_seeker,
    posting,
)
from tests.offres.sources.fakes import FakeDetailSource, FakeSource


@pytest.fixture
def seeker(migrated_engine: Engine) -> Seeker:
    with migrated_engine.begin() as connection:
        return new_seeker(connection)


def by_title(
    code: SourceCode, results: dict[str, list[str]]
) -> Callable[[SearchQuery], list[CollectedOffer]]:
    """A source answering each job title with postings of these identifiers."""
    return lambda query: [
        posting(external_id, source=code.value, title=query.title)
        for external_id in results.get(query.title, [])
    ]


def apec(results: dict[str, list[str]] | None = None) -> FakeSource:
    return FakeSource(
        SourceCode.APEC,
        by_title(
            SourceCode.APEC,
            results or {"Data analyst": ["a1", "a3"], "Data scientist": ["a2", "a3"]},
        ),
    )


def failing(code: SourceCode) -> FakeSource:
    def fail(query: SearchQuery) -> list[CollectedOffer]:
        raise SourceFailedError("Le site a répondu par une erreur (HTTP 503).")

    return FakeSource(code, fail)


def watch(
    engine: Engine,
    seeker: Seeker,
    *sources: FakeSource,
    trigger: Trigger = Trigger.MANUAL,
    now: datetime = NOW,
) -> WatchResult:
    return run_watch(
        SqlStorage(engine),
        DatabaseProfiles(engine),
        sources,
        account_id=seeker.account_id,
        trigger=trigger,
        limit=20,
        clock=lambda: now,
    )


def stored_ids(engine: Engine, seeker: Seeker) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                select(job_offers.c.external_id).where(
                    job_offers.c.account_id == seeker.account_id
                )
            ).scalars()
        )


def unit_broken(engine: Engine, seeker: Seeker) -> list[int]:
    with engine.connect() as connection:
        return SqlStore(connection).unscored_or_orphan_offers(seeker.account_id)


def stored_run(engine: Engine, run_id: int) -> tuple[RunStatus, str | None]:
    with engine.connect() as connection:
        run = SqlStore(connection).get_run(run_id)
    assert run is not None and run.finished_at is not None
    return run.status, run.reason


def test_a_watch_links_each_offer_to_the_tracks_that_found_it(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    result = watch(migrated_engine, seeker, apec())

    assert result.status is RunStatus.COMPLETED
    assert stored_run(migrated_engine, result.run_id) == (RunStatus.COMPLETED, None)
    assert result.counts.found == 3 and result.counts.new == 3
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            select(job_offers.c.external_id, offer_tracks.c.track_id)
            .join(offer_tracks, offer_tracks.c.offer_id == job_offers.c.id)
            .where(job_offers.c.account_id == seeker.account_id)
        ).all()
    links: dict[str, set[int]] = {}
    for row in rows:
        links.setdefault(row.external_id, set()).add(row.track_id)
    data, ia = seeker.tracks["Data"], seeker.tracks["IA"]
    assert links == {"a1": {data}, "a2": {ia}, "a3": {data, ia}}
    assert unit_broken(migrated_engine, seeker) == []


def test_a_source_that_ignores_the_place_links_its_offers_to_the_right_tracks(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    wttj = FakeSource(
        SourceCode.WTTJ,
        by_title(SourceCode.WTTJ, {"Data scientist": ["w1"]}),
        filters_location=False,
    )

    result = watch(migrated_engine, seeker, wttj)

    assert result.status is RunStatus.COMPLETED
    with migrated_engine.connect() as connection:
        (track_id,) = connection.execute(
            select(offer_tracks.c.track_id)
            .join(job_offers, offer_tracks.c.offer_id == job_offers.c.id)
            .where(job_offers.c.account_id == seeker.account_id)
        ).scalars()
    assert track_id == seeker.tracks["IA"]


def test_a_failing_source_makes_the_watch_partial_and_keeps_the_others_offers(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    result = watch(migrated_engine, seeker, apec(), failing(SourceCode.ADZUNA))

    status, reason = stored_run(migrated_engine, result.run_id)
    assert status is RunStatus.PARTIAL
    assert reason == "Adzuna : En panne (Le site a répondu par une erreur (HTTP 503).)"
    assert stored_ids(migrated_engine, seeker) == {"a1", "a2", "a3"}
    assert unit_broken(migrated_engine, seeker) == []


def test_every_source_failing_makes_the_watch_failed(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    result = watch(
        migrated_engine, seeker, failing(SourceCode.APEC), failing(SourceCode.ADZUNA)
    )

    status, reason = stored_run(migrated_engine, result.run_id)
    assert status is RunStatus.FAILED
    assert reason is not None and reason.startswith("Apec : En panne")
    assert stored_ids(migrated_engine, seeker) == set()


def test_a_source_waiting_for_access_is_not_a_failure(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    waiting = FakeSource(
        SourceCode.FRANCE_TRAVAIL,
        lambda query: [],
        available=Availability.PENDING_ACCESS,
    )
    unconfigured = FakeSource(
        SourceCode.ADZUNA, lambda query: [], available=Availability.NOT_CONFIGURED
    )

    completed = watch(migrated_engine, seeker, apec(), waiting, unconfigured)
    alone = watch(migrated_engine, seeker, waiting, unconfigured)

    assert completed.status is RunStatus.COMPLETED
    assert stored_run(migrated_engine, alone.run_id) == (
        RunStatus.FAILED,
        NO_SOURCE_REASON,
    )


def test_an_offer_the_score_cannot_handle_is_not_written_and_the_watch_is_partial(
    migrated_engine: Engine, seeker: Seeker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def score(analysis, offer, profile, *, today):  # type: ignore[no-untyped-def]
        if offer.external_id == "a2":
            raise KeyError("unexpected")
        return real_score(analysis, offer, profile, today=today)

    monkeypatch.setattr("rocky.offres.usecases.score", score)

    result = watch(migrated_engine, seeker, apec())

    status, reason = stored_run(migrated_engine, result.run_id)
    assert status is RunStatus.PARTIAL
    assert reason == (
        "1 offre non écrite après une erreur technique "
        "(trace dans le journal de l'application)."
    )
    assert result.counts.not_written == 1
    # Nothing of the failing offer was written, not even the offer without its score.
    assert stored_ids(migrated_engine, seeker) == {"a1", "a3"}
    assert unit_broken(migrated_engine, seeker) == []


def test_a_stopped_process_closes_the_run_as_interrupted_with_whole_offers(
    migrated_engine: Engine, seeker: Seeker, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def record(store, **arguments):  # type: ignore[no-untyped-def]
        calls.append(arguments["offer"].external_id)
        recorded = real_record(store, **arguments)
        if len(calls) == 2:
            # Stopped inside the second offer's transaction, after its writes.
            raise KeyboardInterrupt
        return recorded

    monkeypatch.setattr("rocky.offres.watch.usecases.record_offer", record)

    with pytest.raises(KeyboardInterrupt):
        watch(migrated_engine, seeker, apec())

    with migrated_engine.connect() as connection:
        run = SqlStore(connection).last_run(seeker.account_id)
    assert run is not None
    assert (run.status, run.reason) == (RunStatus.INTERRUPTED, INTERRUPTED_REASON)
    # The first offer is whole; the second one's transaction was rolled back.
    assert stored_ids(migrated_engine, seeker) == {"a1"}
    assert unit_broken(migrated_engine, seeker) == []
    # The lock was released: the next watch runs.
    monkeypatch.setattr("rocky.offres.watch.usecases.record_offer", real_record)
    assert watch(migrated_engine, seeker, apec()).status is RunStatus.COMPLETED


def test_a_run_left_running_by_a_killed_process_is_closed_at_start(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    storage = SqlStorage(migrated_engine)
    with storage.transaction() as store:
        run_id = store.start_run(seeker.account_id, Trigger.SCHEDULED, NOW)

    # While another process holds the account's lock, its run is left alone.
    with storage.lock(seeker.account_id):
        assert run_id not in recover_interrupted(storage, clock=lambda: NOW)
    closed = recover_interrupted(storage, clock=lambda: NOW)

    assert run_id in closed
    assert stored_run(migrated_engine, run_id) == (
        RunStatus.INTERRUPTED,
        INTERRUPTED_REASON,
    )
    with migrated_engine.connect() as connection:
        event = connection.execute(
            select(events).where(
                events.c.type == "offres.watch_interrupted",
                events.c.subject_id == str(run_id),
            )
        ).one()
    assert event.account_id == seeker.account_id


def test_a_watch_run_twice_adds_nothing(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    watch(migrated_engine, seeker, apec())

    again = watch(migrated_engine, seeker, apec())

    assert again.status is RunStatus.COMPLETED
    assert (again.counts.found, again.counts.new, again.counts.completed) == (3, 0, 0)
    assert stored_ids(migrated_engine, seeker) == {"a1", "a2", "a3"}


def test_a_second_watch_of_the_same_account_is_refused_while_one_runs(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    with (
        SqlStorage(migrated_engine).lock(seeker.account_id),
        pytest.raises(WatchBusyError),
    ):
        watch(migrated_engine, seeker, apec())

    with migrated_engine.connect() as connection:
        assert SqlStore(connection).last_run(seeker.account_id) is None


def test_the_detail_is_asked_only_for_offers_not_yet_complete(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    def excerpts(query: SearchQuery) -> list[CollectedOffer]:
        if query.title != "Data analyst":
            return []
        return [posting("a1", complete=False), posting("a2", complete=False)]

    source = FakeDetailSource(SourceCode.APEC, excerpts)

    first = watch(migrated_engine, seeker, source)
    second = watch(migrated_engine, seeker, source)

    assert source.completed == ["a1", "a2"]
    assert first.counts.completed == 0 and first.counts.incomplete == 0
    assert second.counts.incomplete == 0
    assert second.sources[0].incomplete == 0


def test_a_profile_without_active_track_fails_with_its_reason(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    with migrated_engine.begin() as connection:
        editor = seeker.editor(connection)
        for track_id in seeker.tracks.values():
            editor.pause_track(track_id)

    result = watch(migrated_engine, seeker, apec())

    assert stored_run(migrated_engine, result.run_id) == (
        RunStatus.FAILED,
        NO_TRACK_REASON,
    )


def test_every_run_is_journaled_with_its_status_and_counts(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    result = watch(migrated_engine, seeker, apec(), trigger=Trigger.SCHEDULED)

    with migrated_engine.connect() as connection:
        event = connection.execute(
            select(events).where(
                events.c.type == "offres.watch_finished",
                events.c.subject_id == str(result.run_id),
            )
        ).one()
    assert event.actor == "system"
    assert event.payload["status"] == "completed"
    assert event.payload["trigger"] == "scheduled"
    assert event.payload["new"] == 3


def test_a_changed_profile_rescores_every_offer_once(
    migrated_engine: Engine, seeker: Seeker
) -> None:
    watch(migrated_engine, seeker, apec())
    storage, profiles = SqlStorage(migrated_engine), DatabaseProfiles(migrated_engine)
    assert (
        rescore_account(
            storage, profiles, account_id=seeker.account_id, clock=lambda: NOW
        )
        == 0
    )
    with migrated_engine.begin() as connection:
        seeker.editor(connection).update_track(
            seeker.tracks["IA"],
            make_track(name="IA", titles=["Data analyst"], locations=["Paris"]),
        )

    rescored = rescore_account(
        storage, profiles, account_id=seeker.account_id, clock=lambda: NOW
    )

    assert rescored == 3
    assert (
        rescore_account(
            storage, profiles, account_id=seeker.account_id, clock=lambda: NOW
        )
        == 0
    )
    with migrated_engine.connect() as connection:
        (event,) = connection.execute(
            select(events).where(
                events.c.type == "offres.scores_recomputed",
                events.c.account_id == seeker.account_id,
            )
        ).all()
    assert event.payload["rescored"] == 3


def test_at_half_past_midnight_in_paris_the_watch_scores_on_the_paris_day(
    migrated_engine: Engine, seeker: Seeker, monkeypatch: pytest.MonkeyPatch
) -> None:
    days: list[date] = []

    def score(analysis, offer, profile, *, today):  # type: ignore[no-untyped-def]
        days.append(today)
        return real_score(analysis, offer, profile, today=today)

    monkeypatch.setattr("rocky.offres.usecases.score", score)

    watch(migrated_engine, seeker, apec(), now=HALF_PAST_MIDNIGHT)
    with migrated_engine.begin() as connection:
        seeker.editor(connection).update_track(
            seeker.tracks["IA"],
            make_track(name="IA", titles=["Data analyst"], locations=["Paris"]),
        )
    rescore_account(
        SqlStorage(migrated_engine),
        DatabaseProfiles(migrated_engine),
        account_id=seeker.account_id,
        clock=lambda: HALF_PAST_MIDNIGHT,
    )

    assert len(days) > 3 and set(days) == {TODAY}  # recorded, then rescored
