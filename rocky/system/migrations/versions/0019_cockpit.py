"""The cockpit (step G3): the goal of the week of a profile, and the previous visit of the cockpit of an account.

Decision ``docs/decisions/G3-cockpit.md``: the goal is chosen by the user, from 1 to 10, 3 by default (Q9); the
cockpit marks what happened since the previous visit (Q14).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("weekly_goal", sa.SmallInteger(), nullable=False, server_default="3"),
    )
    op.create_check_constraint(
        op.f("ck_profiles_weekly_goal_range"),
        "profiles",
        "weekly_goal BETWEEN 1 AND 10",
    )
    op.add_column(
        "accounts",
        sa.Column("cockpit_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "cockpit_seen_at")
    op.drop_constraint(op.f("ck_profiles_weekly_goal_range"), "profiles", type_="check")
    op.drop_column("profiles", "weekly_goal")
