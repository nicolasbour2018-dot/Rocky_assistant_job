"""Use cases of the watch: run it for an account, recover the runs a stopped process left open, rescore.

Decision ``docs/decisions/C6-veille.md``. A run is always closed with a final status and its reason; every offer is
written with its tracks and its scores in one transaction (``record_offer``), so a failure at any point leaves only
whole offers. The network is never used inside a transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import datetime

from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sources.model import JobSource
from rocky.offres.sources.usecases import (
    CollectionReport,
    DetailReport,
    collect,
    complete_descriptions,
)
from rocky.offres.usecases import record_offer, rescore_offer
from rocky.offres.watch.model import (
    Profiles,
    RunCounts,
    RunStatus,
    SourceRun,
    Storage,
    Trigger,
    WatchBusyError,
)
from rocky.offres.watch.rules import (
    INTERRUPTED_REASON,
    NO_TRACK_REASON,
    TECHNICAL_REASON,
    run_status,
    source_runs,
    track_queries,
)
from rocky.profil.model import Profile, Track, TrackStatus
from rocky.system.clock import paris_day
from rocky.system.events import Actor, NewEvent

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]
type SourcesFactory = Callable[[], AbstractContextManager[Sequence[JobSource]]]

# Who starts a run, for the journal: the planner, or the user's gesture.
TRIGGER_ACTORS = {
    Trigger.SCHEDULED: Actor.SYSTEM,
    Trigger.MANUAL: Actor.USER,
    Trigger.CATCH_UP: Actor.USER,
}


@dataclass
class WatchResult:
    """A closed run, with what the sources said (``report`` and ``detail`` are None when no source was asked)."""

    run_id: int
    status: RunStatus = RunStatus.RUNNING
    reason: str | None = None
    counts: RunCounts = field(default_factory=RunCounts)
    sources: list[SourceRun] = field(default_factory=list)
    report: CollectionReport | None = None
    detail: DetailReport | None = None


def active_tracks(profile: Profile | None, name: str | None = None) -> list[Track]:
    """The tracks a watch searches: active ones, or only the one named ``name`` (compared without case)."""
    return [
        track
        for track in (profile.tracks if profile else ())
        if track.status is TrackStatus.ACTIVE
        and (name is None or track.name.casefold() == name.casefold())
    ]


def run_watch(
    storage: Storage,
    profiles: Profiles,
    sources: Sequence[JobSource],
    *,
    account_id: int,
    trigger: Trigger,
    limit: int,
    clock: Clock,
    track_name: str | None = None,
) -> WatchResult:
    """One watch of one account, always closed. Raises ``WatchBusyError`` if the account's watch is running."""
    with storage.lock(account_id) as locked:
        if not locked:
            raise WatchBusyError(account_id)
        with storage.transaction() as store:
            run_id = store.start_run(account_id, trigger, clock())
        result = WatchResult(run_id)
        try:
            _search_and_record(
                result,
                storage,
                profiles,
                sources,
                account_id=account_id,
                limit=limit,
                clock=clock,
                track_name=track_name,
            )
        except Exception:
            logger.exception("watch run %s of account %s failed", run_id, account_id)
            result.status, result.reason = RunStatus.FAILED, TECHNICAL_REASON
        except BaseException:
            # The process is being stopped: the run is closed, then the stop goes on.
            result.status, result.reason = RunStatus.INTERRUPTED, INTERRUPTED_REASON
            raise
        finally:
            _close(storage, result, account_id=account_id, trigger=trigger, now=clock())
        return result


def _search_and_record(
    result: WatchResult,
    storage: Storage,
    profiles: Profiles,
    sources: Sequence[JobSource],
    *,
    account_id: int,
    limit: int,
    clock: Clock,
    track_name: str | None,
) -> None:
    profile = profiles.profile(account_id)
    tracks = active_tracks(profile, track_name)
    if profile is None or not tracks:
        result.status, result.reason = RunStatus.FAILED, NO_TRACK_REASON
        return
    inputs = scoring_inputs(profile)
    plan = track_queries(tracks)
    report = collect(sources, plan.queries, limit)
    result.report = report
    keys = [(offer.source, offer.external_id) for offer in report.offers]
    with storage.transaction() as store:
        known = store.complete_keys(account_id, keys)
    # The detail is asked only for new offers or offers still incomplete (no daily request for a known text).
    detail = complete_descriptions(
        sources,
        [
            offer
            for offer in report.offers
            if (offer.source, offer.external_id) not in known
        ],
    )
    result.detail = detail
    detailed = {(offer.source, offer.external_id): offer for offer in detail.offers}
    counts = RunCounts(found=len(report.offers))
    complete: dict[tuple[str, str], bool] = {}
    for outcome in report.outcomes:
        for found in outcome.offers:
            offer = detailed.get((found.source, found.external_id), found)
            track_ids = plan.tracks_of(
                outcome.found_by.get(found.external_id, ()),
                filters_location=outcome.filters_location,
            )
            try:
                if not track_ids:
                    raise ValueError(f"no track behind offer {found.external_id}")
                now = clock()
                with storage.transaction() as store:
                    recorded = record_offer(
                        store,
                        account_id=account_id,
                        offer=offer,
                        inputs=inputs,
                        origin=Origin.WATCH,
                        track_ids=track_ids,
                        run_id=result.run_id,
                        now=now,
                        today=paris_day(now),
                    )
            except Exception:
                # One offer the analysis, the score or the database cannot handle: logged with its trace, counted,
                # and the others go on. Its transaction is rolled back: nothing of it is written.
                logger.exception(
                    "offer %s/%s of watch run %s not written",
                    found.source,
                    found.external_id,
                    result.run_id,
                )
                counts = _add(counts, not_written=1)
                continue
            counts = _add(
                counts,
                new=int(recorded.created),
                completed=int(recorded.completed),
                below_threshold=int(recorded.score.below_threshold),
                incomplete=int(not recorded.description_complete),
            )
            complete[(found.source, found.external_id)] = recorded.description_complete
    result.counts = counts
    result.sources = source_runs(report, detail, complete)
    result.status, result.reason = run_status(
        report.outcomes, found=counts.found, not_written=counts.not_written
    )


