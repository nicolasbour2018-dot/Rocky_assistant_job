"""SQL access of the profile: the only place where profile tables are queried."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Connection,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Row,
    Table,
    Text,
    UniqueConstraint,
    delete,
    func,
    insert,
    select,
    text,
    update,
)

from rocky.profil import model
from rocky.profil.model import (
    Contract,
    Experience,
    ExperienceDraft,
    ExperienceKind,
    Language,
    LanguageDraft,
    LanguageLevel,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    RemoteMode,
    Skill,
    SkillCategory,
    SkillDraft,
    SkillLevel,
    Track,
    TrackDraft,
    TrackStatus,
)
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event


def _in(column: str, values: type[StrEnum]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def _all_in(column: str, values: type[StrEnum]) -> str:
    """Every element of the array column is one of ``values``."""
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} <@ ARRAY[{listed}]::text[]"


def _list() -> Any:
    return ARRAY(Text)


def _empty_list() -> Any:
    return text("'{}'::text[]")


def _created() -> Column[Any]:
    return Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


profiles = Table(
    "profiles",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("full_name", Text),
    Column("contact_email", Text),
    Column("phone", Text),
    Column("city", Text),
    Column("postal_code", Text),
    Column("linkedin_url", Text),
    Column("github_url", Text),
    Column("portfolio_url", Text),
    Column("headline_fr", Text),
    Column("headline_en", Text),
    Column("contracts", _list(), nullable=False, server_default=_empty_list()),
    Column("remote_modes", _list(), nullable=False, server_default=_empty_list()),
    Column("min_salary_eur", Integer),
    Column("min_daily_rate_eur", Integer),
    Column("onboarding_completed_at", DateTime(timezone=True)),
    Column("onboarding_deferred_at", DateTime(timezone=True)),
    _created(),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    UniqueConstraint("account_id"),
    CheckConstraint(_all_in("contracts", Contract), name="contracts"),
    CheckConstraint(_all_in("remote_modes", RemoteMode), name="remote_modes"),
    CheckConstraint("min_salary_eur > 0", name="min_salary_positive"),
    CheckConstraint("min_daily_rate_eur > 0", name="min_daily_rate_positive"),
)

search_tracks = Table(
    "search_tracks",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("profile_id", BigInteger, ForeignKey("profiles.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("titles", _list(), nullable=False, server_default=_empty_list()),
    Column("keywords", _list(), nullable=False, server_default=_empty_list()),
    Column("excluded_keywords", _list(), nullable=False, server_default=_empty_list()),
    Column("locations", _list(), nullable=False, server_default=_empty_list()),
    Column("status", Text, nullable=False),
    _created(),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    UniqueConstraint("profile_id", "name"),
    CheckConstraint(_in("status", TrackStatus), name="status"),
)

skills = Table(
    "skills",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("profile_id", BigInteger, ForeignKey("profiles.id"), nullable=False),
    Column("label_fr", Text, nullable=False),
    Column("label_en", Text),
    Column("aliases", _list(), nullable=False, server_default=_empty_list()),
    Column("category", Text, nullable=False),
    Column("level", Text),
    Column("is_key", Boolean, nullable=False, server_default=text("false")),
    _created(),
    # The pair lets skill_terms and the link tables check that a skill belongs to their profile.
    UniqueConstraint("profile_id", "id"),
    CheckConstraint(_in("category", SkillCategory), name="category"),
    CheckConstraint(_in("level", SkillLevel), name="level"),
    Index("ix_skills_profile_id", "profile_id"),
)

# Every name a skill answers to (French and English labels, aliases), normalized: the primary key forbids
# two skills of a profile to share one. This is what makes "no duplicate skill" a database guarantee.
skill_terms = Table(
    "skill_terms",
    metadata,
    Column("profile_id", BigInteger, nullable=False),
    Column("term", Text, nullable=False),
    Column("skill_id", BigInteger, nullable=False),
    PrimaryKeyConstraint("profile_id", "term"),
    ForeignKeyConstraint(
        ["profile_id", "skill_id"],
        ["skills.profile_id", "skills.id"],
        ondelete="CASCADE",
    ),
    Index("ix_skill_terms_skill_id", "skill_id"),
)

languages = Table(
    "languages",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("profile_id", BigInteger, ForeignKey("profiles.id"), nullable=False),
    Column("code", Text, nullable=False),
    Column("level", Text, nullable=False),
    _created(),
    UniqueConstraint("profile_id", "code"),
    CheckConstraint(_in("level", LanguageLevel), name="level"),
)

experiences = Table(
    "experiences",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("profile_id", BigInteger, ForeignKey("profiles.id"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("title_fr", Text, nullable=False),
    Column("title_en", Text),
    Column("organisation", Text, nullable=False),
    Column("place", Text),
    Column("start_month", Date, nullable=False),
    Column("end_month", Date),
    Column("bullets_fr", _list(), nullable=False, server_default=_empty_list()),
    Column("bullets_en", _list(), nullable=False, server_default=_empty_list()),
    _created(),
    UniqueConstraint("profile_id", "id"),
    CheckConstraint(_in("kind", ExperienceKind), name="kind"),
    CheckConstraint("end_month IS NULL OR end_month >= start_month", name="dates"),
    Index("ix_experiences_profile_id", "profile_id"),
)

projects = Table(
    "projects",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("profile_id", BigInteger, ForeignKey("profiles.id"), nullable=False),
    Column("name_fr", Text, nullable=False),
    Column("name_en", Text),
    Column("problem_fr", Text),
    Column("problem_en", Text),
    Column("work_fr", Text),
    Column("work_en", Text),
    Column("results_fr", Text),
    Column("results_en", Text),
    Column("stack", _list(), nullable=False, server_default=_empty_list()),
    Column("url", Text),
    _created(),
    UniqueConstraint("profile_id", "id"),
    Index("ix_projects_profile_id", "profile_id"),
)


def _link_table(name: str, owner: str) -> Table:
    """Skills linked to an experience or a project, both of the same profile."""
    return Table(
        name,
        metadata,
        Column("profile_id", BigInteger, nullable=False),
        Column(f"{owner}_id", BigInteger, nullable=False),
        Column("skill_id", BigInteger, nullable=False),
        PrimaryKeyConstraint(f"{owner}_id", "skill_id"),
        ForeignKeyConstraint(
            ["profile_id", f"{owner}_id"],
            [f"{owner}s.profile_id", f"{owner}s.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["profile_id", "skill_id"],
            ["skills.profile_id", "skills.id"],
            ondelete="CASCADE",
        ),
        Index(f"ix_{name}_skill_id", "skill_id"),
    )


experience_skills = _link_table("experience_skills", "experience")
project_skills = _link_table("project_skills", "project")


class SqlProfileStore:
    """``ProfileStore`` on a connection already inside a transaction; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    # Profile row

    def find_profile_id(self, account_id: int) -> int | None:
        found = self._conn.execute(
            select(profiles.c.id).where(profiles.c.account_id == account_id)
        ).scalar_one_or_none()
        return None if found is None else int(found)

    def create_profile(self, account_id: int, contact_email: str, now: datetime) -> int:
        statement = (
            insert(profiles)
            .values(
                account_id=account_id,
                contact_email=contact_email,
                created_at=now,
                updated_at=now,
            )
            .returning(profiles.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def onboarding_state(self, account_id: int) -> OnboardingState | None:
        row = self._conn.execute(
            select(
                profiles.c.onboarding_completed_at, profiles.c.onboarding_deferred_at
            ).where(profiles.c.account_id == account_id)
        ).one_or_none()
        if row is None:
            return None
        return OnboardingState(
            completed_at=row.onboarding_completed_at,
            deferred_at=row.onboarding_deferred_at,
        )

    def load(self, profile_id: int) -> Profile:
        row = self._conn.execute(
            select(profiles).where(profiles.c.id == profile_id)
        ).one()
        return Profile(
            id=row.id,
            account_id=row.account_id,
            identity=_identity(row),
            preferences=Preferences(
                contracts=tuple(Contract(c) for c in row.contracts),
                remote_modes=tuple(RemoteMode(m) for m in row.remote_modes),
                min_salary_eur=row.min_salary_eur,
                min_daily_rate_eur=row.min_daily_rate_eur,
            ),
            onboarding=OnboardingState(
                completed_at=row.onboarding_completed_at,
                deferred_at=row.onboarding_deferred_at,
            ),
            tracks=self._tracks(profile_id),
            skills=self._skills(profile_id),
            languages=self._languages(profile_id),
            experiences=self._experiences(profile_id),
            projects=self._projects(profile_id),
        )

    def save_identity(
        self, profile_id: int, identity: model.Identity, now: datetime
    ) -> None:
        self._update_profile(
            profile_id,
            now,
            full_name=identity.full_name or None,
            contact_email=identity.contact_email,
            phone=identity.phone,
            city=identity.city,
            postal_code=identity.postal_code,
            linkedin_url=identity.linkedin_url,
            github_url=identity.github_url,
            portfolio_url=identity.portfolio_url,
            headline_fr=identity.headline.fr or None,
            headline_en=identity.headline.en,
        )

    def save_preferences(
        self, profile_id: int, preferences: Preferences, now: datetime
    ) -> None:
        self._update_profile(
            profile_id,
            now,
            contracts=[c.value for c in preferences.contracts],
            remote_modes=[m.value for m in preferences.remote_modes],
            min_salary_eur=preferences.min_salary_eur,
            min_daily_rate_eur=preferences.min_daily_rate_eur,
        )

    def mark_onboarding_completed(self, profile_id: int, now: datetime) -> None:
        self._update_profile(profile_id, now, onboarding_completed_at=now)

    def mark_onboarding_deferred(self, profile_id: int, now: datetime) -> None:
        self._update_profile(profile_id, now, onboarding_deferred_at=now)

    # Tracks

    def add_track(self, profile_id: int, track: TrackDraft, now: datetime) -> int:
        statement = (
            insert(search_tracks)
            .values(
                profile_id=profile_id,
                status=TrackStatus.ACTIVE.value,
                created_at=now,
                updated_at=now,
                **_track_values(track),
            )
            .returning(search_tracks.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def update_track(
        self, profile_id: int, track_id: int, track: TrackDraft, now: datetime
    ) -> bool:
        return self._update_owned(
            search_tracks, profile_id, track_id, updated_at=now, **_track_values(track)
        )

    def set_track_status(
        self, profile_id: int, track_id: int, status: TrackStatus, now: datetime
    ) -> bool:
        return self._update_owned(
            search_tracks, profile_id, track_id, status=status.value, updated_at=now
        )

    def delete_track(self, profile_id: int, track_id: int) -> bool:
        return self._delete_owned(search_tracks, profile_id, track_id)

    # Skills

    def term_owners(
        self, profile_id: int, terms: frozenset[str], except_skill: int | None
    ) -> list[str]:
        statement = (
            select(skills.c.label_fr)
            .distinct()
            .join(
                skill_terms,
                (skill_terms.c.skill_id == skills.c.id)
                & (skill_terms.c.profile_id == skills.c.profile_id),
            )
            .where(skill_terms.c.profile_id == profile_id)
            .where(skill_terms.c.term.in_(sorted(terms)))
            .order_by(skills.c.label_fr)
        )
        if except_skill is not None:
            statement = statement.where(skills.c.id != except_skill)
        return list(self._conn.execute(statement).scalars())

    def add_skill(
        self, profile_id: int, skill: SkillDraft, terms: frozenset[str]
    ) -> int:
        statement = (
            insert(skills)
            .values(profile_id=profile_id, **_skill_values(skill))
            .returning(skills.c.id)
        )
        skill_id = int(self._conn.execute(statement).scalar_one())
        self._write_terms(profile_id, skill_id, terms)
        return skill_id

    def update_skill(
        self,
        profile_id: int,
        skill_id: int,
        skill: SkillDraft,
        terms: frozenset[str],
    ) -> bool:
        if not self._update_owned(skills, profile_id, skill_id, **_skill_values(skill)):
            return False
        self._conn.execute(
            delete(skill_terms).where(skill_terms.c.skill_id == skill_id)
        )
        self._write_terms(profile_id, skill_id, terms)
        return True

    def delete_skill(self, profile_id: int, skill_id: int) -> bool:
        return self._delete_owned(skills, profile_id, skill_id)

    def _write_terms(
        self, profile_id: int, skill_id: int, terms: frozenset[str]
    ) -> None:
        self._conn.execute(
            insert(skill_terms),
            [
                {"profile_id": profile_id, "term": term, "skill_id": skill_id}
                for term in sorted(terms)
            ],
        )

    # Languages

    def add_language(self, profile_id: int, language: LanguageDraft) -> int:
        statement = (
            insert(languages)
            .values(
                profile_id=profile_id, code=language.code, level=language.level.value
            )
            .returning(languages.c.id)
        )
        return int(self._conn.execute(statement).scalar_one())

    def update_language(
        self, profile_id: int, language_id: int, language: LanguageDraft
    ) -> bool:
        return self._update_owned(
            languages,
            profile_id,
            language_id,
            code=language.code,
            level=language.level.value,
        )

    def delete_language(self, profile_id: int, language_id: int) -> bool:
        return self._delete_owned(languages, profile_id, language_id)

    # Experiences and projects

    def add_experience(self, profile_id: int, experience: ExperienceDraft) -> int:
        statement = (
            insert(experiences)
            .values(profile_id=profile_id, **_experience_values(experience))
            .returning(experiences.c.id)
        )
        experience_id = int(self._conn.execute(statement).scalar_one())
        self._link(
            experience_skills,
            "experience_id",
            profile_id,
            experience_id,
            experience.skill_ids,
        )
        return experience_id

    def update_experience(
        self, profile_id: int, experience_id: int, experience: ExperienceDraft
    ) -> bool:
        if not self._update_owned(
            experiences, profile_id, experience_id, **_experience_values(experience)
        ):
            return False
        self._link(
            experience_skills,
            "experience_id",
            profile_id,
            experience_id,
            experience.skill_ids,
        )
        return True

    def delete_experience(self, profile_id: int, experience_id: int) -> bool:
        return self._delete_owned(experiences, profile_id, experience_id)

    def add_project(self, profile_id: int, project: ProjectDraft) -> int:
        statement = (
            insert(projects)
            .values(profile_id=profile_id, **_project_values(project))
            .returning(projects.c.id)
        )
        project_id = int(self._conn.execute(statement).scalar_one())
        self._link(
            project_skills, "project_id", profile_id, project_id, project.skill_ids
        )
        return project_id

    def update_project(
        self, profile_id: int, project_id: int, project: ProjectDraft
    ) -> bool:
        if not self._update_owned(
            projects, profile_id, project_id, **_project_values(project)
        ):
            return False
        self._link(
            project_skills, "project_id", profile_id, project_id, project.skill_ids
        )
        return True

    def delete_project(self, profile_id: int, project_id: int) -> bool:
        return self._delete_owned(projects, profile_id, project_id)

    def append_event(self, event: NewEvent) -> None:
        append_event(self._conn, event)

    # Reading

    def _tracks(self, profile_id: int) -> tuple[Track, ...]:
        rows = self._conn.execute(
            select(search_tracks)
            .where(search_tracks.c.profile_id == profile_id)
            .order_by(search_tracks.c.id)
        )
        return tuple(
            Track(
                id=row.id,
                status=TrackStatus(row.status),
                content=TrackDraft(
                    name=row.name,
                    titles=tuple(row.titles),
                    keywords=tuple(row.keywords),
                    excluded_keywords=tuple(row.excluded_keywords),
                    locations=tuple(row.locations),
                ),
            )
            for row in rows
        )

    def _skills(self, profile_id: int) -> tuple[Skill, ...]:
        rows = self._conn.execute(
            select(skills)
            .where(skills.c.profile_id == profile_id)
            .order_by(func.lower(skills.c.label_fr), skills.c.id)
        )
        return tuple(
            Skill(
                id=row.id,
                content=SkillDraft(
                    label=model.Text(row.label_fr, row.label_en),
                    category=SkillCategory(row.category),
                    aliases=tuple(row.aliases),
                    level=SkillLevel(row.level) if row.level else None,
                    is_key=row.is_key,
                ),
            )
            for row in rows
        )

    def _languages(self, profile_id: int) -> tuple[Language, ...]:
        rows = self._conn.execute(
            select(languages)
            .where(languages.c.profile_id == profile_id)
            .order_by(languages.c.id)
        )
        return tuple(
            Language(
                id=row.id,
                content=LanguageDraft(code=row.code, level=LanguageLevel(row.level)),
            )
            for row in rows
        )

    def _experiences(self, profile_id: int) -> tuple[Experience, ...]:
        links = self._links(experience_skills, "experience_id", profile_id)
        rows = self._conn.execute(
            select(experiences)
            .where(experiences.c.profile_id == profile_id)
            # Current first, then the most recent.
            .order_by(
                experiences.c.end_month.desc().nulls_first(),
                experiences.c.start_month.desc(),
                experiences.c.id,
            )
        )
        return tuple(
            Experience(
                id=row.id,
                content=ExperienceDraft(
                    kind=ExperienceKind(row.kind),
                    title=model.Text(row.title_fr, row.title_en),
                    organisation=row.organisation,
                    start=row.start_month,
                    end=row.end_month,
                    place=row.place,
                    bullets_fr=tuple(row.bullets_fr),
                    bullets_en=tuple(row.bullets_en),
                    skill_ids=links.get(row.id, ()),
                ),
            )
            for row in rows
        )

    def _projects(self, profile_id: int) -> tuple[Project, ...]:
        links = self._links(project_skills, "project_id", profile_id)
        rows = self._conn.execute(
            select(projects)
            .where(projects.c.profile_id == profile_id)
            .order_by(projects.c.id)
        )
        return tuple(
            Project(
                id=row.id,
                content=ProjectDraft(
                    name=model.Text(row.name_fr, row.name_en),
                    problem=model.Text(row.problem_fr or "", row.problem_en),
                    work=model.Text(row.work_fr or "", row.work_en),
                    results=model.Text(row.results_fr or "", row.results_en),
                    stack=tuple(row.stack),
                    url=row.url,
                    skill_ids=links.get(row.id, ()),
                ),
            )
            for row in rows
        )

    def _links(
        self, table: Table, owner: str, profile_id: int
    ) -> dict[int, tuple[int, ...]]:
        rows = self._conn.execute(
            select(table.c[owner], table.c.skill_id)
            .where(table.c.profile_id == profile_id)
            .order_by(table.c[owner], table.c.skill_id)
        )
        found: dict[int, list[int]] = {}
        for owner_id, skill_id in rows:
            found.setdefault(owner_id, []).append(skill_id)
        return {owner_id: tuple(ids) for owner_id, ids in found.items()}

    # Writing helpers

    def _link(
        self,
        table: Table,
        owner: str,
        profile_id: int,
        owner_id: int,
        skill_ids: Sequence[int],
    ) -> None:
        """Replace the skills linked to one owner; a skill of another profile is refused by the database."""
        self._conn.execute(delete(table).where(table.c[owner] == owner_id))
        if skill_ids:
            self._conn.execute(
                insert(table),
                [
                    {"profile_id": profile_id, owner: owner_id, "skill_id": skill_id}
                    for skill_id in skill_ids
                ],
            )

    def _update_profile(self, profile_id: int, now: datetime, **values: Any) -> None:
        self._conn.execute(
            update(profiles)
            .where(profiles.c.id == profile_id)
            .values(updated_at=now, **values)
        )

    def _update_owned(
        self, table: Table, profile_id: int, item_id: int, **values: Any
    ) -> bool:
        result = self._conn.execute(
            update(table)
            .where(table.c.id == item_id, table.c.profile_id == profile_id)
            .values(**values)
        )
        return result.rowcount == 1

    def _delete_owned(self, table: Table, profile_id: int, item_id: int) -> bool:
        result = self._conn.execute(
            delete(table).where(table.c.id == item_id, table.c.profile_id == profile_id)
        )
        return result.rowcount == 1


def _identity(row: Row[Any]) -> model.Identity:
    return model.Identity(
        full_name=row.full_name or "",
        contact_email=row.contact_email,
        phone=row.phone,
        city=row.city,
        postal_code=row.postal_code,
        linkedin_url=row.linkedin_url,
        github_url=row.github_url,
        portfolio_url=row.portfolio_url,
        headline=model.Text(row.headline_fr or "", row.headline_en),
    )


def _track_values(track: TrackDraft) -> dict[str, Any]:
    return {
        "name": track.name,
        "titles": list(track.titles),
        "keywords": list(track.keywords),
        "excluded_keywords": list(track.excluded_keywords),
        "locations": list(track.locations),
    }


def _skill_values(skill: SkillDraft) -> dict[str, Any]:
    return {
        "label_fr": skill.label.fr,
        "label_en": skill.label.en,
        "aliases": list(skill.aliases),
        "category": skill.category.value,
        "level": skill.level.value if skill.level else None,
        "is_key": skill.is_key,
    }


def _experience_values(experience: ExperienceDraft) -> dict[str, Any]:
    return {
        "kind": experience.kind.value,
        "title_fr": experience.title.fr,
        "title_en": experience.title.en,
        "organisation": experience.organisation,
        "place": experience.place,
        "start_month": experience.start,
        "end_month": experience.end,
        "bullets_fr": list(experience.bullets_fr),
        "bullets_en": list(experience.bullets_en),
    }


def _project_values(project: ProjectDraft) -> dict[str, Any]:
    return {
        "name_fr": project.name.fr,
        "name_en": project.name.en,
        "problem_fr": project.problem.fr or None,
        "problem_en": project.problem.en,
        "work_fr": project.work.fr or None,
        "work_en": project.work.en,
        "results_fr": project.results.fr or None,
        "results_en": project.results.en,
        "stack": list(project.stack),
        "url": project.url,
    }
