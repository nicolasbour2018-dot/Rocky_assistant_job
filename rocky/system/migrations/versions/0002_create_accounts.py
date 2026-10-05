"""Create accounts, account tokens and sessions; link events to accounts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failed_login_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("email", name=op.f("uq_accounts_email")),
        sa.CheckConstraint(
            "status IN ('pending', 'active')", name=op.f("ck_accounts_status")
        ),
        sa.CheckConstraint(
            "status <> 'active' OR password_hash IS NOT NULL",
            name=op.f("ck_accounts_active_has_password"),
        ),
    )
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_tokens")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_account_tokens_account_id_accounts"),
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_account_tokens_token_hash")),
        sa.CheckConstraint(
            "purpose IN ('activation', 'password_reset')",
            name=op.f("ck_account_tokens_purpose"),
        ),
    )
    op.create_index(
        "ix_account_tokens_account_purpose",
        "account_tokens",
        ["account_id", "purpose"],
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_sessions_account_id_accounts"),
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"])
    # Adding a column is DDL: the append-only triggers of events (0001) do not apply.
    op.add_column("events", sa.Column("account_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_events_account_id_accounts"),
        "events",
        "accounts",
        ["account_id"],
        ["id"],
    )
    op.create_index("ix_events_account_id", "events", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_events_account_id", table_name="events")
    op.drop_constraint(
        op.f("fk_events_account_id_accounts"), "events", type_="foreignkey"
    )
    op.drop_column("events", "account_id")
    op.drop_index("ix_sessions_account_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_account_tokens_account_purpose", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_table("accounts")
