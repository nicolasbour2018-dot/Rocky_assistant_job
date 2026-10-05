"""Profile proposals of an imported CV: chosen section by section, nothing overwritten nor added twice (D2, Q14)."""

from __future__ import annotations

from rocky.profil.cv.proposals import apply, items, preview_profile
from rocky.profil.cv.template import NEUTRAL_SLOTS, Slots
from rocky.profil.rules import make_identity, make_skill
from rocky.profil.usecases import ProfileEditor
from tests.profil.cv.fixtures import PROFILE
from tests.profil.fakes import InMemoryProfileStore
from tests.system.auth.fakes import FakeClock


def editor() -> ProfileEditor:
    return ProfileEditor(
        InMemoryProfileStore(), clock=FakeClock(), account_id=7, email="c@example.org"
    )


def test_identity_fills_only_what_is_empty() -> None:
    profile_editor = editor()
    profile_editor.save_identity(
        make_identity(
            full_name="Camille M.", contact_email="c@example.org", city="Lyon"
        )
    )
    shown = items(PROFILE, "identite", profile_editor.profile())
    assert [(item.text.split(" :")[0], item.present) for item in shown] == [
        ("Nom", True),
        ("Titre", False),
        ("Accroche", False),
        ("E-mail", True),
        ("Téléphone", False),
    ]

    added = apply(
        profile_editor,
        PROFILE,
        "identite",
        [item.index for item in shown],
        NEUTRAL_SLOTS,
    )

    identity = profile_editor.profile().identity
    assert added == 3
    assert identity.full_name == "Camille M."  # kept
    assert identity.title.fr == "Data Scientist"
    assert identity.phone == "06 00 00 00 00"
    assert identity.city == "Lyon"


def test_skills_join_their_group_and_known_skills_are_reused() -> None:
    profile_editor = editor()
    python = profile_editor.add_skill(
        make_skill(label_fr="Python", category="technical")
    )

    apply(profile_editor, PROFILE, "competences", [0], NEUTRAL_SLOTS)
    apply(profile_editor, PROFILE, "transversales", [0], NEUTRAL_SLOTS)

    profile = profile_editor.profile()
    assert [skill.label.fr for skill in profile.skills] == [
        "Curiosité",
        "Python",
        "SQL",
    ]
    (group,) = profile.cv.groups
    assert group.name.fr == "Langages"
    assert group.skill_ids[0] == python
    assert len(profile.cv.transversal) == 1
    assert items(PROFILE, "transversales", profile)[0].present


def test_languages_experiences_projects_and_hobbies_are_added_once() -> None:
    profile_editor = editor()
    for section in ("langues", "parcours", "projets", "loisirs"):
        apply(profile_editor, PROFILE, section, [0], NEUTRAL_SLOTS)
    profile = profile_editor.profile()

    assert [item.content.code for item in profile.languages] == ["en"]
    assert profile.experiences[0].content.organisation == "Transports Exemple"
    assert profile.cv.projects == (profile.projects[0].id,)
    assert [hobby.label.fr for hobby in profile.cv.hobbies] == ["Randonnée"]
    for section in ("langues", "parcours", "projets", "loisirs"):
        assert all(item.present for item in items(PROFILE, section, profile))
        assert apply(profile_editor, PROFILE, section, [0], NEUTRAL_SLOTS) == 0


def test_projects_beyond_the_template_room_stay_out_of_the_cv() -> None:
    profile_editor = editor()
    no_room = Slots(projects=0, groups=1, skills_per_group=5, transversal=1, hobbies=1)

    apply(profile_editor, PROFILE, "projets", [0], no_room)

    profile = profile_editor.profile()
    assert len(profile.projects) == 1
    assert profile.cv.projects == ()


def test_the_preview_profile_holds_the_cv_content() -> None:
    profile = preview_profile(PROFILE)

    assert profile.identity.full_name == "Camille Martin"
    assert [group.name.fr for group in profile.cv.groups] == ["Langages"]
    assert len(profile.cv.projects) == 1
    assert profile.experiences[0].content.start.year == 2023
