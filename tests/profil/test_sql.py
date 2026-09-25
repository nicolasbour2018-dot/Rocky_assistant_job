"""The profile store on PostgreSQL: round trips, and what the database itself refuses."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Connection, func, insert, select
from sqlalchemy.exc import IntegrityError

from rocky.profil.model import SkillCategory, TrackStatus
from rocky.profil.rules import (
    make_experience,
    make_identity,
    make_language,
    make_preferences,
    make_project,
    make_skill,
    make_track,
)
from rocky.profil.sql import (
    SqlProfileStore,
    experience_skills,
    profiles,
    skill_terms,
    skills,
)
from rocky.profil.usecases import ProfileEditor
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.events import events
from tests.system.auth.fakes import FakeClock


def new_editor(db: Connection) -> ProfileEditor:
    email = f"{uuid4().hex}@example.fr"
    account_id = SqlAuthStore(db).create_account(email, FakeClock()())
    return ProfileEditor(
        SqlProfileStore(db), clock=FakeClock(), account_id=account_id, email=email
    )


def test_a_whole_profile_round_trips(db: Connection) -> None:
    editor = new_editor(db)
    editor.save_identity(
        make_identity(
            full_name="Nicolas",
            city="Paris",
            headline_fr="Data scientist",
            headline_en="Data scientist",
        )
    )
    editor.save_preferences(
        make_preferences(
            contracts=["permanent", "freelance"],
            remote_modes=["hybrid"],
            min_salary_eur=45_000,
            min_daily_rate_eur=450,
        )
    )
    nlp = editor.add_skill(
        make_skill(
            label_fr="NLP",
            label_en="Natural Language Processing (NLP)",
            aliases=["Traitement du langage naturel (NLP)"],
            category="technical",
            level="advanced",
            is_key=True,
        )
    )
    editor.add_language(make_language(code_value="en", level="c1"))
    editor.add_experience(
        make_experience(
            kind="job",
            title_fr="Data scientist",
            title_en="Data scientist",
            organisation="Exemple",
            start="2024-09",
            bullets_fr="Modèle de scoring",
            skill_ids=[nlp],
        )
    )
    editor.add_project(
        make_project(name_fr="Finance connectée", stack="Python", skill_ids=[nlp])
    )
    editor.add_track(
        make_track(name="IA", titles="ML Engineer", keywords="NLP", locations="Paris")
    )

    profile = editor.profile()

    assert profile.identity.full_name == "Nicolas"
    assert profile.identity.headline.en == "Data scientist"
    assert profile.preferences.min_daily_rate_eur == 450
    [skill] = profile.skills
    assert skill.content.aliases == ("Traitement du langage naturel (NLP)",)
    assert skill.content.category is SkillCategory.TECHNICAL
    [experience] = profile.experiences
    assert experience.content.start == date(2024, 9, 1)
    assert experience.content.skill_ids == (nlp,)
    assert profile.projects[0].content.skill_ids == (nlp,)
    assert profile.projects[0].content.problem.fr == ""
    assert profile.tracks[0].content.keywords == ("NLP",)
    assert profile.onboarding.completed_at is not None


def test_the_database_refuses_two_skills_sharing_a_name(db: Connection) -> None:
    editor = new_editor(db)
    editor.add_skill(make_skill(label_fr="NLP", category="technical"))
    profile_id = editor.profile().id
    other = db.execute(
        insert(skills)
        .values(profile_id=profile_id, label_fr="nlp", category="technical")
        .returning(skills.c.id)
    ).scalar_one()

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(skill_terms).values(
                profile_id=profile_id, term="nlp", skill_id=other
            )
        )


def test_a_skill_of_another_profile_cannot_be_linked(db: Connection) -> None:
    mine, theirs = new_editor(db), new_editor(db)
    experience_id = mine.add_experience(
        make_experience(kind="job", title_fr="A", organisation="B", start="2020-01")
    )
    their_skill = theirs.add_skill(make_skill(label_fr="SQL", category="technical"))

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(experience_skills).values(
                profile_id=mine.profile().id,
                experience_id=experience_id,
                skill_id=their_skill,
            )
        )


def test_removing_a_skill_removes_its_names_and_links(db: Connection) -> None:
    editor = new_editor(db)
    sql_id = editor.add_skill(
        make_skill(label_fr="SQL", aliases="PostgreSQL", category="technical")
    )
    editor.add_experience(
        make_experience(
            kind="job",
            title_fr="A",
            organisation="B",
            start="2020-01",
            skill_ids=[sql_id],
        )
    )

    assert editor.delete_skill(sql_id)

    assert editor.profile().experiences[0].content.skill_ids == ()
    remaining = db.execute(
        select(func.count()).where(skill_terms.c.skill_id == sql_id)
    ).scalar_one()
    assert remaining == 0
    # The name is free again.
    editor.add_skill(make_skill(label_fr="PostgreSQL", category="technical"))


def test_items_of_another_profile_are_out_of_reach(db: Connection) -> None:
    mine, theirs = new_editor(db), new_editor(db)
    track_id = theirs.add_track(make_track(name="IA"))
    skill_id = theirs.add_skill(make_skill(label_fr="SQL", category="technical"))

    assert not mine.update_track(track_id, make_track(name="Volée"))
    assert not mine.archive_track(track_id)
    assert not mine.delete_track(track_id)
    assert not mine.delete_skill(skill_id)
    assert theirs.profile().tracks[0].status is TrackStatus.ACTIVE


def test_track_events_are_written_with_the_change(db: Connection) -> None:
    editor = new_editor(db)
    track_id = editor.add_track(make_track(name="IA", titles="ML Engineer"))

    rows = db.execute(
        select(events.c.type, events.c.payload).where(
            events.c.subject_type == "search_track",
            events.c.subject_id == str(track_id),
        )
    ).all()

    assert [row.type for row in rows] == ["profil.track_created"]
    assert rows[0].payload["titles"] == ["ML Engineer"]


def test_a_profile_is_unique_per_account(db: Connection) -> None:
    editor = new_editor(db)
    account_id = editor.profile().account_id

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert(profiles).values(account_id=account_id))


def test_unknown_contract_codes_are_refused(db: Connection) -> None:
    editor = new_editor(db)
    profile_id = editor.profile().id

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            profiles.update()
            .where(profiles.c.id == profile_id)
            .values(contracts=["CDI"])
        )


def test_asking_for_the_onboarding_does_not_create_a_profile(db: Connection) -> None:
    account_id = SqlAuthStore(db).create_account(
        f"{uuid4().hex}@example.fr", FakeClock()()
    )
    store = SqlProfileStore(db)
    editor = ProfileEditor(store, clock=FakeClock(), account_id=account_id, email="x")

    assert editor.needs_onboarding()
    assert store.find_profile_id(account_id) is None
