"""Create the append-only event journal.

Revision ID: 0001
Revises:
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.CheckConstraint(
            "actor IN ('user', 'rule', 'ai', 'system')", name=op.f("ck_events_actor")
        ),
        sa.CheckConstraint(
            "(subject_type IS NULL) = (subject_id IS NULL)",
            name=op.f("ck_events_subject_complete"),
        ),
    )
    op.create_index("ix_events_subject", "events", ["subject_type", "subject_id", "id"])
    # Append-only: the owner role could grant itself back a revoked privilege, not bypass a trigger.
    op.execute(
        """
        CREATE FUNCTION rocky_forbid_event_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'events is append-only: % refused', TG_OP
                USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events"
        " FOR EACH ROW EXECUTE FUNCTION rocky_forbid_event_change()"
    )
    op.execute(
        "CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON events"
        " FOR EACH STATEMENT EXECUTE FUNCTION rocky_forbid_event_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER events_no_truncate ON events")
    op.execute("DROP TRIGGER events_append_only ON events")
    op.execute("DROP FUNCTION rocky_forbid_event_change()")
    op.drop_index("ix_events_subject", table_name="events")
    op.drop_table("events")
