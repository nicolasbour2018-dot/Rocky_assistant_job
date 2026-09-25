from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from rocky.profil.model import (
    Contract,
    OnboardingState,
    RemoteMode,
    SkillCategory,
    SkillLevel,
    Track,
    TrackDraft,
    TrackStatus,
)
from rocky.profil.rules import (
    ProfileInputError,
    clean_lines,
    is_ready,
    make_experience,
    make_identity,
    make_language,
    make_preferences,
    make_project,
    make_skill,
    make_track,
    needs_onboarding,
    normalize_term,
    skill_terms,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def test_terms_ignore_case_accents_and_punctuation() -> None:
    assert normalize_term("Traitement du langage naturel (NLP)") == (
        "traitement du langage naturel nlp"
    )
    assert normalize_term("Visualisation de DONNÉES") == "visualisation de donnees"
    assert normalize_term("  C++ / Rust ") == "c rust"


def test_lines_are_trimmed_and_never_repeated() -> None:
    assert clean_lines("Data Scientist\n\n  data  scientist \nML Engineer\n") == (
        "Data Scientist",
        "ML Engineer",
    )


def test_a_skill_answers_to_its_labels_and_aliases() -> None:
    skill = make_skill(
        label_fr="NLP",
        label_en="Natural Language Processing (NLP)",
        aliases="Traitement du langage naturel (NLP)\nnlp",
        category="technical",
        level="advanced",
        is_key=True,
    )

    assert skill.level is SkillLevel.ADVANCED
    assert skill.category is SkillCategory.TECHNICAL
    assert skill_terms(skill) == {
        "nlp",
        "natural language processing nlp",
        "traitement du langage naturel nlp",
    }


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"label_fr": " ", "category": "technical"}, "Donne un nom"),
        ({"label_fr": "SQL", "category": "hard"}, "Catégorie"),
        ({"label_fr": "SQL", "category": "technical", "level": "guru"}, "Niveau"),
    ],
)
def test_invalid_skills_are_refused(arguments: dict[str, str], message: str) -> None:
    with pytest.raises(ProfileInputError, match=message):
        make_skill(
            label_fr=arguments["label_fr"],
            category=arguments["category"],
            level=arguments.get("level"),
        )


def test_a_track_keeps_clean_lists() -> None:
    track = make_track(
        name=" Data analyst ",
        titles="Data Analyst\nBI Analyst\n",
        keywords="SQL\nPower BI",
        excluded_keywords="stage\nalternance",
        locations="Paris\nTélétravail complet",
    )

    assert track == TrackDraft(
        name="Data analyst",
        titles=("Data Analyst", "BI Analyst"),
        keywords=("SQL", "Power BI"),
        excluded_keywords=("stage", "alternance"),
        locations=("Paris", "Télétravail complet"),
    )


def test_a_keyword_cannot_be_wanted_and_excluded() -> None:
    with pytest.raises(ProfileInputError, match="à la fois un mot-clé et un mot exclu"):
        make_track(name="IA", keywords="Stage", excluded_keywords="stage")


def test_a_track_needs_a_name() -> None:
    with pytest.raises(ProfileInputError, match="nom à la piste"):
        make_track(name="  ", titles="Data Analyst")


def _track(
    status: TrackStatus, titles: tuple[str, ...], places: tuple[str, ...]
) -> Track:
    return Track(1, status, TrackDraft("IA", titles=titles, locations=places))


def test_the_profile_is_ready_with_one_active_track_with_a_title_and_a_place() -> None:
    assert is_ready([_track(TrackStatus.ACTIVE, ("Data Scientist",), ("Paris",))])
    assert not is_ready([_track(TrackStatus.ACTIVE, ("Data Scientist",), ())])
    assert not is_ready([_track(TrackStatus.ACTIVE, (), ("Paris",))])
    assert not is_ready([_track(TrackStatus.PAUSED, ("Data Scientist",), ("Paris",))])
    assert not is_ready([])


def test_onboarding_is_needed_until_completed_or_put_off() -> None:
    assert needs_onboarding(None)
    assert needs_onboarding(OnboardingState())
    assert not needs_onboarding(OnboardingState(completed_at=NOW))
    assert not needs_onboarding(OnboardingState(deferred_at=NOW))


def test_preferences_are_codes_in_a_stable_order() -> None:
    preferences = make_preferences(
        contracts=["freelance", "permanent", "permanent"],
        remote_modes=["hybrid"],
        min_salary_eur="45 000 €",
        min_daily_rate_eur="",
    )

    assert preferences.contracts == (Contract.PERMANENT, Contract.FREELANCE)
    assert preferences.remote_modes == (RemoteMode.HYBRID,)
    assert preferences.min_salary_eur == 45_000
    assert preferences.min_daily_rate_eur is None


@pytest.mark.parametrize("amount", ["quarante mille", "-5", "0"])
def test_amounts_are_positive_whole_euros(amount: str) -> None:
    with pytest.raises(ProfileInputError, match="salaire minimal"):
        make_preferences(min_salary_eur=amount)


def test_identity_needs_a_name_and_valid_links() -> None:
    identity = make_identity(
        full_name=" Nicolas  Exemple ",
        contact_email="nicolas@example.fr",
        headline_fr="Data scientist\n\nen reconversion",
    )
    assert identity.full_name == "Nicolas Exemple"
    assert identity.headline.fr == "Data scientist\n\nen reconversion"
    assert identity.headline.en is None

    with pytest.raises(ProfileInputError, match="nom"):
        make_identity(full_name="")
    with pytest.raises(ProfileInputError, match="LinkedIn"):
        make_identity(full_name="N", linkedin_url="linkedin.com/in/n")
    with pytest.raises(ProfileInputError, match="e-mail de contact"):
        make_identity(full_name="N", contact_email="nicolas")


def test_an_experience_runs_from_month_to_month() -> None:
    experience = make_experience(
        kind="job",
        title_fr="Data scientist",
        organisation="Exemple SA",
        start="2024-09",
        end="",
        bullets_fr="Modèle de scoring\n\nTableau de bord",
        skill_ids=[3, 3, 5],
    )

    assert experience.start == date(2024, 9, 1)
    assert experience.end is None
    assert experience.bullets_fr == ("Modèle de scoring", "Tableau de bord")
    assert experience.skill_ids == (3, 5)


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2024-13", None, "Le début"),
        ("2024-09", "2023-01", "précède"),
        ("sept", None, "AAAA-MM"),
    ],
)
def test_experience_dates_are_checked(
    start: str, end: str | None, message: str
) -> None:
    with pytest.raises(ProfileInputError, match=message):
        make_experience(
            kind="job", title_fr="X", organisation="Y", start=start, end=end
        )


def test_a_project_only_needs_a_name() -> None:
    project = make_project(name_fr="Finance connectée", stack="Python\nFastAPI")

    assert project.name.fr == "Finance connectée"
    assert project.problem.fr == ""
    assert project.stack == ("Python", "FastAPI")


def test_languages_are_known_codes_with_a_cefr_level() -> None:
    assert make_language(code_value="en", level="c1").level.value == "c1"
    with pytest.raises(ProfileInputError, match="Langue inconnue"):
        make_language(code_value="klingon", level="c1")
    with pytest.raises(ProfileInputError, match="Niveau de langue"):
        make_language(code_value="es", level="fluent")
