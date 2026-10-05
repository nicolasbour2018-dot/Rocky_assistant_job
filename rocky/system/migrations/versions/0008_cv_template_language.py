"""A CV template belongs to one language: one imported CV per language, one active per language (D2, Q33).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "cv_templates",
        sa.Column(
            "language", sa.Text(), nullable=False, server_default=sa.text("'fr'")
        ),
    )
    op.create_check_constraint(
        op.f("ck_cv_templates_language"), "cv_templates", "language IN ('fr', 'en')"
    )
    op.drop_index("uq_cv_templates_one_active", table_name="cv_templates")
    op.create_index(
        "uq_cv_templates_one_active",
        "cv_templates",
        ["profile_id", "language"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("uq_cv_templates_one_active", table_name="cv_templates")
    # Before 0008, one template at most was active per profile: the French one stays.
    op.execute("UPDATE cv_templates SET active = false WHERE language <> 'fr'")
    op.create_index(
        "uq_cv_templates_one_active",
        "cv_templates",
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.drop_constraint(op.f("ck_cv_templates_language"), "cv_templates", type_="check")
    op.drop_column("cv_templates", "language")
