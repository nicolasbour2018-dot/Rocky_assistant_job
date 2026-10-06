"""Every call to a language model (step G4): its account, its type, its model, its tokens and its outcome.

Decision ``docs/decisions/G4-assistant.md``: every call is recorded, to measure its cost (Q9, Q16, Q17); the
assistant is limited on it (Q8).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None

CALL_TYPES = (
    "assistant",
    "summary",
    "cv",
    "translation",
    "letter",
    "recruiter_message",
    "mail_classification",
)
PROVIDERS = ("gemini", "anthropic", "openai", "mistral")
OUTCOMES = ("ok", "failed", "rejected")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("call_type", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calls")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_model_calls_account_id_accounts"),
        ),
        sa.CheckConstraint(
            f"call_type IN ({_quoted(CALL_TYPES)})",
            name=op.f("ck_model_calls_call_type"),
        ),
        sa.CheckConstraint(
            f"provider IN ({_quoted(PROVIDERS)})", name=op.f("ck_model_calls_provider")
        ),
        sa.CheckConstraint(
            f"outcome IN ({_quoted(OUTCOMES)})", name=op.f("ck_model_calls_outcome")
        ),
        sa.CheckConstraint(
            "outcome <> 'failed' OR reason IS NOT NULL",
            name=op.f("ck_model_calls_failure_reason"),
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("ck_model_calls_input_tokens_positive"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_model_calls_output_tokens_positive"),
        ),
        sa.CheckConstraint(
            "duration_ms >= 0", name=op.f("ck_model_calls_duration_positive")
        ),
    )
    op.create_index(
        "ix_model_calls_account_id_call_type_called_at",
        "model_calls",
        ["account_id", "call_type", "called_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_calls_account_id_call_type_called_at", table_name="model_calls"
    )
    op.drop_table("model_calls")
