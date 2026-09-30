"""The CV of an application, targeted at its offer (decision D3, Q2, Q3, Q10, Q11): pure functions.

Targeting only chooses and orders what the master CV shows in its three variable blocks — technical skills (in their
groups), soft skills, projects — and never rewrites a text. Each choice keeps its reason, shown behind « Pourquoi ? ».
Nothing leaves the CV in silence: what the rules take out, and what they could not put in, is listed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from rocky.offres.analysis.model import IMPORTANCE_LABELS, Importance, PostingAnalysis
from rocky.profil.cv.template import Slots
from rocky.profil.model import CvLayout, Profile, SkillCategory

# The weight of a skill of the posting in a project's rank, by how the posting asks for it.
WEIGHTS = {Importance.ELIMINATORY: 3, Importance.PREFERRED: 2, Importance.DETECTED: 1}
_ORDER = (Importance.ELIMINATORY, Importance.PREFERRED, Importance.DETECTED)
TRANSVERSAL = frozenset({SkillCategory.SOFT, SkillCategory.BUSINESS})


@dataclass(frozen=True)
class Targeted:
    """The targeted layout and the reasons of its choices.

    ``reasons`` explains the skills and projects of the targeted CV, ``left_out`` the projects of the master CV the
    rules replaced, ``proposed`` the skills the posting names that the rules could not put in (Q10 bis).
    """

    layout: CvLayout
    reasons: Mapping[tuple[str, int], str]  # ("skill" | "project", id) → reason
    left_out: Mapping[int, str]  # project id → reason
    proposed: Mapping[int, str]  # skill id → reason


class Coverage(StrEnum):
    IN_CV = "in_cv"
    IN_PROFILE = "in_profile"
    OUTSIDE = "outside"


COVERAGE_LABELS = {
    Coverage.IN_CV: "Dans le CV",
    Coverage.IN_PROFILE: "Dans ton profil, pas dans le CV",
    Coverage.OUTSIDE: "Absente de ton profil",
}


@dataclass(frozen=True)
class CoverageLine:
    """What the posting requires or welcomes, and where the CV stands (Q11)."""

    name: str
    importance: Importance | None  # None: a requirement outside the account's skills
    coverage: Coverage
    evidence: str
    skill_id: int | None = None


def cited_skills(profile: Profile, analysis: PostingAnalysis) -> dict[int, Importance]:
    """The skills of the profile the posting names, with the strongest importance it gives them.

    The analysis names a skill by its French label (``AccountSkill.label``), unique within a profile.
    """
    by_label = {skill.label.fr: skill.id for skill in profile.skills}
    cited: dict[int, Importance] = {}
    for match in analysis.skills:
        skill_id = by_label.get(match.skill)
        if skill_id is None:
            continue
        known = cited.get(skill_id)
        if known is None or _ORDER.index(match.importance) < _ORDER.index(known):
            cited[skill_id] = match.importance
    return cited


def target(
    master: CvLayout, profile: Profile, analysis: PostingAnalysis, slots: Slots
) -> Targeted:
    """The rules' proposal (Q10): the master CV, the skills the posting names first, the projects that prove most."""
    cited = cited_skills(profile, analysis)
    reasons: dict[tuple[str, int], str] = {}
    proposed: dict[int, str] = {}

    def rank(skill_id: int, index: int) -> tuple[int, int]:
        importance = cited.get(skill_id)
        return (len(_ORDER) if importance is None else _ORDER.index(importance), index)

    def cited_reason(skill_id: int) -> str:
        return f"Citée par l'annonce ({IMPORTANCE_LABELS[cited[skill_id]].lower()})"

    groups = []
    for group in master.groups:
        ordered = tuple(
            skill_id
            for _, skill_id in sorted(
                enumerate(group.skill_ids), key=lambda pair: rank(pair[1], pair[0])
            )
        )
        for skill_id in ordered:
            reasons[("skill", skill_id)] = (
                cited_reason(skill_id) if skill_id in cited else "Dans ton CV maître"
            )
        groups.append(replace(group, skill_ids=ordered))

    in_groups = {skill_id for group in master.groups for skill_id in group.skill_ids}
    categories = {skill.id: skill.content.category for skill in profile.skills}
    for skill_id in _by_importance(cited):
        if (
            categories.get(skill_id) is SkillCategory.TECHNICAL
            and skill_id not in in_groups
        ):
            proposed[skill_id] = (
                f"{cited_reason(skill_id)} : hors de ton CV maître, choisis son groupe"
            )

    transversal = list(master.transversal)
    added = [
        skill_id
        for skill_id in _by_importance(cited)
        if categories.get(skill_id) in TRANSVERSAL and skill_id not in transversal
    ]
    for skill_id in added:
        if len(transversal) < slots.transversal:
            transversal.append(skill_id)
            reasons[("skill", skill_id)] = f"{cited_reason(skill_id)} : ajoutée"
        else:
            proposed[skill_id] = (
                f"{cited_reason(skill_id)} : ton gabarit n'a plus de place"
            )
    ordered_transversal = tuple(
        skill_id
        for _, skill_id in sorted(
            enumerate(transversal), key=lambda pair: rank(pair[1], pair[0])
        )
    )
    for skill_id in ordered_transversal:
        reasons.setdefault(
            ("skill", skill_id),
            cited_reason(skill_id) if skill_id in cited else "Dans ton CV maître",
        )

    projects, left_out = _projects(master, profile, cited, slots, reasons)
    return Targeted(
        layout=replace(
            master,
            groups=tuple(groups),
            transversal=ordered_transversal,
            projects=projects,
        ),
        reasons=reasons,
        left_out=left_out,
        proposed=proposed,
    )


