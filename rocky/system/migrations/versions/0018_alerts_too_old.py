"""An alert older than 3 days gives nothing and says so (E3, Q8): the reading status ``too_old``.

Decision ``docs/decisions/E3-alertes.md`` (Q8, Nicolas 05/10): at most 10 alerts give their offers per day, and an alert
older than 3 days is marked « trop ancienne », without reader nor offer.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-05
"""

from __future__ import annotations

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None

STATUSES_BEFORE = ("read", "unknown_format", "no_card", "failed")
STATUSES = (*STATUSES_BEFORE, "too_old")
WITHOUT_READER_BEFORE = ("unknown_format", "failed")
WITHOUT_READER = (*WITHOUT_READER_BEFORE, "too_old")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _checks(statuses: tuple[str, ...], without_reader: tuple[str, ...]) -> None:
    for name, condition in (
        ("ck_alert_readings_status", f"status IN ({_quoted(statuses)})"),
        (
            "ck_alert_readings_reader_known",
            f"platform IS NOT NULL OR status IN ({_quoted(without_reader)})",
        ),
    ):
        op.drop_constraint(op.f(name), "alert_readings", type_="check")
        op.create_check_constraint(op.f(name), "alert_readings", condition)


def upgrade() -> None:
    _checks(STATUSES, WITHOUT_READER)


def downgrade() -> None:
    # An alert marked too old is unread again: the next pass of the previous version reads it.
    op.execute("DELETE FROM alert_readings WHERE status = 'too_old'")
    _checks(STATUSES_BEFORE, WITHOUT_READER_BEFORE)
