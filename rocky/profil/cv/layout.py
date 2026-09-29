"""Gestures on the master CV layout (decision D2, Q9, Q10): pure functions, one new layout per gesture.

Groups are designated by their index in the layout, skills and projects by their id. A gesture that does not
apply (an unknown index, a move past the end) returns the layout unchanged; ``check_layout`` guards what is
finally stored.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from rocky.profil.model import (
    CvLayout,
    Hobby,
    Profile,
    SkillCategory,
    SkillGroup,
    Text,
)
from rocky.profil.rules import ProfileInputError, normalize_term, optional


def check_layout(profile: Profile, layout: CvLayout) -> None:
    """Refuse a layout that names an item of another profile, misplaces a skill or repeats an item."""
    categories = {skill.id: skill.content.category for skill in profile.skills}
    seen: set[int] = set()
    names: set[str] = set()
    for group in layout.groups:
        name = normalize_term(group.name.fr)
        if not name:
            raise ProfileInputError("Donne un nom au groupe de compétences.")
        if name in names:
            raise ProfileInputError(f"Le groupe « {group.name.fr} » existe déjà.")
        names.add(name)
        for skill_id in group.skill_ids:
            if categories.get(skill_id) is not SkillCategory.TECHNICAL:
                raise ProfileInputError(
                    "Un groupe ne contient que des compétences techniques de ton profil."
                )
            _once(seen, skill_id)
    for skill_id in layout.transversal:
        if categories.get(skill_id) not in (SkillCategory.SOFT, SkillCategory.BUSINESS):
            raise ProfileInputError(
                "Les compétences transversales sont les compétences métier et savoir-être de ton profil."
            )
        _once(seen, skill_id)
    known_projects = {project.id for project in profile.projects}
    if len(set(layout.projects)) != len(layout.projects) or not set(
        layout.projects
    ) <= (known_projects):
        raise ProfileInputError("Un projet du CV n'existe pas dans ton profil.")
    for hobby in layout.hobbies:
        if not optional(hobby.label.fr):
            raise ProfileInputError("Un loisir a besoin d'un nom en français.")


def _once(seen: set[int], skill_id: int) -> None:
    if skill_id in seen:
        raise ProfileInputError("Une compétence figure deux fois dans le CV.")
    seen.add(skill_id)


# Groups


def add_group(layout: CvLayout, name: Text) -> CvLayout:
    return replace(layout, groups=(*layout.groups, SkillGroup(name)))


def rename_group(layout: CvLayout, index: int, name: Text) -> CvLayout:
    if not 0 <= index < len(layout.groups):
        return layout
    return _with_group(layout, index, replace(layout.groups[index], name=name))


def remove_group(layout: CvLayout, index: int) -> CvLayout:
    """The skills of the group leave the CV with it."""
    if not 0 <= index < len(layout.groups):
        return layout
    groups = layout.groups[:index] + layout.groups[index + 1 :]
    return replace(layout, groups=groups)


def move_group(layout: CvLayout, index: int, delta: int) -> CvLayout:
    return replace(layout, groups=_moved(layout.groups, index, delta))


# Skills


def place_skill(
    layout: CvLayout, profile: Profile, skill_id: int, group_index: int | None
) -> CvLayout:
    """Put a skill at the end of a group (technical) or of the transversal list; None takes it out of the CV."""
    skill = profile.skill(skill_id)
    if skill is None:
        return layout
    layout = remove_skill(layout, skill_id)
    if group_index is None:
        return layout
    if skill.content.category is not SkillCategory.TECHNICAL:
        return replace(layout, transversal=(*layout.transversal, skill_id))
    if not 0 <= group_index < len(layout.groups):
        return layout
    group = layout.groups[group_index]
    return _with_group(
        layout, group_index, replace(group, skill_ids=(*group.skill_ids, skill_id))
    )


def remove_skill(layout: CvLayout, skill_id: int) -> CvLayout:
    return replace(
        layout,
        groups=tuple(
            replace(g, skill_ids=tuple(s for s in g.skill_ids if s != skill_id))
            for g in layout.groups
        ),
        transversal=tuple(s for s in layout.transversal if s != skill_id),
    )


def move_skill(layout: CvLayout, skill_id: int, delta: int) -> CvLayout:
    """Up (-1) or down (+1) within its group or the transversal list."""
    for index, group in enumerate(layout.groups):
        if skill_id in group.skill_ids:
            moved = _moved(group.skill_ids, group.skill_ids.index(skill_id), delta)
            return _with_group(layout, index, replace(group, skill_ids=moved))
    if skill_id in layout.transversal:
        index = layout.transversal.index(skill_id)
        return replace(layout, transversal=_moved(layout.transversal, index, delta))
    return layout


# Projects


def toggle_project(layout: CvLayout, project_id: int) -> CvLayout:
    if project_id in layout.projects:
        return replace(
            layout, projects=tuple(p for p in layout.projects if p != project_id)
        )
    return replace(layout, projects=(*layout.projects, project_id))


def move_project(layout: CvLayout, project_id: int, delta: int) -> CvLayout:
    if project_id not in layout.projects:
        return layout
    index = layout.projects.index(project_id)
    return replace(layout, projects=_moved(layout.projects, index, delta))


# Hobbies


def add_hobby(layout: CvLayout, label: Text) -> CvLayout:
    return replace(layout, hobbies=(*layout.hobbies, Hobby(label)))


def update_hobby(layout: CvLayout, index: int, label: Text) -> CvLayout:
    if not 0 <= index < len(layout.hobbies):
        return layout
    return _with_hobby(layout, index, replace(layout.hobbies[index], label=label))


def toggle_hobby(layout: CvLayout, index: int) -> CvLayout:
    if not 0 <= index < len(layout.hobbies):
        return layout
    hobby = layout.hobbies[index]
    return _with_hobby(layout, index, replace(hobby, in_cv=not hobby.in_cv))


def remove_hobby(layout: CvLayout, index: int) -> CvLayout:
    if not 0 <= index < len(layout.hobbies):
        return layout
    return replace(layout, hobbies=layout.hobbies[:index] + layout.hobbies[index + 1 :])


def move_hobby(layout: CvLayout, index: int, delta: int) -> CvLayout:
    return replace(layout, hobbies=_moved(layout.hobbies, index, delta))


# Helpers


def _moved[T](items: Sequence[T], index: int, delta: int) -> tuple[T, ...]:
    target = index + delta
    if not (0 <= index < len(items) and 0 <= target < len(items)):
        return tuple(items)
    moved = list(items)
    moved[index], moved[target] = moved[target], moved[index]
    return tuple(moved)


def _with_group(layout: CvLayout, index: int, group: SkillGroup) -> CvLayout:
    groups = list(layout.groups)
    groups[index] = group
    return replace(layout, groups=tuple(groups))


def _with_hobby(layout: CvLayout, index: int, hobby: Hobby) -> CvLayout:
    hobbies = list(layout.hobbies)
    hobbies[index] = hobby
    return replace(layout, hobbies=tuple(hobbies))
