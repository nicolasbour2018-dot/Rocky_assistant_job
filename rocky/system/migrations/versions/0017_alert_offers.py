"""The job alerts as a source of offers (E3): the reading of each alert and the offers it gave, with what became of the
link of each card.

Decision ``docs/decisions/E3-alertes.md``: an alert is read once (Q4), every card gives an offer (Q3), an unread
posting keeps its reason (Q5); an offer may come from an alert. Everything is appended.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None

PLATFORMS = ("hellowork", "cadremploi", "efinancialcareers", "linkedin")
STATUSES = ("read", "unknown_format", "no_card", "failed")
OUTCOMES = ("read", "refused", "failed", "invalid", "not_tried")
NOT_TRIED = ("known_complete", "too_old", "host_stopped", "no_link", "without_links")
ORIGINS_BEFORE = ("watch", "import", "message")
ORIGINS = (*ORIGINS_BEFORE, "alert")


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

    op.create_table(
        "alert_readings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("cards", sa.Integer(), nullable=False),
        sa.Column("alerts_version", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_readings")),
        _foreign("alert_readings", "account_id", "accounts"),
        _foreign("alert_readings", "message_id", "email_messages"),
        sa.UniqueConstraint("message_id", name=op.f("uq_alert_readings_message_id")),
        sa.CheckConstraint(
            f"platform IS NULL OR platform IN ({_quoted(PLATFORMS)})",
            name=op.f("ck_alert_readings_platform"),
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(STATUSES)})", name=op.f("ck_alert_readings_status")
        ),
        sa.CheckConstraint(
            "status <> 'unknown_format' OR platform IS NULL",
            name=op.f("ck_alert_readings_no_reader"),
        ),
        sa.CheckConstraint(
            "platform IS NOT NULL OR status IN ('unknown_format', 'failed')",
            name=op.f("ck_alert_readings_reader_known"),
        ),
        sa.CheckConstraint(
            "(status = 'read') = (cards > 0)", name=op.f("ck_alert_readings_cards_read")
        ),
        sa.CheckConstraint(
            "(status = 'read') = (reason IS NULL)",
            name=op.f("ck_alert_readings_reason_unless_read"),
        ),
    )
    op.create_index(
        "ix_alert_readings_account_id", "alert_readings", ["account_id", "id"]
    )

    op.create_table(
        "alert_offers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("reading_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("created", sa.Boolean(), nullable=False),
        sa.Column("link_outcome", sa.Text(), nullable=False),
        sa.Column("not_tried", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_offers")),
        _foreign("alert_offers", "reading_id", "alert_readings"),
        _foreign("alert_offers", "account_id", "accounts"),
        _foreign("alert_offers", "offer_id", "job_offers"),
        sa.UniqueConstraint(
            "reading_id", "position", name=op.f("uq_alert_offers_reading_id")
        ),
        sa.CheckConstraint(
            f"link_outcome IN ({_quoted(OUTCOMES)})",
            name=op.f("ck_alert_offers_link_outcome"),
        ),
        sa.CheckConstraint(
            f"not_tried IS NULL OR not_tried IN ({_quoted(NOT_TRIED)})",
            name=op.f("ck_alert_offers_not_tried"),
        ),
        sa.CheckConstraint(
            "(link_outcome = 'not_tried') = (not_tried IS NOT NULL)",
            name=op.f("ck_alert_offers_why_not_tried"),
        ),
        sa.CheckConstraint(
            "(link_outcome = 'read') = (reason IS NULL)",
            name=op.f("ck_alert_offers_reason_unless_read"),
        ),
        sa.CheckConstraint("position > 0", name=op.f("ck_alert_offers_position")),
    )
    op.create_index("ix_alert_offers_offer_id", "alert_offers", ["offer_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_offers_offer_id", table_name="alert_offers")
    op.drop_table("alert_offers")
    op.drop_index("ix_alert_readings_account_id", table_name="alert_readings")
    op.drop_table("alert_readings")
    # The offers are kept: one taken from an alert goes back to the origin closest to it (an import).
    op.execute("UPDATE job_offers SET origin = 'import' WHERE origin = 'alert'")
    op.execute("UPDATE offer_tracks SET found_by = 'import' WHERE found_by = 'alert'")
    _origins(ORIGINS_BEFORE)
