"""Every table of Rocky, registered on ``rocky.system.db.metadata``.

Imported by the Alembic environment and by the schema test: a table missing here is missing from the comparison
between declared tables and migrations.
"""

from __future__ import annotations

from rocky.offres.sql import (
    job_offers,
    offer_scores,
    offer_tracks,
    watch_run_sources,
    watch_runs,
)
from rocky.profil.sql import (
    experience_skills,
    experiences,
    languages,
    profiles,
    project_skills,
    projects,
    search_tracks,
    skill_terms,
    skills,
)
from rocky.system.auth.sql import account_tokens, accounts, sessions
from rocky.system.events import events

__all__ = [
    "account_tokens",
    "accounts",
    "events",
    "experience_skills",
    "experiences",
    "job_offers",
    "languages",
    "offer_scores",
    "offer_tracks",
    "profiles",
    "project_skills",
    "projects",
    "search_tracks",
    "sessions",
    "skill_terms",
    "skills",
    "watch_run_sources",
    "watch_runs",
]
