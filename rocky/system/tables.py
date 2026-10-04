"""Every table of Rocky, registered on ``rocky.system.db.metadata``.

Imported by the Alembic environment and by the schema test: a table missing here is missing from the comparison
between declared tables and migrations.
"""

from __future__ import annotations

from rocky.candidatures.sql import (
    application_changes,
    application_cv_selections,
    application_letters,
    application_messages,
    applications,
)
from rocky.offres.sql import (
    job_decisions,
    job_offers,
    offer_scores,
    offer_summaries,
    offer_tracks,
    watch_run_sources,
    watch_runs,
)
from rocky.profil.sql import (
    cv_templates,
    experience_skills,
    experiences,
    generic_letters,
    glossary_terms,
    hobbies,
    languages,
    profile_links,
    profiles,
    project_skills,
    projects,
    search_tracks,
    skill_groups,
    skill_terms,
    skills,
    translation_memory,
)
from rocky.system.auth.sql import account_tokens, accounts, sessions
from rocky.system.events import events

__all__ = [
    "account_tokens",
    "accounts",
    "application_changes",
    "application_cv_selections",
    "application_letters",
    "application_messages",
    "applications",
    "cv_templates",
    "events",
    "experience_skills",
    "experiences",
    "generic_letters",
    "glossary_terms",
    "hobbies",
    "job_decisions",
    "job_offers",
    "languages",
    "offer_scores",
    "offer_summaries",
    "offer_tracks",
    "profile_links",
    "profiles",
    "project_skills",
    "projects",
    "search_tracks",
    "sessions",
    "skill_groups",
    "skill_terms",
    "skills",
    "translation_memory",
    "watch_run_sources",
    "watch_runs",
]
