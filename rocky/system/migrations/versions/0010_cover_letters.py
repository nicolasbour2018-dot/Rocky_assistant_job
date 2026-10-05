"""Cover letters and accompanying messages (D4).

Decision ``docs/decisions/D4-lettre-message.md``: the account's generic letter, one version per save, the latest of
each language in force (Q6, Q9, Q17); the letter of an application, one version per validation, the latest of each
language in force, or a row « no letter » (Q4, Q11, Q17); the accompanying message of an application (Q1, Q12).
Every table is appended only.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "generic_letters",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("paragraphs", JSONB(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        # The French letter an English one was translated from.
        sa.Column("source_sha256", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generic_letters")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_generic_letters_profile_id_profiles"),
        ),
        sa.CheckConstraint(
            "language IN ('fr', 'en')", name=op.f("ck_generic_letters_language")
        ),
        sa.CheckConstraint(
            "origin IN ('import', 'edit', 'translation')",
            name=op.f("ck_generic_letters_origin"),
        ),
    )
    op.create_index(
        "ix_generic_letters_profile_id",
        "generic_letters",
        ["profile_id", "language", "id"],
    )

    op.create_table(
        "application_letters",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("paragraphs", JSONB(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("recipient", sa.Text(), nullable=True),
        sa.Column("generic_sha256", sa.Text(), nullable=True),
        sa.Column("checks_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_letters")),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_letters_application_id_applications"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_application_letters_account_id_accounts"),
        ),
        sa.CheckConstraint(
            "kind IN ('letter', 'none')", name=op.f("ck_application_letters_kind")
        ),
        sa.CheckConstraint(
            "language IS NULL OR language IN ('fr', 'en')",
            name=op.f("ck_application_letters_language"),
        ),
        sa.CheckConstraint(
            "(kind = 'letter') = (language IS NOT NULL AND paragraphs IS NOT NULL "
            "AND subject IS NOT NULL AND recipient IS NOT NULL)",
            name=op.f("ck_application_letters_letter_complete"),
        ),
    )
    op.create_index(
        "ix_application_letters_application_id",
        "application_letters",
        ["application_id", "id"],
    )

    op.create_table(
        "application_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        # What the model proposed, kept beside what was validated (D14).
        sa.Column("proposed", sa.Text(), nullable=True),
        sa.Column("signals", JSONB(), nullable=False),
        sa.Column("checks_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_messages")),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_messages_application_id_applications"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_application_messages_account_id_accounts"),
        ),
        sa.CheckConstraint(
            "language IN ('fr', 'en')", name=op.f("ck_application_messages_language")
        ),
        sa.CheckConstraint(
            "origin IN ('generated', 'edited')",
            name=op.f("ck_application_messages_origin"),
        ),
    )
    op.create_index(
        "ix_application_messages_application_id",
        "application_messages",
        ["application_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_messages_application_id", table_name="application_messages"
    )
    op.drop_table("application_messages")
    op.drop_index(
        "ix_application_letters_application_id", table_name="application_letters"
    )
    op.drop_table("application_letters")
    op.drop_index("ix_generic_letters_profile_id", table_name="generic_letters")
    op.drop_table("generic_letters")
