"""Revisions of the documents, sendings and prefilled forms of an application (D5).

Decision ``docs/decisions/D5-revisions-envoi.md``: each generated PDF is a revision stored under its hash (Q2); a
sending documents one stage change « Envoyée » with its date, its channel and the exact revisions sent (Q3, Q5); a
prefilled form keeps what the workstation was given and what it reported (Q1, Q4, Q6). Every table is appended only.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None

CHANNELS = (
    "'company_site', 'linkedin', 'indeed', 'welcome_to_the_jungle', 'apec', "
    "'hellowork', 'france_travail', 'email', 'other'"
)


def _owner(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f(f"fk_{table}_application_id_applications"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f(f"fk_{table}_account_id_accounts"),
        ),
    ]


def _documents(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["cv_revision_id"],
            ["document_revisions.id"],
            name=op.f(f"fk_{table}_cv_revision_id_document_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["letter_revision_id"],
            ["document_revisions.id"],
            name=op.f(f"fk_{table}_letter_revision_id_document_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["application_messages.id"],
            name=op.f(f"fk_{table}_message_id_application_messages"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "document_revisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("inputs_sha256", sa.Text(), nullable=False),
        sa.Column("letter_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_revisions")),
        *_owner("document_revisions"),
        sa.ForeignKeyConstraint(
            ["letter_id"],
            ["application_letters.id"],
            name=op.f("fk_document_revisions_letter_id_application_letters"),
        ),
        sa.CheckConstraint(
            "kind IN ('cv', 'letter')", name=op.f("ck_document_revisions_kind")
        ),
        sa.CheckConstraint(
            "language IN ('fr', 'en')", name=op.f("ck_document_revisions_language")
        ),
        sa.CheckConstraint(
            "(kind = 'letter') = (letter_id IS NOT NULL)",
            name=op.f("ck_document_revisions_letter_has_version"),
        ),
    )
    op.create_index(
        "ix_document_revisions_application_id",
        "document_revisions",
        ["application_id", "id"],
    )

    op.create_table(
        "application_sendings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("change_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_on", sa.Date(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("channel_detail", sa.Text(), nullable=True),
        sa.Column("cv_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("letter_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_sendings")),
        *_owner("application_sendings"),
        sa.ForeignKeyConstraint(
            ["change_id"],
            ["application_changes.id"],
            name=op.f("fk_application_sendings_change_id_application_changes"),
        ),
        *_documents("application_sendings"),
        sa.UniqueConstraint(
            "change_id", name=op.f("uq_application_sendings_change_id")
        ),
        sa.CheckConstraint(
            f"channel IN ({CHANNELS})", name=op.f("ck_application_sendings_channel")
        ),
        sa.CheckConstraint(
            "channel <> 'other' OR channel_detail IS NOT NULL",
            name=op.f("ck_application_sendings_other_detailed"),
        ),
    )
    op.create_index(
        "ix_application_sendings_application_id",
        "application_sendings",
        ["application_id", "id"],
    )

    op.create_table(
        "application_prefills",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("cv_revision_id", sa.BigInteger(), nullable=False),
        sa.Column("letter_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("filled", JSONB(), nullable=False),
        sa.Column("missing", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_prefills")),
        *_owner("application_prefills"),
        *_documents("application_prefills"),
    )
    op.create_index(
        "ix_application_prefills_application_id",
        "application_prefills",
        ["application_id", "id"],
    )


def downgrade() -> None:
    for table in ("application_prefills", "application_sendings", "document_revisions"):
        op.drop_index(f"ix_{table}_application_id", table_name=table)
        op.drop_table(table)
