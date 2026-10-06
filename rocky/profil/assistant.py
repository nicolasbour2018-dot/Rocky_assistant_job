"""What the assistant 🐾 knows of the profile (decision G4, Q11): the tracks searched and the main skills, given with
every question as part of the account summary."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from sqlalchemy import Engine

from rocky.profil.api import stored_profile
from rocky.profil.model import TRACK_STATUS_LABELS, Profile, TrackStatus
from rocky.system.assistant.model import Fact
from rocky.system.assistant.registry import add_summary
from rocky.system.auth.model import Account

LINK = "/profil"
# The skills named: the key ones first, then the others, up to this many.
SKILLS = 30


def install(app: FastAPI) -> None:
    add_summary(app, "profil", _summary)


def _summary(request: Request, account: Account) -> Sequence[Fact]:
    engine: Engine = request.app.state.engine
    with engine.connect() as connection:
        profile = stored_profile(connection, account.id)
    return [] if profile is None else profile_facts(profile)


def profile_facts(profile: Profile) -> list[Fact]:
    facts = []
    tracks = [
        track for track in profile.tracks if track.status is not TrackStatus.ARCHIVED
    ]
    for index, track in enumerate(tracks, start=1):
        content = track.content
        text = f"« {content.name} » ({TRACK_STATUS_LABELS[track.status].lower()})"
        if content.titles:
            text += f" ; intitulés : {', '.join(content.titles)}"
        if content.locations:
            text += f" ; lieux : {', '.join(content.locations)}"
        facts.append(Fact(f"compte.piste_{index}", "Piste de recherche", text, LINK))
    skills = sorted(profile.skills, key=lambda skill: not skill.content.is_key)[:SKILLS]
    if skills:
        facts.append(
            Fact(
                "compte.competences",
                "Tes compétences principales",
                ", ".join(skill.label.fr for skill in skills),
                LINK,
            )
        )
    facts.append(
        Fact(
            "compte.objectif",
            "Ton objectif de la semaine",
            f"{profile.weekly_goal} candidature{'s' if profile.weekly_goal > 1 else ''} envoyée"
            f"{'s' if profile.weekly_goal > 1 else ''}",
            "/",
        )
    )
    return facts
