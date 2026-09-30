"""Targeted CV of an application and translation of the profile (D3).

Decision ``docs/decisions/D3-ciblage-traduction.md``: the English stack of a project (Q12); the CV selection of an
application, appended at each adjustment, the latest in force (Q4); the account's glossary (Q6) and its translation
memory (Q14, Q19); the French template an English one was translated from (Q18, Q19).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("stack_en", ARRAY(sa.Text()), nullable=True))
    op.add_column("cv_templates", sa.Column("source_sha256", sa.Text(), nullable=True))

    op.create_table(
        "application_cv_selections",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        # None: back to the rules' proposal.
        sa.Column("layout", JSONB(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_cv_selections")),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_cv_selections_application_id_applications"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_application_cv_selections_account_id_accounts"),
        ),
    )
    op.create_index(
        "ix_application_cv_selections_application_id",
        "application_cv_selections",
        ["application_id", "id"],
    )

    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("fr", sa.Text(), nullable=False),
        sa.Column("en", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_glossary_terms")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_glossary_terms_profile_id_profiles"),
        ),
        sa.UniqueConstraint(
            "profile_id", "term", name=op.f("uq_glossary_terms_profile_id_term")
        ),
    )

    op.create_table(
        "translation_memory",
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("translation", sa.Text(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "profile_id", "source_sha256", name=op.f("pk_translation_memory")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_translation_memory_profile_id_profiles"),
        ),
    )


def downgrade() -> None:
    op.drop_table("translation_memory")
    op.drop_table("glossary_terms")
    op.drop_index(
        "ix_application_cv_selections_application_id",
        table_name="application_cv_selections",
    )
    op.drop_table("application_cv_selections")
    op.drop_column("cv_templates", "source_sha256")
    op.drop_column("projects", "stack_en")
