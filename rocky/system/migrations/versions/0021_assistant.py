"""The conversations with the assistant 🐾 (step G4): one general per account and one per object, and their turns.

Decision ``docs/decisions/G4-assistant.md``: kept whole (Q3), resumed from one day to the next (Q10), a new one when
asked (Q20); each turn keeps the facts it cited and the call that answered it.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | None = None
depends_on: str | None = None


def _foreign(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}")
    )


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_kind", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_conversations")),
        _foreign("assistant_conversations", "account_id", "accounts"),
        sa.CheckConstraint(
            "subject_kind IS NULL OR subject_kind IN ('offre', 'candidature', 'message')",
            name=op.f("ck_assistant_conversations_subject_kind"),
        ),
        sa.CheckConstraint(
            "(subject_kind IS NULL) = (subject_id IS NULL)",
            name=op.f("ck_assistant_conversations_subject_complete"),
        ),
    )
    op.create_index(
        "ix_assistant_conversations_account_id_subject_kind",
        "assistant_conversations",
        ["account_id", "subject_kind", "subject_id", "id"],
    )
    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("cited", postgresql.JSONB(), nullable=False),
        sa.Column("raw_answer", postgresql.JSONB(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("model_call_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_turns")),
        _foreign("assistant_turns", "conversation_id", "assistant_conversations"),
        _foreign("assistant_turns", "account_id", "accounts"),
        _foreign("assistant_turns", "model_call_id", "model_calls"),
        sa.CheckConstraint(
            "outcome IN ('answered', 'no_answer', 'rejected')",
            name=op.f("ck_assistant_turns_outcome"),
        ),
        sa.CheckConstraint(
            "length(question) > 0", name=op.f("ck_assistant_turns_question_given")
        ),
    )
    op.create_index(
        "ix_assistant_turns_conversation_id",
        "assistant_turns",
        ["conversation_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_turns_conversation_id", table_name="assistant_turns")
    op.drop_table("assistant_turns")
    op.drop_index(
        "ix_assistant_conversations_account_id_subject_kind",
        table_name="assistant_conversations",
    )
    op.drop_table("assistant_conversations")
