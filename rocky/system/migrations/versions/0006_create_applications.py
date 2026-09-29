"""Create the applications and their changes (appended, never changed).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None

KINDS = "'created', 'stage', 'next_action', 'cancellation'"
STAGES = (
    "'preparing', 'ready', 'prefilled', 'sent', 'in_discussion', 'interview', "
    "'offer', 'rejected', 'withdrawn', 'no_response'"
)
AUTHORS = "'user', 'rule', 'ai'"


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_applications_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["job_offers.id"],
            name=op.f("fk_applications_offer_id_job_offers"),
        ),
        sa.UniqueConstraint(
            "account_id", "offer_id", name=op.f("uq_applications_account_id_offer_id")
        ),
    )
    op.create_table(
        "application_changes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("next_action_label", sa.Text(), nullable=True),
        sa.Column("next_action_due", sa.Date(), nullable=True),
        sa.Column("decision_id", sa.BigInteger(), nullable=True),
        sa.Column("cancels_id", sa.BigInteger(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_changes")),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_changes_application_id_applications"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_application_changes_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["job_decisions.id"],
            name=op.f("fk_application_changes_decision_id_job_decisions"),
        ),
        sa.ForeignKeyConstraint(
            ["cancels_id"],
            ["application_changes.id"],
            name=op.f("fk_application_changes_cancels_id_application_changes"),
        ),
        sa.UniqueConstraint(
            "cancels_id", name=op.f("uq_application_changes_cancels_id")
        ),
        sa.CheckConstraint(
            f"kind IN ({KINDS})", name=op.f("ck_application_changes_kind")
        ),
        sa.CheckConstraint(
            f"stage IS NULL OR stage IN ({STAGES})",
            name=op.f("ck_application_changes_stage"),
        ),
        sa.CheckConstraint(
            f"author IN ({AUTHORS})", name=op.f("ck_application_changes_author")
        ),
        sa.CheckConstraint(
            "(kind IN ('created', 'stage')) = (stage IS NOT NULL)",
            name=op.f("ck_application_changes_stage_with_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'cancellation') = (cancels_id IS NOT NULL)",
            name=op.f("ck_application_changes_cancellation_has_target"),
        ),
        sa.CheckConstraint(
            "(next_action_label IS NULL) = (next_action_due IS NULL)",
            name=op.f("ck_application_changes_next_action_complete"),
        ),
        sa.CheckConstraint(
            "kind <> 'cancellation' OR next_action_label IS NULL",
            name=op.f("ck_application_changes_cancellation_alone"),
        ),
        sa.CheckConstraint(
            "decision_id IS NULL OR kind = 'created'",
            name=op.f("ck_application_changes_decision_on_creation"),
        ),
    )
    op.create_index(
        "ix_application_changes_application_id",
        "application_changes",
        ["application_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_changes_application_id", table_name="application_changes"
    )
    op.drop_table("application_changes")
    op.drop_table("applications")
