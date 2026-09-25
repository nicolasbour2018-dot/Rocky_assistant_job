from __future__ import annotations

import pytest

from rocky.profil.model import (
    ImportedExperience,
    ImportedProfile,
    SkillCategory,
    TrackStatus,
)
from rocky.profil.rules import (
    ProfileInputError,
    make_experience,
    make_identity,
    make_language,
    make_preferences,
    make_skill,
    make_track,
)
from rocky.profil.usecases import AlreadyFilled, ProfileEditor, ProfileImported
from rocky.system.events import Actor
from tests.profil.fakes import InMemoryProfileStore
from tests.system.auth.fakes import FakeClock


def editor(store: InMemoryProfileStore, account_id: int = 7) -> ProfileEditor:
    return ProfileEditor(
        store, clock=FakeClock(), account_id=account_id, email="n@example.fr"
    )


def test_the_profile_is_created_on_first_use_with_the_account_address() -> None:
    store = InMemoryProfileStore()

    assert editor(store).needs_onboarding()
    assert store.profiles == {}  # asking does not create it

    profile = editor(store).profile()

    assert profile.account_id == 7
    assert profile.identity.contact_email == "n@example.fr"
    assert editor(store).profile().id == profile.id  # one account, one profile


def test_a_ready_track_completes_the_onboarding_once() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)

    profile_editor.add_track(make_track(name="IA", titles="ML Engineer"))
    assert profile_editor.needs_onboarding()

    track_id = profile_editor.add_track(
        make_track(name="Data analyst", titles="Data Analyst", locations="Paris")
    )
    profile_editor.pause_track(track_id)
    profile_editor.resume_track(track_id)

    assert not profile_editor.needs_onboarding()
    assert store.event_types() == [
        "profil.track_created",
        "profil.track_created",
        "profil.onboarding_completed",
        "profil.track_paused",
        "profil.track_resumed",
    ]
    created = store.events[1]
    assert created.actor is Actor.USER
    assert created.account_id == 7
    assert created.subject_type == "search_track"
    assert created.payload["titles"] == ["Data Analyst"]


def test_putting_the_onboarding_off_stops_the_redirection() -> None:
    store = InMemoryProfileStore()

    editor(store).defer_onboarding()

    assert not editor(store).needs_onboarding()


def test_track_names_are_unique_in_a_profile() -> None:
    profile_editor = editor(InMemoryProfileStore())
    profile_editor.add_track(make_track(name="Data analyst"))

    with pytest.raises(ProfileInputError, match="s'appelle déjà"):
        profile_editor.add_track(make_track(name="data  ANALYST"))


def test_track_life_cycle_and_final_removal() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)
    track_id = profile_editor.add_track(make_track(name="IA"))

    assert profile_editor.archive_track(track_id)
    assert profile_editor.profile().tracks[0].status is TrackStatus.ARCHIVED
    assert profile_editor.archive_track(track_id)  # already archived: no new event
    assert profile_editor.delete_track(track_id)
    assert not profile_editor.delete_track(track_id)
    assert store.event_types()[-2:] == ["profil.track_archived", "profil.track_deleted"]


def test_an_unchanged_track_writes_no_event() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)
    track = make_track(name="IA", titles="ML Engineer")
    track_id = profile_editor.add_track(track)

    assert profile_editor.update_track(track_id, track)
    assert profile_editor.update_track(
        track_id, make_track(name="IA", titles="ML Engineer\nNLP Engineer")
    )

    assert store.event_types() == ["profil.track_created", "profil.track_updated"]


def test_a_skill_already_known_under_another_name_is_refused() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)
    profile_editor.add_skill(
        make_skill(
            label_fr="NLP",
            aliases="Traitement du langage naturel (NLP)",
            category="technical",
        )
    )

    with pytest.raises(ProfileInputError, match="déjà présent sous « NLP »"):
        profile_editor.add_skill(
            make_skill(
                label_fr="traitement du langage naturel (nlp)", category="technical"
            )
        )
    assert len(profile_editor.profile().skills) == 1


def test_a_skill_can_keep_its_own_names_when_edited() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)
    skill_id = profile_editor.add_skill(
        make_skill(label_fr="SQL", category="technical")
    )

    assert profile_editor.update_skill(
        skill_id, make_skill(label_fr="SQL", category="technical", level="expert")
    )
    assert store.event_types() == ["profil.skill_added", "profil.skill_updated"]


