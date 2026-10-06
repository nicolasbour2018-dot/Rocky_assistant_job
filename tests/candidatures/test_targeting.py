"""Targeting rules of an application's CV (decision D3, Q10, Q10 bis, Q11)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from rocky.candidatures.targeting import (
    Coverage,
    cited_skills,
    coverage,
    selection_json,
    selection_of,
    target,
)
from rocky.offres.analysis.model import (
    RULES_VERSION,
    Importance,
    PostingAnalysis,
    SkillMatch,
)
from rocky.profil.cv.template import Slots
from rocky.profil.model import (
    CvLayout,
    Identity,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    Skill,
    SkillCategory,
    SkillDraft,
    SkillGroup,
    Text,
)

SLOTS = Slots(projects=2, groups=4, skills_per_group=30, transversal=3, hobbies=99)

PYTHON, SQL, DOCKER, SPARK, CURIOSITY, RIGOUR, FINANCE = 1, 2, 3, 4, 5, 6, 7
SKILLS = {
    PYTHON: ("Python", SkillCategory.TECHNICAL),
    SQL: ("SQL", SkillCategory.TECHNICAL),
    DOCKER: ("Docker", SkillCategory.TECHNICAL),
    SPARK: ("Spark", SkillCategory.TECHNICAL),
    CURIOSITY: ("Curiosité", SkillCategory.SOFT),
    RIGOUR: ("Rigueur", SkillCategory.SOFT),
    FINANCE: ("Finance", SkillCategory.BUSINESS),
}
SORTING, FORECAST, DASHBOARD = 10, 11, 12
MASTER = CvLayout(
    groups=(
        SkillGroup(Text("Langages"), (PYTHON, SQL)),
        SkillGroup(Text("Outils"), (DOCKER,)),
    ),
    transversal=(CURIOSITY, RIGOUR),
    projects=(SORTING, FORECAST),
)


def profile(cv: CvLayout = MASTER) -> Profile:
    return Profile(
        id=1,
        account_id=1,
        identity=Identity(full_name="Camille Martin"),
        preferences=Preferences(),
        onboarding=OnboardingState(completed_at=datetime(2026, 9, 1, tzinfo=UTC)),
        skills=tuple(
            Skill(skill_id, SkillDraft(Text(label), category))
            for skill_id, (label, category) in SKILLS.items()
        ),
        projects=(
            Project(SORTING, ProjectDraft(Text("Tri"), skill_ids=(PYTHON,))),
            Project(FORECAST, ProjectDraft(Text("Prévision"), skill_ids=(SQL,))),
            Project(DASHBOARD, ProjectDraft(Text("Tableau"), skill_ids=(SQL, SPARK))),
        ),
        cv=cv,
    )


def analysis(
    *matches: tuple[str, Importance], requirements: tuple[str, ...] = ()
) -> PostingAnalysis:
    return PostingAnalysis(
        rules_version=RULES_VERSION,
        description="",
        skills=tuple(
            SkillMatch(name, name.lower(), importance, f"On attend {name}.")
            for name, importance in matches
        ),
        requirements=requirements,
    )


def test_a_posting_that_names_nothing_keeps_the_master_cv() -> None:
    targeted = target(MASTER, profile(), analysis(), SLOTS)

    assert targeted.layout == MASTER
    assert targeted.reasons[("skill", PYTHON)] == "Dans ton CV maître"
    assert targeted.left_out == {}
    assert targeted.proposed == {}


def test_cited_skills_come_first_in_their_group_by_importance() -> None:
    targeted = target(
        MASTER,
        profile(),
        analysis(("SQL", Importance.PREFERRED), ("Python", Importance.DETECTED)),
        SLOTS,
    )

    assert targeted.layout.groups[0].skill_ids == (SQL, PYTHON)
    assert targeted.reasons[("skill", SQL)] == "Citée par l'annonce (un plus)"
    # The order of the groups is the design's: it never changes.
    assert [group.name.fr for group in targeted.layout.groups] == ["Langages", "Outils"]


def test_the_strongest_importance_counts_when_a_skill_is_named_twice() -> None:
    cited = cited_skills(
        profile(),
        analysis(("SQL", Importance.DETECTED), ("SQL", Importance.ELIMINATORY)),
    )

    assert cited == {SQL: Importance.ELIMINATORY}


def test_a_technical_skill_outside_the_master_cv_is_proposed_not_added() -> None:
    targeted = target(
        MASTER, profile(), analysis(("Spark", Importance.ELIMINATORY)), SLOTS
    )

    assert all(SPARK not in group.skill_ids for group in targeted.layout.groups)
    assert "choisis son groupe" in targeted.proposed[SPARK]


def test_a_cited_soft_skill_is_added_while_the_template_has_room() -> None:
    targeted = target(
        MASTER, profile(), analysis(("Finance", Importance.PREFERRED)), SLOTS
    )

    assert targeted.layout.transversal == (FINANCE, CURIOSITY, RIGOUR)
    assert targeted.reasons[("skill", FINANCE)].endswith(": ajoutée")


def test_a_cited_soft_skill_beyond_the_template_is_proposed() -> None:
    full = Slots(projects=2, groups=4, skills_per_group=30, transversal=2, hobbies=99)

    targeted = target(
        MASTER, profile(), analysis(("Finance", Importance.PREFERRED)), full
    )

    assert targeted.layout.transversal == (CURIOSITY, RIGOUR)
    assert "plus de place" in targeted.proposed[FINANCE]


def test_the_projects_proving_most_fill_the_master_cvs_count() -> None:
    targeted = target(
        MASTER,
        profile(),
        analysis(("Spark", Importance.PREFERRED), ("SQL", Importance.PREFERRED)),
        SLOTS,
    )

    # Tableau proves SQL and Spark (4), Prévision SQL (2), Tri nothing: Tri leaves, and it is said.
    assert targeted.layout.projects == (DASHBOARD, FORECAST)
    assert targeted.reasons[("project", DASHBOARD)] == (
        "Prouve 2 compétences de l'annonce : SQL, Spark"
    )
    assert SORTING in targeted.left_out


def test_projects_that_tie_keep_the_master_cvs_order() -> None:
    targeted = target(
        MASTER, profile(), analysis(("Docker", Importance.ELIMINATORY)), SLOTS
    )

    assert targeted.layout.projects == (SORTING, FORECAST)
    assert targeted.reasons[("project", SORTING)] == (
        "Dans ton CV maître, sans compétence de l'annonce"
    )


def test_targeting_is_deterministic() -> None:
    posting = analysis(
        ("SQL", Importance.PREFERRED), ("Curiosité", Importance.DETECTED)
    )

    assert target(MASTER, profile(), posting, SLOTS) == target(
        MASTER, profile(), posting, SLOTS
    )


def test_coverage_says_where_each_required_skill_stands() -> None:
    posting = analysis(
        ("Python", Importance.ELIMINATORY),
        ("Spark", Importance.PREFERRED),
        ("Docker", Importance.DETECTED),
        requirements=("Expérience impérative sur Informatica",),
    )

    lines = coverage(MASTER, profile(), posting)

    assert [(line.name, line.coverage) for line in lines] == [
        ("Python", Coverage.IN_CV),
        ("Spark", Coverage.IN_PROFILE),
        ("Expérience impérative sur Informatica", Coverage.OUTSIDE),
    ]


def test_a_kept_selection_is_placed_on_the_master_cv() -> None:
    adjusted = target(
        MASTER, profile(), analysis(("SQL", Importance.PREFERRED)), SLOTS
    ).layout

    assert selection_of(selection_json(adjusted), profile()) == adjusted


def test_a_kept_selection_is_dropped_when_the_master_groups_changed() -> None:
    kept = selection_json(MASTER)
    renamed = replace(
        MASTER,
        groups=(replace(MASTER.groups[0], name=Text("Code")), MASTER.groups[1]),
    )

    assert selection_of(kept, profile(renamed)) is None


def test_a_kept_selection_leaves_out_what_the_profile_lost() -> None:
    """Step H1: a removed skill or project is no longer placed (it was a KeyError when rendering)."""
    kept = selection_json(MASTER)
    full = profile()
    reduced = replace(
        full,
        skills=tuple(s for s in full.skills if s.id not in (SQL, RIGOUR)),
        projects=tuple(p for p in full.projects if p.id != FORECAST),
    )

    placed = selection_of(kept, reduced)

    assert placed is not None
    assert [group.skill_ids for group in placed.groups] == [(PYTHON,), (DOCKER,)]
    assert placed.transversal == (CURIOSITY,)
    assert placed.projects == (SORTING,)