def _projects(
    master: CvLayout,
    profile: Profile,
    cited: Mapping[int, Importance],
    slots: Slots,
    reasons: dict[tuple[str, int], str],
) -> tuple[tuple[int, ...], dict[int, str]]:
    """As many projects as the master CV shows (within the template's slots), those proving the most of the posting's
    skills first; ties keep the master CV's order, then the profile's."""
    count = min(len(master.projects), slots.projects)
    labels = {skill.id: skill.label.fr for skill in profile.skills}
    master_index = {project_id: i for i, project_id in enumerate(master.projects)}
    proofs = {
        project.id: [s for s in project.content.skill_ids if s in cited]
        for project in profile.projects
    }

    def weight(project_id: int) -> int:
        return sum(WEIGHTS[cited[skill_id]] for skill_id in proofs[project_id])

    ranked = sorted(
        (project.id for project in profile.projects),
        key=lambda project_id: (
            -weight(project_id),
            master_index.get(project_id, len(master_index)),
        ),
    )
    chosen = tuple(ranked[:count])
    for project_id in chosen:
        proven = proofs[project_id]
        if proven:
            names = ", ".join(labels[skill_id] for skill_id in proven)
            reasons[("project", project_id)] = (
                f"Prouve {len(proven)} compétence{'s' if len(proven) > 1 else ''} de l'annonce : {names}"
            )
        else:
            reasons[("project", project_id)] = (
                "Dans ton CV maître, sans compétence de l'annonce"
            )
    left_out = {
        project_id: "Remplacé par un projet qui prouve plus de compétences de l'annonce"
        for project_id in master.projects
        if project_id not in chosen
    }
    return chosen, left_out


def _by_importance(cited: Mapping[int, Importance]) -> list[int]:
    return sorted(cited, key=lambda skill_id: _ORDER.index(cited[skill_id]))


def coverage(
    layout: CvLayout, profile: Profile, analysis: PostingAnalysis
) -> tuple[CoverageLine, ...]:
    """Each skill the posting requires or welcomes: in the CV, in the profile only; then what it requires outside the
    account's skills (Q11). Skills only mentioned are left out: they decide nothing."""
    by_label = {skill.label.fr: skill.id for skill in profile.skills}
    shown = {skill_id for group in layout.groups for skill_id in group.skill_ids}
    shown |= set(layout.transversal)
    lines: list[CoverageLine] = []
    seen: set[int] = set()
    for importance in (Importance.ELIMINATORY, Importance.PREFERRED):
        for match in analysis.skills_of(importance):
            skill_id = by_label.get(match.skill)
            if skill_id is None or skill_id in seen:
                continue
            seen.add(skill_id)
            lines.append(
                CoverageLine(
                    name=match.skill,
                    importance=importance,
                    coverage=Coverage.IN_CV
                    if skill_id in shown
                    else Coverage.IN_PROFILE,
                    evidence=match.evidence,
                    skill_id=skill_id,
                )
            )
    lines += [
        CoverageLine(
            name=requirement,
            importance=None,
            coverage=Coverage.OUTSIDE,
            evidence=requirement,
        )
        for requirement in analysis.requirements
    ]
    return tuple(lines)