def test_quick_entry_reports_the_skills_already_there() -> None:
    profile_editor = editor(InMemoryProfileStore())
    profile_editor.add_skill(make_skill(label_fr="Python", category="technical"))

    result = profile_editor.add_skills(
        {
            SkillCategory.TECHNICAL: ["python", "SQL"],
            SkillCategory.SOFT: ["Curiosité"],
        }
    )

    assert result.added == ("SQL", "Curiosité")
    assert result.already_there == ("python",)


def test_removing_a_skill_is_journaled() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)
    skill_id = profile_editor.add_skill(
        make_skill(label_fr="SQL", category="technical")
    )

    assert profile_editor.delete_skill(skill_id)
    assert not profile_editor.delete_skill(skill_id)
    assert store.event_types() == ["profil.skill_added", "profil.skill_removed"]
    assert store.terms == {}


def test_a_language_appears_once() -> None:
    profile_editor = editor(InMemoryProfileStore())
    profile_editor.add_language(make_language(code_value="en", level="c1"))

    with pytest.raises(ProfileInputError, match="figure déjà"):
        profile_editor.add_language(make_language(code_value="en", level="b2"))


def test_linked_skills_must_belong_to_the_profile() -> None:
    profile_editor = editor(InMemoryProfileStore())

    with pytest.raises(ProfileInputError, match="n'existe pas"):
        profile_editor.add_experience(
            make_experience(
                kind="job",
                title_fr="Analyste",
                organisation="X",
                start="2020-01",
                skill_ids=[999],
            )
        )


def test_preferences_are_journaled_only_when_they_change() -> None:
    store = InMemoryProfileStore()
    profile_editor = editor(store)
    preferences = make_preferences(contracts=["permanent"], min_daily_rate_eur="450")

    profile_editor.save_preferences(preferences)
    profile_editor.save_preferences(preferences)

    assert store.event_types() == ["profil.preferences_updated"]
    assert store.events[0].payload["min_daily_rate_eur"] == 450


def imported_profile() -> ImportedProfile:
    return ImportedProfile(
        identity=make_identity(full_name="Nicolas"),
        skills=(
            make_skill(
                label_fr="NLP",
                aliases=["Traitement du langage naturel (NLP)"],
                category="technical",
            ),
            make_skill(label_fr="SQL", category="technical"),
        ),
        languages=(make_language(code_value="fr", level="native"),),
        experiences=(
            ImportedExperience(
                make_experience(
                    kind="job", title_fr="Analyste", organisation="X", start="2020-01"
                ),
                skills=("traitement du langage naturel (nlp)", "SQL"),
            ),
        ),
        tracks=(
            make_track(name="Data analyst", titles="Data Analyst", locations="Paris"),
        ),
    )


def test_an_import_fills_an_empty_profile_and_links_skills_by_name() -> None:
    store = InMemoryProfileStore()

    result = editor(store).import_profile(imported_profile())

    assert isinstance(result, ProfileImported)
    assert result.counts["skills"] == 2
    profile = editor(store).profile()
    assert profile.identity.contact_email == "n@example.fr"
    nlp, sql = profile.skills
    assert profile.experiences[0].content.skill_ids == (nlp.id, sql.id)
    assert store.event_types() == [
        "profil.profile_imported",
        "profil.onboarding_completed",
    ]
    assert store.events[0].actor is Actor.SYSTEM
    assert not editor(store).needs_onboarding()


def test_a_second_import_changes_nothing() -> None:
    store = InMemoryProfileStore()
    editor(store).import_profile(imported_profile())
    before = editor(store).profile()

    result = editor(store).import_profile(imported_profile())

    assert isinstance(result, AlreadyFilled)
    assert editor(store).profile() == before


def test_an_import_naming_an_unknown_skill_is_refused() -> None:
    profile = imported_profile()
    broken = ImportedProfile(
        identity=profile.identity,
        skills=profile.skills,
        experiences=(
            ImportedExperience(profile.experiences[0].content, skills=("Rust",)),
        ),
    )

    with pytest.raises(ProfileInputError, match="« Rust » ne figure pas"):
        editor(InMemoryProfileStore()).import_profile(broken)
