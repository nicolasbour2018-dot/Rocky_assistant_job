"""Rules of the watch: no I/O. Queries of the tracks, the tracks behind a query, the final status of a run, lateness."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from rocky.offres.sources.model import SOURCE_LABELS, SearchQuery
from rocky.offres.sources.rules import queries_for_track, query_key
from rocky.offres.sources.usecases import (
    OUTCOME_LABELS,
    CollectionReport,
    DetailReport,
    Outcome,
    SourceOutcome,
)
from rocky.offres.watch.model import (
    SUCCESSFUL,
    RunStatus,
    SourceRun,
    WatchRun,
)
from rocky.profil.model import Track

# Q2: past this delay without a successful run, the watch is late and a catch-up is proposed.
LATE_AFTER = timedelta(hours=24)
# Outcomes that do not count as a failure (Q3): the source was not asked.
NOT_ASKED = frozenset({Outcome.PENDING_ACCESS, Outcome.NOT_CONFIGURED})
FAILURES = frozenset({Outcome.REFUSED, Outcome.FAILED})

NO_TRACK_REASON = (
    "Aucune piste active : ajoute ou reprends une piste pour lancer la veille."
)
NO_SOURCE_REASON = (
    "Aucune source interrogeable (toutes en attente d'accès ou non configurées)."
)
NOT_WRITTEN_REASON = (
    "{count} offre{s} non écrite{s} après une erreur technique (trace dans le journal de "
    "l'application)."
)
TECHNICAL_REASON = (
    "Erreur technique pendant la veille (trace dans le journal de l'application)."
)
INTERRUPTED_REASON = "La veille a été arrêtée avant la fin (arrêt de l'application)."


@dataclass(frozen=True)
class TrackQueries:
    """The queries of the active tracks, and which tracks each query stands for (D3)."""

    queries: tuple[SearchQuery, ...]
    # (query key, filters_location) -> track ids.
    _tracks: dict[tuple[tuple[str, str], bool], frozenset[int]]

    def tracks_of(
        self, queries: Iterable[SearchQuery], *, filters_location: bool
    ) -> frozenset[int]:
        """The tracks behind the queries a source ran (a source that ignores places ran one query per title)."""
        found: set[int] = set()
        for query in queries:
            found |= self._tracks.get(
                (query_key(query, filters_location=filters_location), filters_location),
                frozenset(),
            )
        return frozenset(found)


def track_queries(tracks: Sequence[Track]) -> TrackQueries:
    queries: list[SearchQuery] = []
    owners: dict[tuple[tuple[str, str], bool], set[int]] = {}
    for track in tracks:
        for query in queries_for_track(track.content.titles, track.content.locations):
            queries.append(query)
            for filters_location in (True, False):
                key = (
                    query_key(query, filters_location=filters_location),
                    filters_location,
                )
                owners.setdefault(key, set()).add(track.id)
    return TrackQueries(
        tuple(queries), {key: frozenset(ids) for key, ids in owners.items()}
    )


def run_status(
    outcomes: Sequence[SourceOutcome], *, found: int, not_written: int
) -> tuple[RunStatus, str | None]:
    """The final status of a run that went through the sources, and its reason (Q3, Q9).

    Failed: no source could be asked, every asked source was refused or broken without giving anything, or every
    collected offer failed to be written. Partial: a search was refused or broken, or an offer could not be written.
    A refused detail and a skipped query are shown, never a failure.
    """
    asked = [outcome for outcome in outcomes if outcome.status not in NOT_ASKED]
    if not asked:
        return RunStatus.FAILED, NO_SOURCE_REASON
    broken = [outcome for outcome in asked if outcome.status in FAILURES]
    reasons = [_source_reason(outcome) for outcome in broken]
    if not_written:
        s = "s" if not_written > 1 else ""
        reasons.append(NOT_WRITTEN_REASON.format(count=not_written, s=s))
    reason = " ; ".join(reasons) or None
    if (len(broken) == len(asked) and found == 0) or (found and not_written == found):
        return RunStatus.FAILED, reason
    if reasons:
        return RunStatus.PARTIAL, reason
    return RunStatus.COMPLETED, None


def _source_reason(outcome: SourceOutcome) -> str:
    label = f"{SOURCE_LABELS[outcome.source]} : {OUTCOME_LABELS[outcome.status]}"
    return f"{label} ({outcome.reason})" if outcome.reason else label


def source_runs(
    report: CollectionReport,
    detail: DetailReport,
    completed: dict[tuple[str, str], bool],
) -> list[SourceRun]:
    """What each source gave, for the record of the run. ``completed``: stored description completeness by offer key
    (an offer not written keeps the completeness it was collected with)."""
    return [
        SourceRun(
            source=outcome.source.value,
            outcome=outcome.status,
            reason=outcome.reason,
            offers=len(outcome.offers),
            incomplete=sum(
                not completed.get(
                    (offer.source, offer.external_id), offer.description_complete
                )
                for offer in outcome.offers
            ),
            skipped=tuple(
                (skipped.query.title, skipped.query.location, skipped.reason)
                for skipped in outcome.skipped
            ),
            detail_stopped=detail.stopped.get(outcome.source),
        )
        for outcome in report.outcomes
    ]


def is_late(last_successful: WatchRun | None, now: datetime) -> bool:
    """Q2: no successful run in the last 24 hours (a run in progress is not late: it is shown as running)."""
    if last_successful is None or last_successful.status not in SUCCESSFUL:
        return True
    return now - last_successful.started_at > LATE_AFTER