def _add(counts: RunCounts, **increments: int) -> RunCounts:
    values = asdict(counts)
    for name, increment in increments.items():
        values[name] += increment
    return RunCounts(**values)


def _close(
    storage: Storage,
    result: WatchResult,
    *,
    account_id: int,
    trigger: Trigger,
    now: datetime,
) -> None:
    if result.status is RunStatus.RUNNING:
        # Unreachable by design; a run is never left open.
        result.status, result.reason = RunStatus.FAILED, TECHNICAL_REASON
    with storage.transaction() as store:
        store.finish_run(
            result.run_id,
            status=result.status,
            reason=result.reason,
            counts=result.counts,
            sources=result.sources,
            now=now,
        )
        store.append_event(
            NewEvent(
                type="offres.watch_finished",
                actor=TRIGGER_ACTORS[trigger],
                subject_type="watch_run",
                subject_id=str(result.run_id),
                payload={
                    "status": result.status.value,
                    "trigger": trigger.value,
                    "reason": result.reason,
                    **asdict(result.counts),
                },
                account_id=account_id,
            )
        )


def recover_interrupted(storage: Storage, *, clock: Clock) -> list[int]:
    """Close the runs a stopped process left open (their account's lock is free): at the start of the application."""
    with storage.transaction() as store:
        running = store.running_runs()
    closed: list[int] = []
    for run in running:
        with storage.lock(run.account_id) as free:
            if not free:
                continue  # Another process is running it.
            with storage.transaction() as store:
                current = store.get_run(run.id)
                if current is None or current.status is not RunStatus.RUNNING:
                    continue
                store.finish_run(
                    run.id,
                    status=RunStatus.INTERRUPTED,
                    reason=INTERRUPTED_REASON,
                    counts=run.counts,
                    sources=(),
                    now=clock(),
                )
                store.append_event(
                    NewEvent(
                        type="offres.watch_interrupted",
                        actor=Actor.SYSTEM,
                        subject_type="watch_run",
                        subject_id=str(run.id),
                        payload={"started_at": run.started_at.isoformat()},
                        account_id=run.account_id,
                    )
                )
            closed.append(run.id)
    return closed


def rescore_account(
    storage: Storage, profiles: Profiles, *, account_id: int, clock: Clock
) -> int:
    """New scores for every offer of the account scored with other inputs (Q5); the number of offers rescored.

    Raises ``WatchBusyError`` while the account's watch runs (it will be done at the next call).
    """
    with storage.lock(account_id) as locked:
        if not locked:
            raise WatchBusyError(account_id)
        profile = profiles.profile(account_id)
        if profile is None:
            return 0
        inputs = scoring_inputs(profile)
        with storage.transaction() as store:
            stale = store.stale_offers(account_id, inputs.inputs_hash)
        rescored = failed = 0
        for offer in stale:
            now = clock()
            try:
                with storage.transaction() as store:
                    rescore_offer(
                        store, offer, inputs=inputs, now=now, today=paris_day(now)
                    )
            except Exception:
                # The offer keeps its previous score; logged with its trace, counted in the event.
                logger.exception("offer %s not rescored", offer.id)
                failed += 1
                continue
            rescored += 1
        if stale:
            with storage.transaction() as store:
                store.append_event(
                    NewEvent(
                        type="offres.scores_recomputed",
                        actor=Actor.SYSTEM,
                        payload={
                            "rescored": rescored,
                            "failed": failed,
                            "inputs_hash": inputs.inputs_hash,
                        },
                        account_id=account_id,
                    )
                )
        return rescored
