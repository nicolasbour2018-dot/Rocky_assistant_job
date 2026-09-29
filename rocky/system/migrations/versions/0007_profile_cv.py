"""Profile data of the master CV: short title, age, photo, links, hobbies, skill groups, CV order, CV templates.

Decision ``docs/decisions/D2-cv-rendu.md`` (Q7–Q10, Q24, Q26). The LinkedIn, GitHub and portfolio columns move to
``profile_links`` (Q8: one list of links); the downgrade puts them back. ``headline`` keeps the profile
paragraph written by the B5 import; ``title`` is the new short title (« Data Scientist »).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None

OLD_LINKS = ("linkedin_url", "github_url", "portfolio_url")
COPY_LINKS = (
    (
        "INSERT INTO profile_links (profile_id, position, label, url) "
        "SELECT id, 0, 'LinkedIn', linkedin_url FROM profiles WHERE linkedin_url <> ''"
    ),
    (
        "INSERT INTO profile_links (profile_id, position, label, url) "
        "SELECT id, 1, 'GitHub', github_url FROM profiles WHERE github_url <> ''"
    ),
    (
        "INSERT INTO profile_links (profile_id, position, label, url) "
        "SELECT id, 2, 'Portfolio', portfolio_url FROM profiles WHERE portfolio_url <> ''"
    ),
)
RESTORE_LINKS = (
    (
        "UPDATE profiles SET linkedin_url = link.url FROM profile_links AS link "
        "WHERE link.profile_id = profiles.id AND link.label = 'LinkedIn'"
    ),
    (
        "UPDATE profiles SET github_url = link.url FROM profile_links AS link "
        "WHERE link.profile_id = profiles.id AND link.label = 'GitHub'"
    ),
    (
        "UPDATE profiles SET portfolio_url = link.url FROM profile_links AS link "
        "WHERE link.profile_id = profiles.id AND link.label = 'Portfolio'"
    ),
)


def upgrade() -> None:
    op.add_column("profiles", sa.Column("title_fr", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("title_en", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column(
        "profiles",
        sa.Column(
            "show_age", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("profiles", sa.Column("photo_path", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("photo_sha256", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_profiles_photo_complete"),
        "profiles",
        "(photo_path IS NULL) = (photo_sha256 IS NULL)",
    )

    op.create_table(
        "profile_links",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_links")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_profile_links_profile_id_profiles"),
        ),
        sa.UniqueConstraint(
            "profile_id", "position", name=op.f("uq_profile_links_profile_id_position")
        ),
    )
    for statement in COPY_LINKS:
        op.execute(statement)
    for column in OLD_LINKS:
        op.drop_column("profiles", column)

    op.create_table(
        "hobbies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label_fr", sa.Text(), nullable=False),
        sa.Column("label_en", sa.Text(), nullable=True),
        sa.Column(
            "in_cv", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hobbies")),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["profiles.id"], name=op.f("fk_hobbies_profile_id_profiles")
        ),
        sa.UniqueConstraint(
            "profile_id", "position", name=op.f("uq_hobbies_profile_id_position")
        ),
    )

    op.create_table(
        "skill_groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name_fr", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_groups")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_skill_groups_profile_id_profiles"),
        ),
        sa.UniqueConstraint(
            "profile_id", "id", name=op.f("uq_skill_groups_profile_id_id")
        ),
        sa.UniqueConstraint(
            "profile_id", "position", name=op.f("uq_skill_groups_profile_id_position")
        ),
    )
    op.add_column("skills", sa.Column("group_id", sa.BigInteger(), nullable=True))
    op.add_column("skills", sa.Column("cv_position", sa.Integer(), nullable=True))
    # The composite key refuses a group of another profile; a group still holding skills cannot be deleted.
    op.create_foreign_key(
        op.f("fk_skills_profile_id_skill_groups"),
        "skills",
        "skill_groups",
        ["profile_id", "group_id"],
        ["profile_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_skills_cv_placement"),
        "skills",
        # A technical skill is in the CV through its group; the others by their position alone.
        "(category = 'technical' AND (group_id IS NULL) = (cv_position IS NULL)) "
        "OR (category <> 'technical' AND group_id IS NULL)",
    )
    op.add_column("projects", sa.Column("cv_position", sa.Integer(), nullable=True))

    op.create_table(
        "cv_templates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_templates")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_cv_templates_profile_id_profiles"),
        ),
        sa.UniqueConstraint(
            "profile_id", "sha256", name=op.f("uq_cv_templates_profile_id_sha256")
        ),
    )
    op.create_index(
        "uq_cv_templates_one_active",
        "cv_templates",
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("uq_cv_templates_one_active", table_name="cv_templates")
    op.drop_table("cv_templates")
    op.drop_column("projects", "cv_position")
    op.drop_constraint(op.f("ck_skills_cv_placement"), "skills", type_="check")
    op.drop_constraint(
        op.f("fk_skills_profile_id_skill_groups"), "skills", type_="foreignkey"
    )
    op.drop_column("skills", "cv_position")
    op.drop_column("skills", "group_id")
    op.drop_table("skill_groups")
    op.drop_table("hobbies")
    for column in OLD_LINKS:
        op.add_column("profiles", sa.Column(column, sa.Text(), nullable=True))
    for statement in RESTORE_LINKS:
        op.execute(statement)
    op.drop_table("profile_links")
    op.drop_constraint(op.f("ck_profiles_photo_complete"), "profiles", type_="check")
    for column in (
        "photo_sha256",
        "photo_path",
        "show_age",
        "birth_date",
        "title_en",
        "title_fr",
    ):
        op.drop_column("profiles", column)
