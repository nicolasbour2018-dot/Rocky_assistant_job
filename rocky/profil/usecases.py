"""Profile use cases, on the ``ProfileStore`` port.

Each use case runs inside one transaction opened by the caller. Input that cannot be accepted raises
``ProfileInputError`` with a message for the user; an item of another profile is answered as missing (False).
The events journal only receives what explains a change of score or of watch (decision B5, Q5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from rocky.profil.model import (
    ExperienceDraft,
    Identity,
    ImportedProfile,
    LanguageDraft,
    Preferences,
    Profile,
    ProfileStore,
    ProjectDraft,
    SkillCategory,
    SkillDraft,
    TrackDraft,
    TrackStatus,
)
from rocky.profil.rules import (
    ProfileInputError,
    has_content,
    is_ready,
    make_skill,
    needs_onboarding,
    normalize_term,
    skill_terms,
)
from rocky.system.events import Actor, JsonValue, NewEvent

type Clock = Callable[[], datetime]


@dataclass(frozen=True)
class SkillsAdded:
    added: tuple[str, ...]
    already_there: tuple[str, ...]


@dataclass(frozen=True)
class ProfileImported:
    profile_id: int
    counts: Mapping[str, int]


@dataclass(frozen=True)
class AlreadyFilled:
    """The profile already has content: an import never merges into it."""

    profile_id: int


class ProfileEditor:
    """The profile of one account; created on first use (one account, one profile)."""

    def __init__(
        self, store: ProfileStore, *, clock: Clock, account_id: int, email: str
    ) -> None:
        self._store = store
        self._clock = clock
        self._account_id = account_id
        self._email = email
        self._profile_id: int | None = None

    # Reading

    def profile(self) -> Profile:
        return self._store.load(self._id())

    def needs_onboarding(self) -> bool:
        """Read only: a missing profile is not created to answer."""
        return needs_onboarding(self._store.onboarding_state(self._account_id))

    # Identity, preferences, onboarding

    def save_identity(self, identity: Identity) -> None:
        self._store.save_identity(self._id(), identity, self._clock())

    def save_preferences(self, preferences: Preferences) -> None:
        profile = self.profile()
        if preferences == profile.preferences:
            return
        self._store.save_preferences(profile.id, preferences, self._clock())
        self._event(
            "profil.preferences_updated",
            "profile",
            profile.id,
            {
                "contracts": [c.value for c in preferences.contracts],
                "remote_modes": [m.value for m in preferences.remote_modes],
                "min_salary_eur": preferences.min_salary_eur,
                "min_daily_rate_eur": preferences.min_daily_rate_eur,
            },
        )

    def defer_onboarding(self) -> None:
        profile = self.profile()
        if profile.onboarding.deferred_at is None:
            self._store.mark_onboarding_deferred(profile.id, self._clock())

    # Tracks

    def add_track(self, track: TrackDraft) -> int:
        profile = self.profile()
        self._check_track_name(profile, track.name, except_track=None)
        track_id = self._store.add_track(profile.id, track, self._clock())
        self._event("profil.track_created", "search_track", track_id, _track(track))
        self._complete_onboarding_if_ready()
        return track_id

    def update_track(self, track_id: int, track: TrackDraft) -> bool:
        profile = self.profile()
        current = profile.track(track_id)
        if current is None:
            return False
        self._check_track_name(profile, track.name, except_track=track_id)
        if track == current.content:
            return True
        self._store.update_track(profile.id, track_id, track, self._clock())
        self._event("profil.track_updated", "search_track", track_id, _track(track))
        self._complete_onboarding_if_ready()
        return True

    def pause_track(self, track_id: int) -> bool:
        return self._set_track_status(
            track_id, TrackStatus.PAUSED, "profil.track_paused"
        )

    def resume_track(self, track_id: int) -> bool:
        """Back to active, from paused or archived."""
        return self._set_track_status(
            track_id, TrackStatus.ACTIVE, "profil.track_resumed"
        )

    def archive_track(self, track_id: int) -> bool:
        return self._set_track_status(
            track_id, TrackStatus.ARCHIVED, "profil.track_archived"
        )

    def delete_track(self, track_id: int) -> bool:
        """Final removal. Allowed while no offer refers to tracks (until C6 links them)."""
        profile = self.profile()
        track = profile.track(track_id)
        if track is None or not self._store.delete_track(profile.id, track_id):
            return False
        self._event(
            "profil.track_deleted", "search_track", track_id, _track(track.content)
        )
        return True

    def _set_track_status(
        self, track_id: int, status: TrackStatus, event_type: str
    ) -> bool:
        profile = self.profile()
        track = profile.track(track_id)
        if track is None:
            return False
        if track.status is status:
            return True
        self._store.set_track_status(profile.id, track_id, status, self._clock())
        self._event(event_type, "search_track", track_id, {"name": track.name})
        self._complete_onboarding_if_ready()
        return True

    def _check_track_name(
        self, profile: Profile, name: str, *, except_track: int | None
    ) -> None:
        wanted = normalize_term(name)
        for track in profile.tracks:
            if track.id != except_track and normalize_term(track.name) == wanted:
                raise ProfileInputError(f"Une piste s'appelle déjà « {track.name} ».")

    def _complete_onboarding_if_ready(self) -> None:
        profile = self.profile()
        if profile.onboarding.completed_at is None and is_ready(profile.tracks):
            self._store.mark_onboarding_completed(profile.id, self._clock())
            self._event("profil.onboarding_completed", "profile", profile.id, {})

    # Skills

    def add_skill(self, skill: SkillDraft) -> int:
        profile_id = self._id()
        terms = self._free_terms(profile_id, skill, except_skill=None)
        skill_id = self._store.add_skill(profile_id, skill, terms)
        self._event("profil.skill_added", "skill", skill_id, _skill(skill))
        return skill_id

    def update_skill(self, skill_id: int, skill: SkillDraft) -> bool:
        profile = self.profile()
        current = profile.skill(skill_id)
        if current is None:
            return False
        terms = self._free_terms(profile.id, skill, except_skill=skill_id)
        if skill == current.content:
            return True
        self._store.update_skill(profile.id, skill_id, skill, terms)
        self._event("profil.skill_updated", "skill", skill_id, _skill(skill))
        return True

    def delete_skill(self, skill_id: int) -> bool:
        profile = self.profile()
        skill = profile.skill(skill_id)
        if skill is None or not self._store.delete_skill(profile.id, skill_id):
            return False
        self._event("profil.skill_removed", "skill", skill_id, _skill(skill.content))
        return True

    def add_skills(
        self, names_by_category: Mapping[SkillCategory, Iterable[str]]
    ) -> SkillsAdded:
        """Quick entry of the onboarding: one name per line; a name already known is reported, not added."""
        added: list[str] = []
        already_there: list[str] = []
        for category, names in names_by_category.items():
            for name in names:
                skill = make_skill(label_fr=name, category=category.value)
                try:
                    self.add_skill(skill)
                except ProfileInputError:
                    already_there.append(skill.label.fr)
                else:
                    added.append(skill.label.fr)
        return SkillsAdded(tuple(added), tuple(already_there))

    def _free_terms(
        self, profile_id: int, skill: SkillDraft, *, except_skill: int | None
    ) -> frozenset[str]:
        terms = skill_terms(skill)
        owners = self._store.term_owners(profile_id, terms, except_skill)
        if owners:
            raise ProfileInputError(
                f"« {skill.label.fr} » est déjà présent sous « {owners[0]} »."
            )
        return terms

    # Languages, experiences, projects (no event: they do not move a score yet)

    def add_language(self, language: LanguageDraft) -> int:
        profile = self.profile()
        self._check_language(profile, language, except_language=None)
        return self._store.add_language(profile.id, language)

    def update_language(self, language_id: int, language: LanguageDraft) -> bool:
        profile = self.profile()
        if not any(item.id == language_id for item in profile.languages):
            return False
        self._check_language(profile, language, except_language=language_id)
        return self._store.update_language(profile.id, language_id, language)

    def delete_language(self, language_id: int) -> bool:
        return self._store.delete_language(self._id(), language_id)

    def _check_language(
        self, profile: Profile, language: LanguageDraft, *, except_language: int | None
    ) -> None:
        for item in profile.languages:
            if item.id != except_language and item.content.code == language.code:
                raise ProfileInputError("Cette langue figure déjà dans ton profil.")

    def add_experience(self, experience: ExperienceDraft) -> int:
        profile = self.profile()
        _check_skills(profile, experience.skill_ids)
        return self._store.add_experience(profile.id, experience)

    def update_experience(
        self, experience_id: int, experience: ExperienceDraft
    ) -> bool:
        profile = self.profile()
        _check_skills(profile, experience.skill_ids)
        return self._store.update_experience(profile.id, experience_id, experience)

    def delete_experience(self, experience_id: int) -> bool:
        return self._store.delete_experience(self._id(), experience_id)

    def add_project(self, project: ProjectDraft) -> int:
        profile = self.profile()
        _check_skills(profile, project.skill_ids)
        return self._store.add_project(profile.id, project)

    def update_project(self, project_id: int, project: ProjectDraft) -> bool:
        profile = self.profile()
        _check_skills(profile, project.skill_ids)
        return self._store.update_project(profile.id, project_id, project)

    def delete_project(self, project_id: int) -> bool:
        return self._store.delete_project(self._id(), project_id)

    # Import

    def import_profile(
        self, imported: ImportedProfile
    ) -> ProfileImported | AlreadyFilled:
        """Write a whole reviewed profile at once, into an empty profile only (a second run changes nothing).

        Any refusal (a duplicate skill, an unknown linked skill) raises before the caller commits: nothing is
        written then.
        """
        profile = self.profile()
        if has_content(profile):
            return AlreadyFilled(profile.id)
        now = self._clock()
        identity = imported.identity
        if identity.contact_email is None:
            identity = replace(identity, contact_email=self._email)
        self._store.save_identity(profile.id, identity, now)
        self._store.save_preferences(profile.id, imported.preferences, now)
        skill_ids: dict[str, int] = {}
        for skill in imported.skills:
            terms = self._free_terms(profile.id, skill, except_skill=None)
            skill_id = self._store.add_skill(profile.id, skill, terms)
            skill_ids.update(dict.fromkeys(terms, skill_id))
        for language in imported.languages:
            self.add_language(language)
        for experience in imported.experiences:
            linked = _resolve(skill_ids, experience.skills)
            self._store.add_experience(
                profile.id, replace(experience.content, skill_ids=linked)
            )
        for project in imported.projects:
            linked = _resolve(skill_ids, project.skills)
            self._store.add_project(
                profile.id, replace(project.content, skill_ids=linked)
            )
        for track in imported.tracks:
            self._check_track_name(self.profile(), track.name, except_track=None)
            self._store.add_track(profile.id, track, now)
        counts = {
            "skills": len(imported.skills),
            "languages": len(imported.languages),
            "experiences": len(imported.experiences),
            "projects": len(imported.projects),
            "tracks": len(imported.tracks),
        }
        self._event(
            "profil.profile_imported", "profile", profile.id, dict(counts), Actor.SYSTEM
        )
        self._complete_onboarding_if_ready()
        return ProfileImported(profile.id, counts)

    # Helpers

    def _id(self) -> int:
        if self._profile_id is None:
            found = self._store.find_profile_id(self._account_id)
            self._profile_id = (
                found
                if found is not None
                else self._store.create_profile(
                    self._account_id, self._email, self._clock()
                )
            )
        return self._profile_id

    def _event(
        self,
        event_type: str,
        subject_type: str,
        subject_id: int,
        payload: Mapping[str, JsonValue],
        actor: Actor = Actor.USER,
    ) -> None:
        self._store.append_event(
            NewEvent(
                type=event_type,
                actor=actor,
                subject_type=subject_type,
                subject_id=str(subject_id),
                payload=payload,
                account_id=self._account_id,
            )
        )


def _check_skills(profile: Profile, skill_ids: Iterable[int]) -> None:
    known = {skill.id for skill in profile.skills}
    if any(skill_id not in known for skill_id in skill_ids):
        raise ProfileInputError(
            "Une des compétences liées n'existe pas dans ton profil."
        )


def _resolve(skill_ids: Mapping[str, int], names: Iterable[str]) -> tuple[int, ...]:
    """Ids of skills named by a label or an alias in an import file."""
    resolved = []
    for name in names:
        skill_id = skill_ids.get(normalize_term(name))
        if skill_id is None:
            raise ProfileInputError(
                f"La compétence liée « {name} » ne figure pas parmi les compétences du fichier."
            )
        resolved.append(skill_id)
    return tuple(dict.fromkeys(resolved))


def _track(track: TrackDraft) -> dict[str, JsonValue]:
    return {
        "name": track.name,
        "titles": list(track.titles),
        "keywords": list(track.keywords),
        "excluded_keywords": list(track.excluded_keywords),
        "locations": list(track.locations),
    }


def _skill(skill: SkillDraft) -> dict[str, JsonValue]:
    return {
        "label_fr": skill.label.fr,
        "label_en": skill.label.en,
        "aliases": list(skill.aliases),
        "category": skill.category.value,
        "level": skill.level.value if skill.level else None,
        "is_key": skill.is_key,
    }
