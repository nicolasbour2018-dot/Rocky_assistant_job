"""In-memory adapter for the profile use cases (no SQL)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import count

from rocky.profil.model import (
    Experience,
    ExperienceDraft,
    Identity,
    Language,
    LanguageDraft,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    Skill,
    SkillDraft,
    Track,
    TrackDraft,
    TrackStatus,
)
from rocky.system.events import NewEvent


@dataclass
class _Profile:
    id: int
    account_id: int
    identity: Identity
    preferences: Preferences = field(default_factory=Preferences)
    onboarding: OnboardingState = field(default_factory=OnboardingState)
    tracks: dict[int, Track] = field(default_factory=dict)
    skills: dict[int, Skill] = field(default_factory=dict)
    languages: dict[int, Language] = field(default_factory=dict)
    experiences: dict[int, Experience] = field(default_factory=dict)
    projects: dict[int, Project] = field(default_factory=dict)


class InMemoryProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[int, _Profile] = {}
        # (profile id, term) -> skill id, like the primary key of skill_terms.
        self.terms: dict[tuple[int, str], int] = {}
        self.events: list[NewEvent] = []
        self._ids = count(1)

    def event_types(self) -> list[str]:
        return [event.type for event in self.events]

    def find_profile_id(self, account_id: int) -> int | None:
        return next(
            (p.id for p in self.profiles.values() if p.account_id == account_id), None
        )

    def create_profile(self, account_id: int, contact_email: str, now: datetime) -> int:
        profile_id = next(self._ids)
        self.profiles[profile_id] = _Profile(
            profile_id, account_id, Identity(contact_email=contact_email)
        )
        return profile_id

    def onboarding_state(self, account_id: int) -> OnboardingState | None:
        profile_id = self.find_profile_id(account_id)
        return None if profile_id is None else self.profiles[profile_id].onboarding

    def load(self, profile_id: int) -> Profile:
        p = self.profiles[profile_id]
        return Profile(
            id=p.id,
            account_id=p.account_id,
            identity=p.identity,
            preferences=p.preferences,
            onboarding=p.onboarding,
            tracks=tuple(p.tracks.values()),
            skills=tuple(sorted(p.skills.values(), key=lambda s: s.label.fr.lower())),
            languages=tuple(p.languages.values()),
            experiences=tuple(p.experiences.values()),
            projects=tuple(p.projects.values()),
        )

    def save_identity(self, profile_id: int, identity: Identity, now: datetime) -> None:
        self.profiles[profile_id].identity = identity

    def save_preferences(
        self, profile_id: int, preferences: Preferences, now: datetime
    ) -> None:
        self.profiles[profile_id].preferences = preferences

    def mark_onboarding_completed(self, profile_id: int, now: datetime) -> None:
        p = self.profiles[profile_id]
        p.onboarding = replace(p.onboarding, completed_at=now)

    def mark_onboarding_deferred(self, profile_id: int, now: datetime) -> None:
        p = self.profiles[profile_id]
        p.onboarding = replace(p.onboarding, deferred_at=now)

    def add_track(self, profile_id: int, track: TrackDraft, now: datetime) -> int:
        track_id = next(self._ids)
        self.profiles[profile_id].tracks[track_id] = Track(
            track_id, TrackStatus.ACTIVE, track
        )
        return track_id

    def update_track(
        self, profile_id: int, track_id: int, track: TrackDraft, now: datetime
    ) -> bool:
        tracks = self.profiles[profile_id].tracks
        if track_id not in tracks:
            return False
        tracks[track_id] = replace(tracks[track_id], content=track)
        return True

    def set_track_status(
        self, profile_id: int, track_id: int, status: TrackStatus, now: datetime
    ) -> bool:
        tracks = self.profiles[profile_id].tracks
        if track_id not in tracks:
            return False
        tracks[track_id] = replace(tracks[track_id], status=status)
        return True

    def delete_track(self, profile_id: int, track_id: int) -> bool:
        return self.profiles[profile_id].tracks.pop(track_id, None) is not None

    def term_owners(
        self, profile_id: int, terms: frozenset[str], except_skill: int | None
    ) -> list[str]:
        skills = self.profiles[profile_id].skills
        owners = {
            skills[skill_id].label.fr
            for (owner, term), skill_id in self.terms.items()
            if owner == profile_id and term in terms and skill_id != except_skill
        }
        return sorted(owners)

    def add_skill(
        self, profile_id: int, skill: SkillDraft, terms: frozenset[str]
    ) -> int:
        skill_id = next(self._ids)
        self.profiles[profile_id].skills[skill_id] = Skill(skill_id, skill)
        self._write_terms(profile_id, skill_id, terms)
        return skill_id

    def update_skill(
        self,
        profile_id: int,
        skill_id: int,
        skill: SkillDraft,
        terms: frozenset[str],
    ) -> bool:
        skills = self.profiles[profile_id].skills
        if skill_id not in skills:
            return False
        skills[skill_id] = Skill(skill_id, skill)
        self._forget_terms(skill_id)
        self._write_terms(profile_id, skill_id, terms)
        return True

    def delete_skill(self, profile_id: int, skill_id: int) -> bool:
        if self.profiles[profile_id].skills.pop(skill_id, None) is None:
            return False
        self._forget_terms(skill_id)
        p = self.profiles[profile_id]
        for experience_id, experience in p.experiences.items():
            kept = tuple(s for s in experience.content.skill_ids if s != skill_id)
            p.experiences[experience_id] = Experience(
                experience_id, replace(experience.content, skill_ids=kept)
            )
        for project_id, project in p.projects.items():
            kept = tuple(s for s in project.content.skill_ids if s != skill_id)
            p.projects[project_id] = Project(
                project_id, replace(project.content, skill_ids=kept)
            )
        return True

    def _write_terms(
        self, profile_id: int, skill_id: int, terms: frozenset[str]
    ) -> None:
        for term in terms:
            key = (profile_id, term)
            if key in self.terms:
                raise AssertionError(f"duplicate term {term!r}")
            self.terms[key] = skill_id

    def _forget_terms(self, skill_id: int) -> None:
        self.terms = {k: v for k, v in self.terms.items() if v != skill_id}

    def add_language(self, profile_id: int, language: LanguageDraft) -> int:
        language_id = next(self._ids)
        self.profiles[profile_id].languages[language_id] = Language(
            language_id, language
        )
        return language_id

    def update_language(
        self, profile_id: int, language_id: int, language: LanguageDraft
    ) -> bool:
        languages = self.profiles[profile_id].languages
        if language_id not in languages:
            return False
        languages[language_id] = Language(language_id, language)
        return True

    def delete_language(self, profile_id: int, language_id: int) -> bool:
        return self.profiles[profile_id].languages.pop(language_id, None) is not None

    def add_experience(self, profile_id: int, experience: ExperienceDraft) -> int:
        experience_id = next(self._ids)
        self.profiles[profile_id].experiences[experience_id] = Experience(
            experience_id, experience
        )
        return experience_id

    def update_experience(
        self, profile_id: int, experience_id: int, experience: ExperienceDraft
    ) -> bool:
        experiences = self.profiles[profile_id].experiences
        if experience_id not in experiences:
            return False
        experiences[experience_id] = Experience(experience_id, experience)
        return True

    def delete_experience(self, profile_id: int, experience_id: int) -> bool:
        return (
            self.profiles[profile_id].experiences.pop(experience_id, None) is not None
        )

    def add_project(self, profile_id: int, project: ProjectDraft) -> int:
        project_id = next(self._ids)
        self.profiles[profile_id].projects[project_id] = Project(project_id, project)
        return project_id

    def update_project(
        self, profile_id: int, project_id: int, project: ProjectDraft
    ) -> bool:
        projects = self.profiles[profile_id].projects
        if project_id not in projects:
            return False
        projects[project_id] = Project(project_id, project)
        return True

    def delete_project(self, profile_id: int, project_id: int) -> bool:
        return self.profiles[profile_id].projects.pop(project_id, None) is not None

    def append_event(self, event: NewEvent) -> None:
        self.events.append(event)
