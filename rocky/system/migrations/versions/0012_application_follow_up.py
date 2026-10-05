"""The follow-up of an application (D6): « Fait », its notes and its language.

Decision ``docs/decisions/D6-ecran-candidatures.md``: « Fait » is a change ``action_done`` that sets the next action
(Q5); the notes are appended, a removal is a row of its own (Q6); the language of the application is appended at
each choice, the latest in force (Q4).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None

KINDS_BEFORE = "'created', 'stage', 'next_action', 'cancellation'"
KINDS = KINDS_BEFORE + ", 'action_done'"
NOTE_MAX_LENGTH = 4000


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


def _kinds(kinds: str) -> None:
    op.drop_constraint(
        op.f("ck_application_changes_kind"), "application_changes", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_application_changes_kind"), "application_changes", f"kind IN ({kinds})"
    )


def upgrade() -> None:
    _kinds(KINDS)

    op.create_table(
        "application_notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("removes_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_notes")),
        *_owner("application_notes"),
        sa.ForeignKeyConstraint(
            ["removes_id"],
            ["application_notes.id"],
            name=op.f("fk_application_notes_removes_id_application_notes"),
        ),
        sa.UniqueConstraint("removes_id", name=op.f("uq_application_notes_removes_id")),
        sa.CheckConstraint(
            "(text IS NULL) = (removes_id IS NOT NULL)",
            name=op.f("ck_application_notes_note_or_removal"),
        ),
        sa.CheckConstraint(
            f"text IS NULL OR char_length(text) BETWEEN 1 AND {NOTE_MAX_LENGTH}",
            name=op.f("ck_application_notes_text_length"),
        ),
    )
    op.create_index(
        "ix_application_notes_application_id",
        "application_notes",
        ["application_id", "id"],
    )

    op.create_table(
        "application_languages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_languages")),
        *_owner("application_languages"),
        sa.CheckConstraint(
            "language IN ('fr', 'en')", name=op.f("ck_application_languages_language")
        ),
    )
    op.create_index(
        "ix_application_languages_application_id",
        "application_languages",
        ["application_id", "id"],
    )


def downgrade() -> None:
    for table in ("application_languages", "application_notes"):
        op.drop_index(f"ix_{table}_application_id", table_name=table)
        op.drop_table(table)
    # The « Fait » have no place before 0012: they go, with the cancellations that target them (their events stay).
    op.execute(
        "DELETE FROM application_changes WHERE cancels_id IN "
        "(SELECT id FROM application_changes WHERE kind = 'action_done')"
    )
    op.execute("DELETE FROM application_changes WHERE kind = 'action_done'")
    _kinds(KINDS_BEFORE)
