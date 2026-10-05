"""Create the decisions on offers (appended, never changed) and the stored summaries of the offers.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None

KINDS = "'decision', 'cancellation'"
VALUES = "'interested', 'rejected', 'later'"
AUTHORS = "'user', 'rule', 'ai'"


def _timestamp(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "job_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=True),
        sa.Column("displayed_score", sa.Integer(), nullable=True),
        sa.Column("score", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rules_version", sa.Text(), nullable=True),
        sa.Column("inputs_hash", sa.Text(), nullable=True),
        sa.Column("cancels_id", sa.BigInteger(), nullable=True),
        _timestamp("decided_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_decisions")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_job_decisions_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["job_offers.id"],
            name=op.f("fk_job_decisions_offer_id_job_offers"),
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["search_tracks.id"],
            name=op.f("fk_job_decisions_track_id_search_tracks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cancels_id"],
            ["job_decisions.id"],
            name=op.f("fk_job_decisions_cancels_id_job_decisions"),
        ),
        sa.UniqueConstraint("cancels_id", name=op.f("uq_job_decisions_cancels_id")),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f("ck_job_decisions_kind")),
        sa.CheckConstraint(
            f"value IS NULL OR value IN ({VALUES})", name=op.f("ck_job_decisions_value")
        ),
        sa.CheckConstraint(
            f"author IN ({AUTHORS})", name=op.f("ck_job_decisions_author")
        ),
        sa.CheckConstraint(
            "(kind = 'decision') = (value IS NOT NULL AND score IS NOT NULL)",
            name=op.f("ck_job_decisions_decision_has_value"),
        ),
        sa.CheckConstraint(
            "(kind = 'cancellation') = (cancels_id IS NOT NULL)",
            name=op.f("ck_job_decisions_cancellation_has_target"),
        ),
    )
    op.create_index(
        "ix_job_decisions_account_id_offer_id",
        "job_decisions",
        ["account_id", "offer_id", "id"],
    )
    op.create_table(
        "offer_summaries",
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("description_hash", sa.Text(), nullable=False),
        sa.Column("missions", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("offer_id", name=op.f("pk_offer_summaries")),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["job_offers.id"],
            name=op.f("fk_offer_summaries_offer_id_job_offers"),
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("offer_summaries")
    op.drop_index("ix_job_decisions_account_id_offer_id", table_name="job_decisions")
    op.drop_table("job_decisions")
