"""SQL access of the offers: the only place where the tables of the module ``offres`` are queried.

Decision ``docs/decisions/C6-veille.md``: an offer, its tracks and its scores are written in the caller's transaction,
as one unit; ``SqlStorage`` opens those transactions and holds the watch lock of an account.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Connection,
    Date,
    DateTime,
    Double,
    Engine,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Row,
    Table,
    Text,
    UniqueConstraint,
    and_,
    delete,
    exists,
    insert,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rocky.offres.analysis.usecases import Summary
from rocky.offres.decisions import (
    Author,
    Decision,
    DecisionKind,
    DecisionRow,
    DecisionValue,
)
from rocky.offres.model import OfferHeading, Origin, StoredOffer, StoredSummary
from rocky.offres.scoring.model import (
    THRESHOLD,
    ConfidenceLevel,
    Score,
    TrackScore,
)
from rocky.offres.screen import ListedOffer, TrackMark
from rocky.offres.sources.model import CollectedOffer
from rocky.offres.sources.usecases import Outcome
from rocky.offres.watch.model import (
    RunCounts,
    RunStatus,
    SourceRun,
    Trigger,
    WatchRun,
)
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event

# First key of the advisory locks of the watch (the second is the account): no other lock of Rocky uses it.
WATCH_LOCK_SPACE = 6006


def _in(column: str, values: type[StrEnum]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def _timestamp(name: str, *, nullable: bool = False) -> Column[Any]:
    return Column(name, DateTime(timezone=True), nullable=nullable)


job_offers = Table(
    "job_offers",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    # The facts of the posting, as collected (``CollectedOffer``): the analysis and the score are recomputed from them.
    Column("source", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("description_complete", Boolean, nullable=False),
    Column("incomplete_reason", Text),
    Column("company", Text),
    Column("location", Text),
    Column("country", Text),
    Column("application_url", Text),
    Column("contract", Text),
    Column("remote", Text),
    Column("salary_text", Text),
    Column("salary_min", Double),
    Column("salary_max", Double),
    Column("salary_currency", Text),
    Column("salary_period", Text),
    Column("sector", Text),
    Column("published_on", Date),
    Column("deadline", Date),
    # Title and employer in comparison form: "vue aussi sur …" between two sites (Q4).
    Column("match_key", Text),
    Column("origin", Text, nullable=False),
    _timestamp("first_seen_at"),
    _timestamp("last_seen_at"),
    UniqueConstraint("account_id", "source", "external_id"),
    CheckConstraint(_in("origin", Origin), name="origin"),
    Index("ix_job_offers_account_id_url", "account_id", "url"),
    Index("ix_job_offers_account_id_match_key", "account_id", "match_key"),
)

watch_runs = Table(
    "watch_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("trigger", Text, nullable=False),
    Column("status", Text, nullable=False),
    _timestamp("started_at"),
    _timestamp("finished_at", nullable=True),
    Column("reason", Text),
    Column("found", Integer, nullable=False, server_default="0"),
    Column("new", Integer, nullable=False, server_default="0"),
    Column("completed", Integer, nullable=False, server_default="0"),
    Column("below_threshold", Integer, nullable=False, server_default="0"),
    Column("incomplete", Integer, nullable=False, server_default="0"),
    Column("not_written", Integer, nullable=False, server_default="0"),
    CheckConstraint(_in("trigger", Trigger), name="trigger"),
    CheckConstraint(_in("status", RunStatus), name="status"),
    # A run is closed exactly when it has a final status.
    CheckConstraint(
        "(status = 'running') = (finished_at IS NULL)", name="closed_when_final"
    ),
    Index("ix_watch_runs_account_id_started_at", "account_id", "started_at"),
)

watch_run_sources = Table(
    "watch_run_sources",
    metadata,
    Column(
        "run_id",
        BigInteger,
        ForeignKey("watch_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("reason", Text),
    Column("offers", Integer, nullable=False),
    Column("incomplete", Integer, nullable=False),
    # Skipped queries: [title, location, reason].
    Column("skipped", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("detail_stopped", Text),
    PrimaryKeyConstraint("run_id", "source"),
    CheckConstraint(_in("outcome", Outcome), name="outcome"),
)

offer_tracks = Table(
    "offer_tracks",
    metadata,
    Column(
        "offer_id",
        BigInteger,
        ForeignKey("job_offers.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # RESTRICT: a track an offer is linked to cannot be deleted, only archived (decision B5, Q21).
    Column(
        "track_id",
        BigInteger,
        ForeignKey("search_tracks.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("found_by", Text, nullable=False),
    Column("run_id", BigInteger, ForeignKey("watch_runs.id")),
    _timestamp("found_at"),
    PrimaryKeyConstraint("offer_id", "track_id"),
    CheckConstraint(_in("found_by", Origin), name="found_by"),
    Index("ix_offer_tracks_track_id", "track_id"),
)

offer_scores = Table(
    "offer_scores",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "offer_id",
        BigInteger,
        ForeignKey("job_offers.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # None: the account had no active track (the score of the offer alone, C4 Q20). Scores are recomputed: a deleted
    # track takes its scores with it.
    Column("track_id", BigInteger, ForeignKey("search_tracks.id", ondelete="CASCADE")),
    # Order of the tracks in the profile: the first of the best is the score of the offer.
    Column("position", Integer, nullable=False),
    Column("value", Double, nullable=False),
    Column("display", Integer, nullable=False),
    Column("below_threshold", Boolean, nullable=False),
    Column("confidence", Text, nullable=False),
    Column("rules_version", Text, nullable=False),
    Column("analysis_rules_version", Text, nullable=False),
    Column("inputs_hash", Text, nullable=False),
    # ``TrackScore`` in its stored form: components, evidence, caps and features (D14).
    Column("detail", JSONB, nullable=False),
    _timestamp("scored_at"),
    UniqueConstraint("offer_id", "track_id", postgresql_nulls_not_distinct=True),
    Index("ix_offer_scores_track_id", "track_id"),
)

job_decisions = Table(
    "job_decisions",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("offer_id", BigInteger, ForeignKey("job_offers.id"), nullable=False),
    # Appended only (C7, Q8): a change is a new decision, « Annuler » a cancellation row.
    Column("kind", Text, nullable=False),
    Column("value", Text),
    Column("reasons", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("note", Text),
    Column("author", Text, nullable=False),
    # The track whose score was shown, and a copy of the whole score at that moment (Q11, D14).
    Column("track_id", BigInteger, ForeignKey("search_tracks.id", ondelete="SET NULL")),
    Column("displayed_score", Integer),
    Column("score", JSONB),
    Column("rules_version", Text),
    Column("inputs_hash", Text),
    Column("cancels_id", BigInteger, ForeignKey("job_decisions.id")),
    _timestamp("decided_at"),
    UniqueConstraint("cancels_id"),
    CheckConstraint(_in("kind", DecisionKind), name="kind"),
    CheckConstraint("value IS NULL OR " + _in("value", DecisionValue), name="value"),
    CheckConstraint(_in("author", Author), name="author"),
    CheckConstraint(
        "(kind = 'decision') = (value IS NOT NULL AND score IS NOT NULL)",
        name="decision_has_value",
    ),
    CheckConstraint(
        "(kind = 'cancellation') = (cancels_id IS NOT NULL)",
        name="cancellation_has_target",
    ),
    Index("ix_job_decisions_account_id_offer_id", "account_id", "offer_id", "id"),
)

offer_summaries = Table(
    "offer_summaries",
    metadata,
    Column(
        "offer_id",
        BigInteger,
        ForeignKey("job_offers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Fingerprint of the description summarised: a changed description makes the summary stale (C7, Q6).
    Column("description_hash", Text, nullable=False),
    Column("missions", Text, nullable=False),
    Column("context", Text, nullable=False),
    Column("profile", Text, nullable=False),
    _timestamp("created_at"),
)

FACT_COLUMNS = (
    "title",
    "description",
    "description_complete",
    "incomplete_reason",
    "company",
    "location",
    "country",
    "application_url",
    "contract",
    "remote",
    "salary_text",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "sector",
    "published_on",
    "deadline",
)


class SqlStore:
    """``Store`` (offers and runs) on a connection already inside a transaction; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    # Offers

    def find(self, account_id: int, offer: CollectedOffer) -> StoredOffer | None:
        same = or_(
            and_(
                job_offers.c.source == offer.source,
                job_offers.c.external_id == offer.external_id,
            ),
            job_offers.c.url == offer.url,
        )
        row = self._conn.execute(
            select(job_offers)
            .where(job_offers.c.account_id == account_id, same)
            # The same source and identifier first, then the oldest offer at this address.
            .order_by(
                (
                    (job_offers.c.source == offer.source)
                    & (job_offers.c.external_id == offer.external_id)
                ).desc(),
                job_offers.c.id,
            )
            .limit(1)
        ).one_or_none()
        return None if row is None else _stored(row)

    def get(self, offer_id: int) -> StoredOffer | None:
        row = self._conn.execute(
            select(job_offers).where(job_offers.c.id == offer_id)
        ).one_or_none()
        return None if row is None else _stored(row)

    def insert(
        self,
        account_id: int,
        offer: CollectedOffer,
        *,
        origin: Origin,
        match_key: str | None,
        now: datetime,
    ) -> int:
        statement = (
            insert(job_offers)
            .values(
                account_id=account_id,
                source=offer.source,
                external_id=offer.external_id,
                url=offer.url,
                match_key=match_key,
                origin=origin.value,
                first_seen_at=now,
                last_seen_at=now,
                **_facts(offer),
            )
            .returning(job_offers.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def update(
        self,
        offer_id: int,
        offer: CollectedOffer,
        *,
        match_key: str | None,
        now: datetime,
        seen: bool = True,
    ) -> None:
        seen_at = {"last_seen_at": now} if seen else {}
        self._conn.execute(
            update(job_offers)
            .where(job_offers.c.id == offer_id)
            .values(match_key=match_key, **seen_at, **_facts(offer))
        )

    def mark_seen(self, offer_id: int, now: datetime) -> None:
        self._conn.execute(
            update(job_offers)
            .where(job_offers.c.id == offer_id)
            .values(last_seen_at=now)
        )

    def link_tracks(
        self,
        offer_id: int,
        track_ids: Iterable[int],
        *,
        found_by: Origin,
        run_id: int | None,
        now: datetime,
    ) -> None:
        rows = [
            {
                "offer_id": offer_id,
                "track_id": track_id,
                "found_by": found_by.value,
                "run_id": run_id,
                "found_at": now,
            }
            for track_id in sorted(set(track_ids))
        ]
        if rows:
            self._conn.execute(pg_insert(offer_tracks).on_conflict_do_nothing(), rows)

    def track_ids(self, offer_id: int) -> set[int]:
        return set(
            self._conn.execute(
                select(offer_tracks.c.track_id).where(
                    offer_tracks.c.offer_id == offer_id
                )
            ).scalars()
        )

    def replace_scores(
        self, offer_id: int, score: Score, *, inputs_hash: str, now: datetime
    ) -> None:
        self._conn.execute(
            delete(offer_scores).where(offer_scores.c.offer_id == offer_id)
        )
        self._conn.execute(
            insert(offer_scores),
            [
                {
                    "offer_id": offer_id,
                    "track_id": track.track_id,
                    "position": position,
                    "value": track.value,
                    "display": track.display,
                    "below_threshold": track.display < THRESHOLD,
                    "confidence": track.confidence.level.value,
                    "rules_version": score.rules_version,
                    "analysis_rules_version": score.analysis_rules_version,
                    "inputs_hash": inputs_hash,
                    "detail": asdict(track),
                    "scored_at": now,
                }
                for position, track in enumerate(score.tracks)
            ],
        )

    def current_score(self, offer_id: int) -> Score | None:
        """The current scores of the offer, in the order of the tracks; None when it has none."""
        rows = self._conn.execute(
            select(offer_scores)
            .where(offer_scores.c.offer_id == offer_id)
            .order_by(offer_scores.c.position)
        ).all()
        if not rows:
            return None
        return Score(
            rules_version=rows[0].rules_version,
            analysis_rules_version=rows[0].analysis_rules_version,
            tracks=tuple(TrackScore.from_json(row.detail) for row in rows),
        )

    def current_inputs_hash(self, offer_id: int) -> str | None:
        return self._conn.execute(
            select(offer_scores.c.inputs_hash)
            .where(offer_scores.c.offer_id == offer_id)
            .order_by(offer_scores.c.position)
            .limit(1)
        ).scalar_one_or_none()

    def stale_offers(self, account_id: int, inputs_hash: str) -> list[StoredOffer]:
        current = exists().where(
            offer_scores.c.offer_id == job_offers.c.id,
            offer_scores.c.inputs_hash == inputs_hash,
        )
        rows = self._conn.execute(
            select(job_offers)
            .where(job_offers.c.account_id == account_id, ~current)
            .order_by(job_offers.c.id)
        ).all()
        return [_stored(row) for row in rows]

    def complete_keys(
        self, account_id: int, keys: Iterable[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        wanted = list(set(keys))
        if not wanted:
            return set()
        rows = self._conn.execute(
            select(job_offers.c.source, job_offers.c.external_id).where(
                job_offers.c.account_id == account_id,
                job_offers.c.description_complete,
                tuple_(job_offers.c.source, job_offers.c.external_id).in_(wanted),
            )
        ).all()
        return {(row.source, row.external_id) for row in rows}

    def unscored_or_orphan_offers(self, account_id: int) -> list[int]:
        """Offers breaking the unit (exit criterion of C6): without any score, or found by the watch without any track.

        Always empty; kept as a check for the tests and the real measure.
        """
        scored = exists().where(offer_scores.c.offer_id == job_offers.c.id)
        linked = exists().where(offer_tracks.c.offer_id == job_offers.c.id)
        rows = self._conn.execute(
            select(job_offers.c.id)
            .where(
                job_offers.c.account_id == account_id,
                or_(
                    ~scored,
                    and_(job_offers.c.origin == Origin.WATCH.value, ~linked),
                ),
            )
            .order_by(job_offers.c.id)
        ).scalars()
        return list(rows)

    # The offers screen (C7)

    def offer_of(self, account_id: int, offer_id: int) -> StoredOffer | None:
        """The offer, only when it belongs to the account."""
        row = self._conn.execute(
            select(job_offers).where(
                job_offers.c.id == offer_id, job_offers.c.account_id == account_id
            )
        ).one_or_none()
        return None if row is None else _stored(row)

    def offers_of(self, account_id: int, offer_ids: Iterable[int]) -> list[StoredOffer]:
        """The account's offers among ``offer_ids``."""
        ids = list(offer_ids)
        if not ids:
            return []
        rows = self._conn.execute(
            select(job_offers).where(
                job_offers.c.account_id == account_id, job_offers.c.id.in_(ids)
            )
        )
        return [_stored(row) for row in rows]

    def headings(
        self, account_id: int, offer_ids: Iterable[int]
    ) -> dict[int, OfferHeading]:
        """Title, employer, place and links of the account's offers among ``offer_ids``."""
        ids = list(offer_ids)
        if not ids:
            return {}
        rows = self._conn.execute(
            select(
                job_offers.c.id,
                job_offers.c.title,
                job_offers.c.company,
                job_offers.c.location,
                job_offers.c.url,
                job_offers.c.application_url,
            ).where(job_offers.c.account_id == account_id, job_offers.c.id.in_(ids))
        )
        return {
            row.id: OfferHeading(
                row.id,
                row.title,
                row.company,
                row.location,
                row.url,
                row.application_url,
            )
            for row in rows
        }

    def listed_offers(self, account_id: int) -> list[ListedOffer]:
        """Every offer of the account as the list and the triage need it: facts shown, tracks and current scores."""
        marks: dict[int, list[TrackMark]] = {}
        for row in self._conn.execute(
            select(
                offer_scores.c.offer_id,
                offer_scores.c.track_id,
                offer_scores.c.position,
                offer_scores.c.value,
                offer_scores.c.display,
                offer_scores.c.confidence,
            )
            .join(job_offers, job_offers.c.id == offer_scores.c.offer_id)
            .where(job_offers.c.account_id == account_id)
            .order_by(offer_scores.c.offer_id, offer_scores.c.position)
        ):
            marks.setdefault(row.offer_id, []).append(
                TrackMark(
                    track_id=row.track_id,
                    position=row.position,
                    value=row.value,
                    display=row.display,
                    confidence=ConfidenceLevel(row.confidence),
                )
            )
        linked: dict[int, set[int]] = {}
        for row in self._conn.execute(
            select(offer_tracks.c.offer_id, offer_tracks.c.track_id)
            .join(job_offers, job_offers.c.id == offer_tracks.c.offer_id)
            .where(job_offers.c.account_id == account_id)
        ):
            linked.setdefault(row.offer_id, set()).add(row.track_id)
        rows = self._conn.execute(
            select(
                job_offers.c.id,
                job_offers.c.title,
                job_offers.c.company,
                job_offers.c.location,
                job_offers.c.source,
                job_offers.c.published_on,
                job_offers.c.description_complete,
                job_offers.c.match_key,
            )
            .where(job_offers.c.account_id == account_id)
            .order_by(job_offers.c.id)
        ).all()
        return [
            ListedOffer(
                id=row.id,
                title=row.title,
                company=row.company,
                location=row.location,
                source=row.source,
                published_on=row.published_on,
                description_complete=row.description_complete,
                match_key=row.match_key,
                track_ids=frozenset(linked.get(row.id, ())),
                marks=tuple(marks[row.id]),
            )
            # An offer always has a score (C6); one being written right now is left for the next request.
            for row in rows
            if row.id in marks
        ]

    def same_posting(
        self, account_id: int, offer_id: int, key: str | None
    ) -> list[tuple[int, str]]:
        """Other offers of the account with the same comparison key (« vue aussi sur … », C6 Q4): id and source."""
        if key is None:
            return []
        rows = self._conn.execute(
            select(job_offers.c.id, job_offers.c.source)
            .where(
                job_offers.c.account_id == account_id,
                job_offers.c.match_key == key,
                job_offers.c.id != offer_id,
            )
            .order_by(job_offers.c.id)
        ).all()
        return [(row.id, row.source) for row in rows]

    def decision_rows(
        self, account_id: int, offer_id: int | None = None
    ) -> list[DecisionRow]:
        """The decisions and cancellations of the account (of one offer when given), in the order they were made."""
        statement = select(job_decisions).where(
            job_decisions.c.account_id == account_id
        )
        if offer_id is not None:
            statement = statement.where(job_decisions.c.offer_id == offer_id)
        rows = self._conn.execute(statement.order_by(job_decisions.c.id)).all()
        return [_decision_row(row) for row in rows]

    def insert_decision(
        self,
        account_id: int,
        offer_id: int,
        decision: Decision,
        *,
        author: Author,
        track: TrackScore,
        score: Score,
        inputs_hash: str | None,
        now: datetime,
    ) -> int:
        statement = (
            insert(job_decisions)
            .values(
                account_id=account_id,
                offer_id=offer_id,
                kind=DecisionKind.DECISION.value,
                value=decision.value.value,
                reasons=list(decision.reasons),
                note=decision.note,
                author=author.value,
                track_id=track.track_id,
                displayed_score=track.display,
                score=score.to_json(),
                rules_version=score.rules_version,
                inputs_hash=inputs_hash,
                decided_at=now,
            )
            .returning(job_decisions.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def insert_cancellation(
        self,
        account_id: int,
        cancelled: DecisionRow,
        *,
        author: Author,
        now: datetime,
    ) -> DecisionRow:
        statement = (
            insert(job_decisions)
            .values(
                account_id=account_id,
                offer_id=cancelled.offer_id,
                kind=DecisionKind.CANCELLATION.value,
                author=author.value,
                cancels_id=cancelled.id,
                decided_at=now,
            )
            .returning(job_decisions)
        )
        return _decision_row(self._conn.execute(statement).one())

    def summary(self, offer_id: int) -> StoredSummary | None:
        row = self._conn.execute(
            select(offer_summaries).where(offer_summaries.c.offer_id == offer_id)
        ).one_or_none()
        if row is None:
            return None
        return StoredSummary(
            description_hash=row.description_hash,
            summary=Summary(
                missions=row.missions, context=row.context, profile=row.profile
            ),
        )

    def save_summary(
        self, offer_id: int, summary: StoredSummary, now: datetime
    ) -> None:
        values = {
            "description_hash": summary.description_hash,
            "missions": summary.summary.missions,
            "context": summary.summary.context,
            "profile": summary.summary.profile,
            "created_at": now,
        }
        self._conn.execute(
            pg_insert(offer_summaries)
            .values(offer_id=offer_id, **values)
            .on_conflict_do_update(index_elements=["offer_id"], set_=values)
        )

    # Runs

    def start_run(self, account_id: int, trigger: Trigger, now: datetime) -> int:
        statement = (
            insert(watch_runs)
            .values(
                account_id=account_id,
                trigger=trigger.value,
                status=RunStatus.RUNNING.value,
                started_at=now,
            )
            .returning(watch_runs.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def finish_run(
        self,
        run_id: int,
        *,
        status: RunStatus,
        reason: str | None,
        counts: RunCounts,
        sources: Sequence[SourceRun],
        now: datetime,
    ) -> None:
        if status is RunStatus.RUNNING:
            raise ValueError("a finished run needs a final status")
        self._conn.execute(
            update(watch_runs)
            .where(watch_runs.c.id == run_id, watch_runs.c.status == "running")
            .values(
                status=status.value, reason=reason, finished_at=now, **asdict(counts)
            )
        )
        if sources:
            self._conn.execute(
                insert(watch_run_sources),
                [
                    {
                        "run_id": run_id,
                        "source": item.source,
                        "outcome": item.outcome.value,
                        "reason": item.reason,
                        "offers": item.offers,
                        "incomplete": item.incomplete,
                        "skipped": [list(skipped) for skipped in item.skipped],
                        "detail_stopped": item.detail_stopped,
                    }
                    for item in sources
                ],
            )

    def running_runs(self) -> list[WatchRun]:
        rows = self._conn.execute(
            select(watch_runs)
            .where(watch_runs.c.status == RunStatus.RUNNING.value)
            .order_by(watch_runs.c.id)
        ).all()
        return [_run(row) for row in rows]

    def get_run(self, run_id: int) -> WatchRun | None:
        row = self._conn.execute(
            select(watch_runs).where(watch_runs.c.id == run_id)
        ).one_or_none()
        return None if row is None else _run(row)

    def last_run(self, account_id: int) -> WatchRun | None:
        return self._last(account_id, None)

    def last_successful_run(self, account_id: int) -> WatchRun | None:
        return self._last(
            account_id, (RunStatus.COMPLETED.value, RunStatus.PARTIAL.value)
        )

    def _last(
        self, account_id: int, statuses: tuple[str, ...] | None
    ) -> WatchRun | None:
        statement = select(watch_runs).where(watch_runs.c.account_id == account_id)
        if statuses is not None:
            statement = statement.where(watch_runs.c.status.in_(statuses))
        row = self._conn.execute(
            statement.order_by(
                watch_runs.c.started_at.desc(), watch_runs.c.id.desc()
            ).limit(1)
        ).one_or_none()
        return None if row is None else _run(row)

    def source_runs(self, run_id: int) -> list[SourceRun]:
        rows = self._conn.execute(
            select(watch_run_sources).where(watch_run_sources.c.run_id == run_id)
        ).all()
        return [
            SourceRun(
                source=row.source,
                outcome=Outcome(row.outcome),
                reason=row.reason,
                offers=row.offers,
                incomplete=row.incomplete,
                skipped=tuple(
                    (title, location, reason) for title, location, reason in row.skipped
                ),
                detail_stopped=row.detail_stopped,
            )
            for row in rows
        ]

    def append_event(self, event: NewEvent) -> None:
        append_event(self._conn, event)


class SqlStorage:
    """``Storage`` on an engine: one transaction per call, and the advisory lock of an account's watch."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[SqlStore]:
        with self._engine.begin() as connection:
            yield SqlStore(connection)

    @contextmanager
    def lock(self, account_id: int) -> Iterator[bool]:
        """A session lock on its own connection, held while open: a killed process releases it with its session."""
        with self._engine.connect() as connection:
            locked = bool(
                connection.execute(
                    text(
                        "SELECT pg_try_advisory_lock("
                        "CAST(:space AS integer), CAST(:account AS integer))"
                    ),
                    {"space": WATCH_LOCK_SPACE, "account": account_id},
                ).scalar_one()
            )
            connection.commit()
            try:
                yield locked
            finally:
                if locked:
                    connection.execute(
                        text(
                            "SELECT pg_advisory_unlock("
                            "CAST(:space AS integer), CAST(:account AS integer))"
                        ),
                        {"space": WATCH_LOCK_SPACE, "account": account_id},
                    )
                    connection.commit()


def _facts(offer: CollectedOffer) -> dict[str, Any]:
    return {name: getattr(offer, name) for name in FACT_COLUMNS}


def _stored(row: Row[Any]) -> StoredOffer:
    return StoredOffer(
        id=row.id,
        account_id=row.account_id,
        offer=CollectedOffer(
            source=row.source,
            external_id=row.external_id,
            url=row.url,
            **{name: getattr(row, name) for name in FACT_COLUMNS},
        ),
        origin=Origin(row.origin),
    )


def _decision_row(row: Row[Any]) -> DecisionRow:
    kind = DecisionKind(row.kind)
    return DecisionRow(
        id=row.id,
        offer_id=row.offer_id,
        kind=kind,
        decided_at=row.decided_at,
        decision=Decision(DecisionValue(row.value), tuple(row.reasons), row.note)
        if kind is DecisionKind.DECISION
        else None,
        cancels=row.cancels_id,
    )


def _run(row: Row[Any]) -> WatchRun:
    return WatchRun(
        id=row.id,
        account_id=row.account_id,
        trigger=Trigger(row.trigger),
        status=RunStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        reason=row.reason,
        counts=RunCounts(
            found=row.found,
            new=row.new,
            completed=row.completed,
            below_threshold=row.below_threshold,
            incomplete=row.incomplete,
            not_written=row.not_written,
        ),
    )
