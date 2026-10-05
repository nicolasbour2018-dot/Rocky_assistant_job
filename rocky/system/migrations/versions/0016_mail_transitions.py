"""The decisions on the messages (E4): the transitions they give, how the user settled them, the account's rules per
sender, the decision a user's decision reviews, and the offers created from a message.

Decision ``docs/decisions/E4-decisions-ecran.md``: a transition is recorded with the decision that gave it, applied
(with the change of the application) or proposed (Q1); « Ce qui a bougé » is the transitions without a settlement
(Q5); a rule per sender is appended, a removal is a row of its own (Q7); a user's decision keeps the decision it
reviews, the labels of D14 (Q6); an offer may come from a message (Q4, Q12).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None

STAGES = (
    "preparing",
    "ready",
    "prefilled",
    "sent",
    "in_discussion",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "no_response",
)
OUTCOMES = ("applied", "proposed")
GESTURES = ("seen", "applied", "dismissed", "cancelled", "corrected", "replaced")
RULE_CATEGORIES = ("recruiter_approach", "job_alert", "unrelated")
ORIGINS_BEFORE = ("watch", "import")
ORIGINS = (*ORIGINS_BEFORE, "message")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _foreign(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}")
    )


def _origins(origins: tuple[str, ...]) -> None:
    for table, column in (("job_offers", "origin"), ("offer_tracks", "found_by")):
        name = op.f(f"ck_{table}_{column}")
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"{column} IN ({_quoted(origins)})")


def upgrade() -> None:
    _origins(ORIGINS)

    op.add_column(
        "message_decisions", sa.Column("reviews_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_message_decisions_reviews_id_message_decisions"),
        "message_decisions",
        "message_decisions",
        ["reviews_id"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_message_decisions_reviews_by_user"),
        "message_decisions",
        "reviews_id IS NULL OR author = 'user'",
    )

    op.create_table(
        "mail_transitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("decision_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("from_stage", sa.Text(), nullable=False),
        sa.Column("to_stage", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("change_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_transitions")),
        _foreign("mail_transitions", "account_id", "accounts"),
        _foreign("mail_transitions", "decision_id", "message_decisions"),
        _foreign("mail_transitions", "message_id", "email_messages"),
        _foreign("mail_transitions", "application_id", "applications"),
        _foreign("mail_transitions", "change_id", "application_changes"),
        sa.UniqueConstraint(
            "decision_id", name=op.f("uq_mail_transitions_decision_id")
        ),
        sa.UniqueConstraint("change_id", name=op.f("uq_mail_transitions_change_id")),
        sa.CheckConstraint(
            f"from_stage IN ({_quoted(STAGES)})",
            name=op.f("ck_mail_transitions_from_stage"),
        ),
        sa.CheckConstraint(
            f"to_stage IN ({_quoted(STAGES)})",
            name=op.f("ck_mail_transitions_to_stage"),
        ),
        sa.CheckConstraint(
            f"outcome IN ({_quoted(OUTCOMES)})",
            name=op.f("ck_mail_transitions_outcome"),
        ),
        sa.CheckConstraint(
            "from_stage <> to_stage", name=op.f("ck_mail_transitions_moves")
        ),
        # An applied transition is a change of the application; a proposed one is not, until the user applies it.
        sa.CheckConstraint(
            "(outcome = 'applied') = (change_id IS NOT NULL)",
            name=op.f("ck_mail_transitions_change_when_applied"),
        ),
    )
    op.create_index(
        "ix_mail_transitions_account_id", "mail_transitions", ["account_id", "id"]
    )
    op.create_index(
        "ix_mail_transitions_message_id", "mail_transitions", ["message_id", "id"]
    )

    op.create_table(
        "mail_transition_settlements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("transition_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("gesture", sa.Text(), nullable=False),
        sa.Column("change_id", sa.BigInteger(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_transition_settlements")),
        _foreign("mail_transition_settlements", "transition_id", "mail_transitions"),
        _foreign("mail_transition_settlements", "account_id", "accounts"),
        _foreign("mail_transition_settlements", "change_id", "application_changes"),
        sa.UniqueConstraint(
            "transition_id",
            "gesture",
            name=op.f("uq_mail_transition_settlements_transition_id"),
        ),
        sa.CheckConstraint(
            f"gesture IN ({_quoted(GESTURES)})",
            name=op.f("ck_mail_transition_settlements_gesture"),
        ),
        # Applying a proposal is a change of the application.
        sa.CheckConstraint(
            "gesture <> 'applied' OR change_id IS NOT NULL",
            name=op.f("ck_mail_transition_settlements_change_when_applied"),
        ),
    )

    op.create_table(
        "mail_sender_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_address", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("decision_id", sa.BigInteger(), nullable=True),
        sa.Column("removes_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_sender_rules")),
        _foreign("mail_sender_rules", "account_id", "accounts"),
        _foreign("mail_sender_rules", "decision_id", "message_decisions"),
        _foreign("mail_sender_rules", "removes_id", "mail_sender_rules"),
        sa.UniqueConstraint("removes_id", name=op.f("uq_mail_sender_rules_removes_id")),
        sa.CheckConstraint(
            "(category IS NULL) = (removes_id IS NOT NULL)",
            name=op.f("ck_mail_sender_rules_rule_or_removal"),
        ),
        sa.CheckConstraint(
            f"category IS NULL OR category IN ({_quoted(RULE_CATEGORIES)})",
            name=op.f("ck_mail_sender_rules_category"),
        ),
        sa.CheckConstraint(
            "char_length(sender_address) > 0 AND sender_address = lower(sender_address)",
            name=op.f("ck_mail_sender_rules_sender_address"),
        ),
    )
    op.create_index(
        "ix_mail_sender_rules_account_id", "mail_sender_rules", ["account_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mail_sender_rules_account_id", table_name="mail_sender_rules")
    op.drop_table("mail_sender_rules")
    op.drop_table("mail_transition_settlements")
    op.drop_index("ix_mail_transitions_message_id", table_name="mail_transitions")
    op.drop_index("ix_mail_transitions_account_id", table_name="mail_transitions")
    op.drop_table("mail_transitions")
    op.drop_constraint(
        op.f("ck_message_decisions_reviews_by_user"), "message_decisions", type_="check"
    )
    op.drop_constraint(
        op.f("fk_message_decisions_reviews_id_message_decisions"),
        "message_decisions",
        type_="foreignkey",
    )
    op.drop_column("message_decisions", "reviews_id")
    # The offers are kept: one created from a message goes back to the origin closest to it (an import).
    op.execute("UPDATE job_offers SET origin = 'import' WHERE origin = 'message'")
    op.execute("UPDATE offer_tracks SET found_by = 'import' WHERE found_by = 'message'")
    _origins(ORIGINS_BEFORE)
