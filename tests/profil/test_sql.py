"""The profile store on PostgreSQL: round trips, and what the database itself refuses."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from rocky.profil.model import (
    CvLayout,
    Hobby,
    SkillCategory,
    SkillGroup,
    StoredPhoto,
    Text,
    TrackStatus,
)
from rocky.profil.rules import (
    ProfileInputError,
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
    skill_groups,
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


# Master CV (decision D2)


def test_links_photo_and_master_cv_round_trip(db: Connection) -> None:
    editor = new_editor(db)
    editor.save_identity(
        make_identity(
            full_name="Nicolas",
            links="https://github.com/n\nhttps://huggingface.co/n",
            title_fr="Data Scientist",
            birth_date="1989-03-15",
            show_age=True,
        )
    )
    editor.save_photo(StoredPhoto("comptes/1/photos/abc.jpg", "abc"))
    python = editor.add_skill(make_skill(label_fr="Python", category="technical"))
    sql = editor.add_skill(make_skill(label_fr="SQL", category="technical"))
    curiosity = editor.add_skill(make_skill(label_fr="Curiosité", category="soft"))
    project = editor.add_project(make_project(name_fr="Rocky"))
    layout = CvLayout(
        groups=(
            SkillGroup(Text("Data", "Data"), (sql, python)),
            SkillGroup(Text("Vide")),
        ),
        transversal=(curiosity,),
        projects=(project,),
        hobbies=(Hobby(Text("Échecs", "Chess")), Hobby(Text("Piano"), in_cv=False)),
    )

    editor.save_cv_layout(layout)
    profile = editor.profile()

    assert [link.label for link in profile.identity.links] == ["GitHub", "Hugging Face"]
    assert profile.identity.title == Text("Data Scientist")
    assert profile.identity.birth_date == date(1989, 3, 15)
    assert profile.identity.show_age
    assert profile.photo == StoredPhoto("comptes/1/photos/abc.jpg", "abc")
    assert profile.cv == layout

    editor.save_cv_layout(CvLayout())  # replaced whole, groups included
    assert editor.profile().cv == CvLayout()


def test_the_database_refuses_a_technical_skill_in_the_cv_without_group(
    db: Connection,
) -> None:
    editor = new_editor(db)
    python = editor.add_skill(make_skill(label_fr="Python", category="technical"))

    with pytest.raises(IntegrityError, match="ck_skills_cv_placement"):
        db.execute(update(skills).where(skills.c.id == python).values(cv_position=0))


def test_the_database_refuses_the_group_of_another_profile(db: Connection) -> None:
    first, second = new_editor(db), new_editor(db)
    first.save_cv_layout(CvLayout(groups=(SkillGroup(Text("Data")),)))
    group_id = db.execute(
        select(skill_groups.c.id).where(skill_groups.c.profile_id == first.profile().id)
    ).scalar_one()
    python = second.add_skill(make_skill(label_fr="Python", category="technical"))

    with pytest.raises(IntegrityError, match="fk_skills_profile_id_skill_groups"):
        db.execute(
            update(skills)
            .where(skills.c.id == python)
            .values(group_id=group_id, cv_position=0)
        )


def test_a_skill_of_a_group_can_be_deleted(db: Connection) -> None:
    editor = new_editor(db)
    python = editor.add_skill(make_skill(label_fr="Python", category="technical"))
    editor.save_cv_layout(CvLayout(groups=(SkillGroup(Text("Data"), (python,)),)))

    assert editor.delete_skill(python)
    assert editor.profile().cv.groups == (SkillGroup(Text("Data")),)


def test_one_active_template_per_language(db: Connection) -> None:
    editor = new_editor(db)
    french = editor.record_cv_template("comptes/1/gabarits/a", "a", "CV français", "fr")
    english = editor.record_cv_template("comptes/1/gabarits/b", "b", "CV anglais", "en")
    other = editor.record_cv_template(
        "comptes/1/gabarits/c", "c", "Autre CV français", "fr"
    )

    assert editor.activate_cv_template(french, "fr")
    assert editor.activate_cv_template(english, "en")
    assert not editor.activate_cv_template(english, "fr")  # not a French template
    assert editor.activate_cv_template(other, "fr")

    active = editor.active_cv_template("fr")
    assert active is not None
    assert active.id == other
    english_active = editor.active_cv_template("en")
    assert english_active is not None
    assert english_active.id == english
    assert editor.activate_cv_template(None, "en")
    assert editor.active_cv_template("en") is None


def test_a_template_no_longer_used_is_deleted_never_the_one_in_service(
    db: Connection,
) -> None:
    """Decision D6, Q8: the row goes, journalized; the bundle stays in the files root."""
    editor = new_editor(db)
    used = editor.record_cv_template("comptes/1/gabarits/u", "u", "CV en service", "fr")
    trial = editor.record_cv_template("comptes/1/gabarits/t", "t", "Essai", "fr")
    editor.activate_cv_template(used, "fr")

    with pytest.raises(ProfileInputError, match="celui de ton CV"):
        editor.delete_cv_template(used)
    assert editor.delete_cv_template(trial)

    assert [t.id for t in editor.cv_templates()] == [used]
    assert not editor.delete_cv_template(trial)  # gone already
    payload = db.execute(
        select(events.c.payload).where(
            events.c.type == "profil.cv_template_deleted",
            events.c.subject_id == str(trial),
        )
    ).scalar_one()
    assert payload == {"sha256": "t", "name": "Essai", "language": "fr"}


def test_the_english_stack_of_a_project_round_trips(db: Connection) -> None:
    editor = new_editor(db)
    untranslated = editor.add_project(
        make_project(name_fr="Tri", stack="Python\nBase vectorielle")
    )
    translated = editor.add_project(
        make_project(name_fr="Prévision", stack="Python", stack_en="Python\n")
    )

    projects = {project.id: project.content for project in editor.profile().projects}

    assert projects[untranslated].stack_en is None
    assert projects[translated].stack_en == ("Python",)


def test_a_glossary_term_is_replaced_by_its_french_term(db: Connection) -> None:
    editor = new_editor(db)
    profile_id = editor.profile().id
    store = SqlProfileStore(db)
    first = store.save_glossary_term(
        profile_id, "pilotage", "Pilotage", "Steering", FakeClock()()
    )
    again = store.save_glossary_term(
        profile_id, "pilotage", "pilotage", "Oversight", FakeClock()()
    )
    kept = store.save_glossary_term(
        profile_id, "eure et loir", "Eure-et-Loir", "Eure-et-Loir", FakeClock()()
    )

    assert first == again
    assert [(term.fr, term.en) for term in store.glossary(profile_id)] == [
        ("Eure-et-Loir", "Eure-et-Loir"),
        ("pilotage", "Oversight"),
    ]
    assert store.delete_glossary_term(profile_id, kept)
    assert not store.delete_glossary_term(new_editor(db).profile().id, first)


def test_the_translation_memory_keeps_the_latest_validation(db: Connection) -> None:
    editor = new_editor(db)
    profile_id = editor.profile().id
    store = SqlProfileStore(db)
    store.remember_translation(
        profile_id, "Analyse de sentiment", "Sentiment analysis", FakeClock()()
    )
    store.remember_translation(
        profile_id, "Analyse de sentiment", "Sentiment analytics", FakeClock()()
    )

    memory = store.translation_memory(profile_id)

    assert [(entry.source, entry.translation) for entry in memory.values()] == [
        ("Analyse de sentiment", "Sentiment analytics")
    ]


def test_an_english_template_keeps_the_french_one_it_comes_from(db: Connection) -> None:
    editor = new_editor(db)
    profile_id = editor.profile().id
    store = SqlProfileStore(db)
    store.add_cv_template(
        profile_id,
        "comptes/1/gabarits/en",
        "en",
        "CV anglais",
        "en",
        FakeClock()(),
        source_sha256="fr",
    )

    (template,) = store.cv_templates(profile_id)

    assert template.source_sha256 == "fr"


def test_the_goal_of_the_week_round_trips_and_the_base_bounds_it(
    db: Connection,
) -> None:
    editor = new_editor(db)
    editor.set_weekly_goal(7)

    assert editor.profile().weekly_goal == 7
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(update(profiles).values(weekly_goal=0))
