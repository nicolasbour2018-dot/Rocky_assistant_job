"""The platform's notices on an application (E2, acceptance): a tenth category of the messages.

Decision ``docs/decisions/E2-classification.md`` (Q20): « Avis de plateforme » (finalise your application, offer
withdrawn, application seen) is no longer an employer's message.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05
"""

from __future__ import annotations

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None

BEFORE = (
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
AFTER = (*BEFORE[:6], "platform_notice", *BEFORE[6:])
NAME = "ck_message_decisions_category"


def _check(categories: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{category}'" for category in categories)
    return f"category IS NULL OR category IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "message_decisions", type_="check")
    op.create_check_constraint(op.f(NAME), "message_decisions", _check(AFTER))


def downgrade() -> None:
    # The decisions are kept: a platform's notice goes back to the category it had before (an employer's message).
    op.execute(
        "UPDATE message_decisions SET category = 'employer_update' WHERE category = 'platform_notice'"
    )
    op.drop_constraint(op.f(NAME), "message_decisions", type_="check")
    op.create_check_constraint(op.f(NAME), "message_decisions", _check(BEFORE))
