"""The master CV layout: gestures and what a stored layout may hold (decision D2, Q9, Q10)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from rocky.profil.cv import layout
from rocky.profil.model import CvLayout, Hobby, Profile, SkillGroup, Text
from rocky.profil.rules import ProfileInputError, make_project, make_skill
from rocky.profil.usecases import ProfileEditor
from tests.profil.fakes import InMemoryProfileStore
from tests.system.auth.fakes import FakeClock


def editor(store: InMemoryProfileStore) -> ProfileEditor:
    return ProfileEditor(store, clock=FakeClock(), account_id=7, email="n@example.fr")


@pytest.fixture
def cv_editor() -> ProfileEditor:
    profile_editor = editor(InMemoryProfileStore())
    for name in ("Python", "SQL", "Docker"):
        profile_editor.add_skill(make_skill(label_fr=name, category="technical"))
    profile_editor.add_skill(make_skill(label_fr="Curiosité", category="soft"))
    profile_editor.add_skill(
        make_skill(label_fr="Gestion de projet", category="business")
    )
    for name in ("Rocky", "Détecteur"):
        profile_editor.add_project(make_project(name_fr=name))
    return profile_editor


def ids(profile: Profile, *labels: str) -> tuple[int, ...]:
    by_label = {skill.label.fr: skill.id for skill in profile.skills}
    return tuple(by_label[label] for label in labels)


def test_skills_are_placed_in_groups_then_moved_and_removed(
    cv_editor: ProfileEditor,
) -> None:
    profile = cv_editor.profile()
    python, sql, docker, curiosity = ids(
        profile, "Python", "SQL", "Docker", "Curiosité"
    )
    cv = layout.add_group(CvLayout(), Text("Langages et Data", "Languages and data"))
    cv = layout.add_group(cv, Text("Déploiement"))
    for skill_id, group in ((python, 0), (sql, 0), (docker, 1), (curiosity, 0)):
        cv = layout.place_skill(cv, profile, skill_id, group)

    cv = layout.move_skill(cv, sql, -1)
    cv = layout.move_group(cv, 1, -1)

    assert cv.groups == (
        SkillGroup(Text("Déploiement"), (docker,)),
        SkillGroup(Text("Langages et Data", "Languages and data"), (sql, python)),
    )
    assert cv.transversal == (curiosity,)  # a soft skill goes to the transversal list
    cv = layout.place_skill(cv, profile, python, 0)  # moved to another group
    assert cv.groups[0].skill_ids == (docker, python)
    assert cv.groups[1].skill_ids == (sql,)
    cv = layout.place_skill(cv, profile, python, None)
    assert python not in cv.groups[0].skill_ids

    cv_editor.save_cv_layout(cv)
    assert cv_editor.profile().cv == cv


def test_a_move_past_the_end_changes_nothing(cv_editor: ProfileEditor) -> None:
    profile = cv_editor.profile()
    python, sql = ids(profile, "Python", "SQL")
    cv = layout.add_group(CvLayout(), Text("Data"))
    cv = layout.place_skill(cv, profile, python, 0)
    cv = layout.place_skill(cv, profile, sql, 0)

    assert layout.move_skill(cv, python, -1) == cv
    assert layout.move_skill(cv, sql, 1) == cv
    assert layout.move_group(cv, 0, 1) == cv
    assert layout.rename_group(cv, 5, Text("X")) == cv


def test_projects_and_hobbies_keep_the_order_chosen(cv_editor: ProfileEditor) -> None:
    rocky, detector = (project.id for project in cv_editor.profile().projects)
    cv = layout.toggle_project(CvLayout(), rocky)
    cv = layout.toggle_project(cv, detector)
    cv = layout.move_project(cv, detector, -1)
    assert cv.projects == (detector, rocky)
    assert layout.toggle_project(cv, detector).projects == (rocky,)

    cv = layout.add_hobby(cv, Text("Course à pied", "Running"))
    cv = layout.add_hobby(cv, Text("Échecs"))
    cv = layout.move_hobby(cv, 1, -1)
    cv = layout.toggle_hobby(cv, 1)
    assert cv.hobbies == (
        Hobby(Text("Échecs")),
        Hobby(Text("Course à pied", "Running"), in_cv=False),
    )
    assert layout.remove_hobby(cv, 0).hobbies == (cv.hobbies[1],)


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ("technical_in_transversal", "transversales"),
        ("soft_in_group", "techniques"),
        ("twice", "deux fois"),
        ("unknown_project", "projet"),
        ("empty_group_name", "nom au groupe"),
        ("same_group_name", "existe déjà"),
        ("empty_hobby", "loisir"),
    ],
)
def test_a_wrong_layout_is_refused(
    cv_editor: ProfileEditor, bad: str, message: str
) -> None:
    profile = cv_editor.profile()
    python, curiosity = ids(profile, "Python", "Curiosité")
    group = SkillGroup(Text("Data"), (python,))
    layouts = {
        "technical_in_transversal": CvLayout(transversal=(python,)),
        "soft_in_group": CvLayout(groups=(SkillGroup(Text("Data"), (curiosity,)),)),
        "twice": CvLayout(groups=(group, SkillGroup(Text("Autre"), (python,)))),
        "unknown_project": CvLayout(projects=(999,)),
        "empty_group_name": CvLayout(groups=(SkillGroup(Text(" ")),)),
        "same_group_name": CvLayout(groups=(group, SkillGroup(Text("DATA")))),
        "empty_hobby": CvLayout(hobbies=(Hobby(Text("")),)),
    }

    with pytest.raises(ProfileInputError, match=message):
        cv_editor.save_cv_layout(layouts[bad])


def test_a_skill_changing_category_leaves_the_cv(cv_editor: ProfileEditor) -> None:
    profile = cv_editor.profile()
    (python,) = ids(profile, "Python")
    cv_editor.save_cv_layout(
        layout.place_skill(
            layout.add_group(CvLayout(), Text("Data")), profile, python, 0
        )
    )
    skill = profile.skill(python)
    assert skill is not None

    cv_editor.update_skill(
        python,
        replace(
            skill.content, category=make_skill(label_fr="x", category="soft").category
        ),
    )

    assert cv_editor.profile().cv.groups[0].skill_ids == ()


def test_a_deleted_skill_or_project_leaves_the_cv(cv_editor: ProfileEditor) -> None:
    profile = cv_editor.profile()
    (curiosity,) = ids(profile, "Curiosité")
    project = profile.projects[0].id
    cv_editor.save_cv_layout(CvLayout(transversal=(curiosity,), projects=(project,)))

    cv_editor.delete_skill(curiosity)
    cv_editor.delete_project(project)

    assert cv_editor.profile().cv == CvLayout()
