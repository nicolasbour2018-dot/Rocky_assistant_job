"""Create the offers: collected offers, the tracks that found them, their current scores, and the watch runs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

ORIGINS = "'watch', 'import'"
TRIGGERS = "'scheduled', 'manual', 'catch_up'"
STATUSES = "'running', 'completed', 'partial', 'failed', 'interrupted'"
OUTCOMES = "'ok', 'refused', 'failed', 'pending_access', 'not_configured'"


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _count(name: str) -> sa.Column[int]:
    return sa.Column(name, sa.Integer(), server_default="0", nullable=False)


def upgrade() -> None:
    op.create_table(
        "job_offers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("description_complete", sa.Boolean(), nullable=False),
        sa.Column("incomplete_reason", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("application_url", sa.Text(), nullable=True),
        sa.Column("contract", sa.Text(), nullable=True),
        sa.Column("remote", sa.Text(), nullable=True),
        sa.Column("salary_text", sa.Text(), nullable=True),
        sa.Column("salary_min", sa.Double(), nullable=True),
        sa.Column("salary_max", sa.Double(), nullable=True),
        sa.Column("salary_currency", sa.Text(), nullable=True),
        sa.Column("salary_period", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("match_key", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        _timestamp("first_seen_at"),
        _timestamp("last_seen_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_offers")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_job_offers_account_id_accounts"),
        ),
        sa.UniqueConstraint(
            "account_id",
            "source",
            "external_id",
            name=op.f("uq_job_offers_account_id_source_external_id"),
        ),
        sa.CheckConstraint(f"origin IN ({ORIGINS})", name=op.f("ck_job_offers_origin")),
    )
    op.create_index("ix_job_offers_account_id_url", "job_offers", ["account_id", "url"])
    op.create_index(
        "ix_job_offers_account_id_match_key", "job_offers", ["account_id", "match_key"]
    )
    op.create_table(
        "watch_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _timestamp("started_at"),
        _timestamp("finished_at", nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        _count("found"),
        _count("new"),
        _count("completed"),
        _count("below_threshold"),
        _count("incomplete"),
        _count("not_written"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watch_runs")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_watch_runs_account_id_accounts"),
        ),
        sa.CheckConstraint(
            f"trigger IN ({TRIGGERS})", name=op.f("ck_watch_runs_trigger")
        ),
        sa.CheckConstraint(
            f"status IN ({STATUSES})", name=op.f("ck_watch_runs_status")
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_watch_runs_closed_when_final"),
        ),
    )
    op.create_index(
        "ix_watch_runs_account_id_started_at",
        "watch_runs",
        ["account_id", "started_at"],
    )
    op.create_table(
        "watch_run_sources",
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("offers", sa.Integer(), nullable=False),
        sa.Column("incomplete", sa.Integer(), nullable=False),
        sa.Column(
            "skipped",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("detail_stopped", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "source", name=op.f("pk_watch_run_sources")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["watch_runs.id"],
            name=op.f("fk_watch_run_sources_run_id_watch_runs"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"outcome IN ({OUTCOMES})", name=op.f("ck_watch_run_sources_outcome")
        ),
    )
    op.create_table(
        "offer_tracks",
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column("found_by", sa.Text(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        _timestamp("found_at"),
        sa.PrimaryKeyConstraint("offer_id", "track_id", name=op.f("pk_offer_tracks")),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["job_offers.id"],
            name=op.f("fk_offer_tracks_offer_id_job_offers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["search_tracks.id"],
            name=op.f("fk_offer_tracks_track_id_search_tracks"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["watch_runs.id"],
            name=op.f("fk_offer_tracks_run_id_watch_runs"),
        ),
        sa.CheckConstraint(
            f"found_by IN ({ORIGINS})", name=op.f("ck_offer_tracks_found_by")
        ),
    )
    op.create_index("ix_offer_tracks_track_id", "offer_tracks", ["track_id"])
    op.create_table(
        "offer_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("display", sa.Integer(), nullable=False),
        sa.Column("below_threshold", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("rules_version", sa.Text(), nullable=False),
        sa.Column("analysis_rules_version", sa.Text(), nullable=False),
        sa.Column("inputs_hash", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp("scored_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offer_scores")),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["job_offers.id"],
            name=op.f("fk_offer_scores_offer_id_job_offers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["search_tracks.id"],
            name=op.f("fk_offer_scores_track_id_search_tracks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "offer_id",
            "track_id",
            name=op.f("uq_offer_scores_offer_id_track_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_offer_scores_track_id", "offer_scores", ["track_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_scores_track_id", table_name="offer_scores")
    op.drop_table("offer_scores")
    op.drop_index("ix_offer_tracks_track_id", table_name="offer_tracks")
    op.drop_table("offer_tracks")
    op.drop_table("watch_run_sources")
    op.drop_index("ix_watch_runs_account_id_started_at", table_name="watch_runs")
    op.drop_table("watch_runs")
    op.drop_index("ix_job_offers_account_id_match_key", table_name="job_offers")
    op.drop_index("ix_job_offers_account_id_url", table_name="job_offers")
    op.drop_table("job_offers")
