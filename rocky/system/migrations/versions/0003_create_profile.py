"""Create the profile: identity and preferences, search tracks, skills and their terms, languages,
experiences, projects and the skills they prove.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None

CONTRACTS = (
    "'permanent', 'fixed_term', 'freelance', 'international_volunteer', "
    "'internship', 'apprenticeship', 'temporary'"
)
REMOTE_MODES = "'on_site', 'hybrid', 'full_remote'"


def _list(name: str) -> sa.Column[list[str]]:
    return sa.Column(
        name,
        postgresql.ARRAY(sa.Text()),
        server_default=sa.text("'{}'::text[]"),
        nullable=False,
    )


def _timestamp(name: str) -> sa.Column[datetime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _owned_by_profile(table: str) -> list[sa.Constraint]:
    """Identity key and owning profile."""
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f(f"fk_{table}_profile_id_profiles"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("github_url", sa.Text(), nullable=True),
        sa.Column("portfolio_url", sa.Text(), nullable=True),
        sa.Column("headline_fr", sa.Text(), nullable=True),
        sa.Column("headline_en", sa.Text(), nullable=True),
        _list("contracts"),
        _list("remote_modes"),
        sa.Column("min_salary_eur", sa.Integer(), nullable=True),
        sa.Column("min_daily_rate_eur", sa.Integer(), nullable=True),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarding_deferred_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_profiles_account_id_accounts"),
        ),
        sa.UniqueConstraint("account_id", name=op.f("uq_profiles_account_id")),
        sa.CheckConstraint(
            f"contracts <@ ARRAY[{CONTRACTS}]::text[]",
            name=op.f("ck_profiles_contracts"),
        ),
        sa.CheckConstraint(
            f"remote_modes <@ ARRAY[{REMOTE_MODES}]::text[]",
            name=op.f("ck_profiles_remote_modes"),
        ),
        sa.CheckConstraint(
            "min_salary_eur > 0", name=op.f("ck_profiles_min_salary_positive")
        ),
        sa.CheckConstraint(
            "min_daily_rate_eur > 0",
            name=op.f("ck_profiles_min_daily_rate_positive"),
        ),
    )
    op.create_table(
        "search_tracks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _list("titles"),
        _list("keywords"),
        _list("excluded_keywords"),
        _list("locations"),
        sa.Column("status", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        *_owned_by_profile("search_tracks"),
        sa.UniqueConstraint(
            "profile_id", "name", name=op.f("uq_search_tracks_profile_id_name")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived')",
            name=op.f("ck_search_tracks_status"),
        ),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("label_fr", sa.Text(), nullable=False),
        sa.Column("label_en", sa.Text(), nullable=True),
        _list("aliases"),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column(
            "is_key", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        _timestamp("created_at"),
        *_owned_by_profile("skills"),
        sa.UniqueConstraint("profile_id", "id", name=op.f("uq_skills_profile_id_id")),
        sa.CheckConstraint(
            "category IN ('technical', 'business', 'soft')",
            name=op.f("ck_skills_category"),
        ),
        sa.CheckConstraint(
            "level IN ('beginner', 'intermediate', 'advanced', 'expert')",
            name=op.f("ck_skills_level"),
        ),
    )
    op.create_index("ix_skills_profile_id", "skills", ["profile_id"])
    op.create_table(
        "skill_terms",
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("profile_id", "term", name=op.f("pk_skill_terms")),
        sa.ForeignKeyConstraint(
            ["profile_id", "skill_id"],
            ["skills.profile_id", "skills.id"],
            name=op.f("fk_skill_terms_profile_id_skills"),
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_skill_terms_skill_id", "skill_terms", ["skill_id"])
    op.create_table(
        "languages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        _timestamp("created_at"),
        *_owned_by_profile("languages"),
        sa.UniqueConstraint(
            "profile_id", "code", name=op.f("uq_languages_profile_id_code")
        ),
        sa.CheckConstraint(
            "level IN ('a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'native')",
            name=op.f("ck_languages_level"),
        ),
    )
    op.create_table(
        "experiences",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("organisation", sa.Text(), nullable=False),
        sa.Column("place", sa.Text(), nullable=True),
        sa.Column("start_month", sa.Date(), nullable=False),
        sa.Column("end_month", sa.Date(), nullable=True),
        _list("bullets_fr"),
        _list("bullets_en"),
        _timestamp("created_at"),
        *_owned_by_profile("experiences"),
        sa.UniqueConstraint(
            "profile_id", "id", name=op.f("uq_experiences_profile_id_id")
        ),
        sa.CheckConstraint(
            "kind IN ('job', 'education')", name=op.f("ck_experiences_kind")
        ),
        sa.CheckConstraint(
            "end_month IS NULL OR end_month >= start_month",
            name=op.f("ck_experiences_dates"),
        ),
    )
    op.create_index("ix_experiences_profile_id", "experiences", ["profile_id"])
    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("name_fr", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("problem_fr", sa.Text(), nullable=True),
        sa.Column("problem_en", sa.Text(), nullable=True),
        sa.Column("work_fr", sa.Text(), nullable=True),
        sa.Column("work_en", sa.Text(), nullable=True),
        sa.Column("results_fr", sa.Text(), nullable=True),
        sa.Column("results_en", sa.Text(), nullable=True),
        _list("stack"),
        sa.Column("url", sa.Text(), nullable=True),
        _timestamp("created_at"),
        *_owned_by_profile("projects"),
        sa.UniqueConstraint("profile_id", "id", name=op.f("uq_projects_profile_id_id")),
    )
    op.create_index("ix_projects_profile_id", "projects", ["profile_id"])
    for table, owner in (
        ("experience_skills", "experience"),
        ("project_skills", "project"),
    ):
        op.create_table(
            table,
            sa.Column("profile_id", sa.BigInteger(), nullable=False),
            sa.Column(f"{owner}_id", sa.BigInteger(), nullable=False),
            sa.Column("skill_id", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint(
                f"{owner}_id", "skill_id", name=op.f(f"pk_{table}")
            ),
            sa.ForeignKeyConstraint(
                ["profile_id", f"{owner}_id"],
                [f"{owner}s.profile_id", f"{owner}s.id"],
                name=op.f(f"fk_{table}_profile_id_{owner}s"),
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["profile_id", "skill_id"],
                ["skills.profile_id", "skills.id"],
                name=op.f(f"fk_{table}_profile_id_skills"),
                ondelete="CASCADE",
            ),
        )
        op.create_index(f"ix_{table}_skill_id", table, ["skill_id"])


def downgrade() -> None:
    for table in ("project_skills", "experience_skills"):
        op.drop_index(f"ix_{table}_skill_id", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_projects_profile_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_experiences_profile_id", table_name="experiences")
    op.drop_table("experiences")
    op.drop_table("languages")
    op.drop_index("ix_skill_terms_skill_id", table_name="skill_terms")
    op.drop_table("skill_terms")
    op.drop_index("ix_skills_profile_id", table_name="skills")
    op.drop_table("skills")
    op.drop_table("search_tracks")
    op.drop_table("profiles")
