"""The classification of the messages (E2): decisions with their proof, calls to the language model, employer domains.

Decision ``docs/decisions/E2-classification.md``: a decision is appended, the latest in force (Q13), and cannot be
written without a rule, a quotation and a reason (exit criterion); every call to the language model is a row (Q18);
the employer's e-mail domain of an application is appended, the latest in force (Q3).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None

CATEGORIES = (
    "acknowledgement",
    "rejection",
    "interview",
    "assessment",
    "offer",
    "employer_update",
    "recruiter_approach",
    "job_alert",
    "unrelated",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _foreign(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}")
    )


def upgrade() -> None:
    op.create_table(
        "message_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("application_id", sa.BigInteger(), nullable=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("proofs", postgresql.JSONB(), nullable=False),
        sa.Column("classify_version", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_decisions")),
        _foreign("message_decisions", "message_id", "email_messages"),
        _foreign("message_decisions", "account_id", "accounts"),
        _foreign("message_decisions", "application_id", "applications"),
        sa.CheckConstraint(
            f"category IS NULL OR category IN ({_quoted(CATEGORIES)})",
            name=op.f("ck_message_decisions_category"),
        ),
        sa.CheckConstraint(
            "level IN ('high', 'medium', 'low')",
            name=op.f("ck_message_decisions_level"),
        ),
        sa.CheckConstraint(
            "author IN ('user', 'rule', 'ai')",
            name=op.f("ck_message_decisions_author"),
        ),
        sa.CheckConstraint(
            "char_length(rule) > 0", name=op.f("ck_message_decisions_rule_given")
        ),
        sa.CheckConstraint(
            "char_length(excerpt) > 0",
            name=op.f("ck_message_decisions_excerpt_given"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proofs) = 'array' AND jsonb_array_length(proofs) > 0",
            name=op.f("ck_message_decisions_proofs_given"),
        ),
        sa.CheckConstraint(
            "category IS NOT NULL OR level = 'low'",
            name=op.f("ck_message_decisions_undecided_low"),
        ),
    )
    op.create_index(
        "ix_message_decisions_message_id", "message_decisions", ["message_id", "id"]
    )
    op.create_index(
        "ix_message_decisions_account_id", "message_decisions", ["account_id", "id"]
    )

    op.create_table(
        "mail_model_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classify_version", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_model_calls")),
        _foreign("mail_model_calls", "account_id", "accounts"),
        _foreign("mail_model_calls", "message_id", "email_messages"),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'refused', 'failed')",
            name=op.f("ck_mail_model_calls_outcome"),
        ),
    )
    op.create_index(
        "ix_mail_model_calls_account_id_called_at",
        "mail_model_calls",
        ["account_id", "called_at"],
    )

    op.create_table(
        "application_domains",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_domains")),
        _foreign("application_domains", "application_id", "applications"),
        _foreign("application_domains", "account_id", "accounts"),
        sa.CheckConstraint(
            "domain IS NULL OR (domain = lower(domain) AND domain LIKE '%_._%' AND domain NOT LIKE '% %')",
            name=op.f("ck_application_domains_domain_form"),
        ),
    )
    op.create_index(
        "ix_application_domains_application_id",
        "application_domains",
        ["application_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_domains_application_id", table_name="application_domains"
    )
    op.drop_table("application_domains")
    op.drop_index(
        "ix_mail_model_calls_account_id_called_at", table_name="mail_model_calls"
    )
    op.drop_table("mail_model_calls")
    op.drop_index("ix_message_decisions_account_id", table_name="message_decisions")
    op.drop_index("ix_message_decisions_message_id", table_name="message_decisions")
    op.drop_table("message_decisions")
