"""The mail collection (E1): mailboxes, their collections and the messages collected.

Decision ``docs/decisions/E1-collecte.md``: a refresh token is stored sealed (Q3); a message is stored once per mailbox
(the idempotence of the collection) and never changed; a collection is always closed with a final status (Q7).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def _account(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["account_id"], ["accounts.id"], name=op.f(f"fk_{table}_account_id_accounts")
    )


def _mailbox(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["mailbox_id"], ["mailboxes.id"], name=op.f(f"fk_{table}_mailbox_id_mailboxes")
    )


def upgrade() -> None:
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sealed_token", sa.LargeBinary(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mailboxes")),
        _account("mailboxes"),
        sa.UniqueConstraint(
            "account_id", "address", name=op.f("uq_mailboxes_account_id_address")
        ),
        sa.CheckConstraint(
            "status IN ('connected', 'access_lost', 'disconnected')",
            name=op.f("ck_mailboxes_status"),
        ),
        sa.CheckConstraint(
            "(status = 'connected') = (sealed_token IS NOT NULL)",
            name=op.f("ck_mailboxes_token_when_connected"),
        ),
    )

    op.create_table(
        "mail_syncs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("mailbox_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queries_version", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("listed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("known", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new", sa.Integer(), server_default="0", nullable=False),
        sa.Column("not_written", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_syncs")),
        _mailbox("mail_syncs"),
        _account("mail_syncs"),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'manual')", name=op.f("ck_mail_syncs_trigger")
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed', 'interrupted')",
            name=op.f("ck_mail_syncs_status"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_mail_syncs_closed_when_final"),
        ),
    )
    op.create_index(
        "ix_mail_syncs_mailbox_id_started_at",
        "mail_syncs",
        ["mailbox_id", "started_at"],
    )

    op.create_table(
        "email_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("mailbox_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("sync_id", sa.BigInteger(), nullable=False),
        sa.Column("gmail_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("sender_address", sa.Text(), nullable=True),
        sa.Column("recipients", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=False),
        sa.Column("attachments", postgresql.JSONB(), nullable=False),
        sa.Column("rfc822_id", sa.Text(), nullable=True),
        sa.Column("found_by", postgresql.JSONB(), nullable=False),
        sa.Column("queries_version", sa.Text(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_messages")),
        _mailbox("email_messages"),
        _account("email_messages"),
        sa.ForeignKeyConstraint(
            ["sync_id"],
            ["mail_syncs.id"],
            name=op.f("fk_email_messages_sync_id_mail_syncs"),
        ),
        sa.UniqueConstraint(
            "mailbox_id", "gmail_id", name=op.f("uq_email_messages_mailbox_id_gmail_id")
        ),
    )
    op.create_index(
        "ix_email_messages_account_id_received_at",
        "email_messages",
        ["account_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_messages_account_id_received_at", table_name="email_messages"
    )
    op.drop_table("email_messages")
    op.drop_index("ix_mail_syncs_mailbox_id_started_at", table_name="mail_syncs")
    op.drop_table("mail_syncs")
    op.drop_table("mailboxes")
