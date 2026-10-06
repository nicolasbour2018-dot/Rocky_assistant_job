"""Rules of the watch: final status (Q3, Q9), lateness (Q2) and the tracks behind a query (D3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rocky.offres.sources.model import SearchQuery, SourceCode
from rocky.offres.sources.usecases import Outcome, SourceOutcome
from rocky.offres.watch.model import RunCounts, RunStatus, Trigger, WatchRun
from rocky.offres.watch.rules import (
    NO_SOURCE_REASON,
    is_late,
    run_status,
    track_queries,
)
from rocky.profil.model import Track, TrackDraft, TrackStatus
from rocky.system.clock import PARIS
from tests.offres.fakes import NOW, posting


def outcome(
    code: SourceCode, status: Outcome, reason: str | None = None
) -> SourceOutcome:
    offers = (posting("1", source=code.value),) if status is Outcome.OK else ()
    return SourceOutcome(code, status, True, offers, reason=reason)


OK = outcome(SourceCode.APEC, Outcome.OK)


def test_every_asked_source_answering_completes_the_watch() -> None:
    waiting = outcome(SourceCode.FRANCE_TRAVAIL, Outcome.PENDING_ACCESS)
    unconfigured = outcome(SourceCode.ADZUNA, Outcome.NOT_CONFIGURED)

    assert run_status([OK, waiting, unconfigured], found=1, not_written=0) == (
        RunStatus.COMPLETED,
        None,
    )


def test_a_refused_search_makes_the_watch_partial() -> None:
    refused = outcome(SourceCode.LINKEDIN, Outcome.REFUSED, "Refusé (HTTP 999).")

    assert run_status([OK, refused], found=1, not_written=0) == (
        RunStatus.PARTIAL,
        "LinkedIn : Refusée par la plateforme (Refusé (HTTP 999).)",
    )


def test_no_source_answering_fails_the_watch() -> None:
    broken = outcome(SourceCode.APEC, Outcome.FAILED, "HTTP 503.")
    refused = outcome(SourceCode.WTTJ, Outcome.REFUSED)

    status, reason = run_status([broken, refused], found=0, not_written=0)

    assert status is RunStatus.FAILED
    assert (
        reason
        == "Apec : En panne (HTTP 503.) ; Welcome to the Jungle : Refusée par la plateforme"
    )


def test_a_broken_source_that_gave_offers_before_stopping_is_partial() -> None:
    broken = SourceOutcome(
        SourceCode.APEC, Outcome.FAILED, True, (posting("1"),), reason="HTTP 503."
    )

    assert run_status([broken], found=1, not_written=0)[0] is RunStatus.PARTIAL


def test_no_source_to_ask_fails_the_watch() -> None:
    waiting = outcome(SourceCode.FRANCE_TRAVAIL, Outcome.PENDING_ACCESS)

    assert run_status([waiting], found=0, not_written=0) == (
        RunStatus.FAILED,
        NO_SOURCE_REASON,
    )


def test_offers_not_written_make_the_watch_partial_or_failed_when_none_is() -> None:
    assert run_status([OK], found=3, not_written=2)[0] is RunStatus.PARTIAL
    assert run_status([OK], found=2, not_written=2)[0] is RunStatus.FAILED


def run(status: RunStatus, hours_ago: float) -> WatchRun:
    started = NOW - timedelta(hours=hours_ago)
    return WatchRun(
        1, 1, Trigger.SCHEDULED, status, started, started, None, RunCounts()
    )


def test_the_watch_is_late_after_25_hours_without_a_successful_run() -> None:
    assert is_late(None, NOW)
    assert not is_late(run(RunStatus.COMPLETED, 24.5), NOW)
    assert not is_late(run(RunStatus.PARTIAL, 24.5), NOW)
    assert is_late(run(RunStatus.COMPLETED, 25.1), NOW)
    assert is_late(run(RunStatus.FAILED, 1), NOW)


def test_the_watch_is_not_late_on_the_day_the_clocks_go_back() -> None:
    # H3, Q1: from 12 h CEST on Saturday to 12 h CET on Sunday, 25 hours pass between two scheduled watches.
    # Stored and compared in UTC, as the database and the clock give them.
    saturday = datetime(2026, 10, 24, 12, tzinfo=PARIS).astimezone(UTC)
    last = WatchRun(
        1,
        1,
        Trigger.SCHEDULED,
        RunStatus.COMPLETED,
        saturday,
        saturday,
        None,
        RunCounts(),
    )
    sunday = datetime(2026, 10, 25, 11, 30, tzinfo=PARIS).astimezone(UTC)
    assert sunday - saturday == timedelta(hours=24, minutes=30)
    assert not is_late(last, sunday)
    assert is_late(last, saturday + timedelta(hours=25, minutes=1))


def track(track_id: int, titles: tuple[str, ...], locations: tuple[str, ...]) -> Track:
    return Track(
        id=track_id,
        status=TrackStatus.ACTIVE,
        content=TrackDraft(
            name=f"Piste {track_id}", titles=titles, locations=locations
        ),
    )


def test_a_query_stands_for_every_track_that_asks_it() -> None:
    plan = track_queries(
        [
            track(1, ("Data analyst",), ("Paris",)),
            track(2, ("data analyst", "Data scientist"), ("Lyon",)),
        ]
    )

    assert plan.tracks_of(
        [SearchQuery("Data analyst", "Paris")], filters_location=True
    ) == {1}
    assert plan.tracks_of(
        [SearchQuery("Data analyst", "Lyon"), SearchQuery("Data scientist", "Lyon")],
        filters_location=True,
    ) == {2}
    # A source that ignores the place ran "Data analyst" once, for both tracks.
    assert plan.tracks_of([SearchQuery("Data analyst")], filters_location=False) == {
        1,
        2,
    }
