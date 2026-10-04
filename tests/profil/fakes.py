"""In-memory adapter for the profile use cases (no SQL)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import count

from rocky.profil.cv.layout import remove_skill
from rocky.profil.model import (
    CvLayout,
    CvTemplateRecord,
    Experience,
    ExperienceDraft,
    GenericLetter,
    GlossaryTerm,
    Identity,
    Language,
    LanguageDraft,
    LetterOrigin,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    Remembered,
    Skill,
    SkillDraft,
    StoredLetter,
    StoredPhoto,
    Track,
    TrackDraft,
    TrackStatus,
)
from rocky.profil.rules import text_sha256
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
    photo: StoredPhoto | None = None
    cv: CvLayout = field(default_factory=CvLayout)


class InMemoryProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[int, _Profile] = {}
        # (profile id, term) -> skill id, like the primary key of skill_terms.
        self.terms: dict[tuple[int, str], int] = {}
        self.events: list[NewEvent] = []
        self.templates: dict[int, list[CvTemplateRecord]] = {}
        self.glossaries: dict[int, dict[str, GlossaryTerm]] = {}
        self.memory: dict[int, dict[str, Remembered]] = {}
        self.letters: dict[int, list[StoredLetter]] = {}
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
            photo=p.photo,
            cv=p.cv,
        )

    def save_identity(self, profile_id: int, identity: Identity, now: datetime) -> None:
        self.profiles[profile_id].identity = identity

    def save_photo(
        self, profile_id: int, photo: StoredPhoto | None, now: datetime
    ) -> None:
        self.profiles[profile_id].photo = photo

    def save_cv_layout(self, profile_id: int, layout: CvLayout) -> None:
        self.profiles[profile_id].cv = layout

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
        p.cv = remove_skill(p.cv, skill_id)
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
        p = self.profiles[profile_id]
        if p.projects.pop(project_id, None) is None:
            return False
        p.cv = replace(
            p.cv, projects=tuple(i for i in p.cv.projects if i != project_id)
        )
        return True

    def add_cv_template(
        self,
        profile_id: int,
        path: str,
        sha256: str,
        name: str,
        language: str,
        now: datetime,
        source_sha256: str | None = None,
    ) -> tuple[int, bool]:
        for record in self.templates.get(profile_id, []):
            if record.sha256 == sha256:
                return record.id, False
        template_id = next(self._ids)
        self.templates.setdefault(profile_id, []).append(
            CvTemplateRecord(
                template_id, path, sha256, name, language, False, now, source_sha256
            )
        )
        return template_id, True

    def cv_templates(self, profile_id: int) -> tuple[CvTemplateRecord, ...]:
        return tuple(reversed(self.templates.get(profile_id, [])))

    def activate_cv_template(
        self, profile_id: int, language: str, template_id: int | None
    ) -> bool:
        records = self.templates.get(profile_id, [])
        mine = [r for r in records if r.language == language]
        if template_id is not None and all(r.id != template_id for r in mine):
            return False
        self.templates[profile_id] = [
            replace(r, active=r.id == template_id) if r.language == language else r
            for r in records
        ]
        return True

    def delete_cv_template(self, profile_id: int, template_id: int) -> bool:
        records = self.templates.get(profile_id, [])
        kept = [r for r in records if r.id != template_id or r.active]
        self.templates[profile_id] = kept
        return len(kept) < len(records)

    def glossary(self, profile_id: int) -> tuple[GlossaryTerm, ...]:
        terms = self.glossaries.get(profile_id, {})
        return tuple(terms[key] for key in sorted(terms))

    def save_glossary_term(
        self, profile_id: int, term: str, fr: str, en: str, now: datetime
    ) -> int:
        terms = self.glossaries.setdefault(profile_id, {})
        known = terms.get(term)
        term_id = known.id if known else next(self._ids)
        terms[term] = GlossaryTerm(term_id, fr, en)
        return term_id

    def delete_glossary_term(self, profile_id: int, term_id: int) -> bool:
        terms = self.glossaries.get(profile_id, {})
        for key, found in list(terms.items()):
            if found.id == term_id:
                del terms[key]
                return True
        return False

    def translation_memory(self, profile_id: int) -> dict[str, Remembered]:
        return dict(self.memory.get(profile_id, {}))

    def remember_translation(
        self, profile_id: int, source: str, translation: str, now: datetime
    ) -> None:
        self.memory.setdefault(profile_id, {})[text_sha256(source)] = Remembered(
            source, translation
        )

    def generic_letter(self, profile_id: int, language: str) -> StoredLetter | None:
        mine = [
            stored
            for stored in self.letters.get(profile_id, [])
            if stored.letter.language == language
        ]
        return mine[-1] if mine else None

    def add_generic_letter(
        self,
        profile_id: int,
        letter: GenericLetter,
        origin: LetterOrigin,
        sha256: str,
        source_sha256: str | None,
        now: datetime,
    ) -> StoredLetter:
        stored = StoredLetter(
            next(self._ids), letter, origin, sha256, source_sha256, now
        )
        self.letters.setdefault(profile_id, []).append(stored)
        return stored

    def append_event(self, event: NewEvent) -> None:
        self.events.append(event)
