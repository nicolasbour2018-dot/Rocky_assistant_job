"""What the assistant 🐾 knows of the profile (decision G4, Q11): the tracks searched, the main skills, the goal."""

from __future__ import annotations

from rocky.profil.assistant import profile_facts
from rocky.profil.model import (
    Identity,
    OnboardingState,
    Preferences,
    Profile,
    Skill,
    Track,
    TrackStatus,
)
from rocky.profil.rules import make_skill, make_track


def test_the_tracks_not_archived_and_the_key_skills_first() -> None:
    profile = Profile(
        id=1,
        account_id=1,
        identity=Identity(),
        preferences=Preferences(),
        onboarding=OnboardingState(),
        tracks=(
            Track(
                1,
                TrackStatus.ACTIVE,
                make_track(name="Data", titles=["Data analyst"], locations=["Paris"]),
            ),
            Track(2, TrackStatus.ARCHIVED, make_track(name="Ancienne")),
        ),
        skills=(
            Skill(1, make_skill(label_fr="Excel", category="technical")),
            Skill(2, make_skill(label_fr="Python", category="technical", is_key=True)),
        ),
        weekly_goal=1,
    )

    assert [fact.line for fact in profile_facts(profile)] == [
        "[compte.piste_1] Piste de recherche : « Data » (active) ; intitulés : Data analyst ; lieux : Paris",
        "[compte.competences] Tes compétences principales : Python, Excel",
        "[compte.objectif] Ton objectif de la semaine : 1 candidature envoyée",
    ]
