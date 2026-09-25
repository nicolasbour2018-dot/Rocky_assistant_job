"""Scoring rules, one case per rule of the decision (docs/decisions/C4-scoring.md)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from rocky.offres.analysis.model import (
    Condition,
    ConditionKind,
    ExperienceNeed,
    Importance,
    LanguageNeed,
    PostingAnalysis,
    Salary,
    SalaryPeriod,
    SkillMatch,
)
from rocky.offres.scoring.model import (
    CAP,
    RULES_VERSION,
    CapKind,
    ComponentCode,
    ConfidenceLevel,
    Job,
    ProfileSkill,
    Score,
    ScoringProfile,
    ScoringTrack,
    TrackScore,
)
from rocky.offres.scoring.rules import score, scoring_profile
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import (
    Contract,
    ExperienceDraft,
    ExperienceKind,
    Identity,
    Language,
    LanguageDraft,
    LanguageLevel,
    OnboardingState,
    Preferences,
    Profile,
    Project,
    ProjectDraft,
    RemoteMode,
    Skill,
    SkillCategory,
    SkillDraft,
    Text,
    Track,
    TrackDraft,
    TrackStatus,
)
from rocky.profil.model import Experience as ProfileExperience

TODAY = date(2026, 9, 25)
DATA = ScoringTrack(
    id=1,
    name="Data",
    titles=("Data Analyst", "Data Scientist"),
    keywords=("pandas",),
    excluded_keywords=("stage", "commercial"),
    locations=("Paris", "Eure-et-Loir"),
)
PROFILE = ScoringProfile(
    skills=(
        ProfileSkill("Python", is_key=True, proven=True),
        ProfileSkill("SQL", proven=True),
        ProfileSkill("Tableau"),
        ProfileSkill("Gestion des données", is_key=True, proven=True),
    ),
    tracks=(DATA,),
    preferences=Preferences(
        contracts=(Contract.PERMANENT, Contract.FREELANCE),
        remote_modes=(RemoteMode.HYBRID, RemoteMode.FULL_REMOTE),
        min_salary_eur=45_000,
        min_daily_rate_eur=400,
    ),
    languages=(("fr", LanguageLevel.NATIVE), ("en", LanguageLevel.B2)),
    jobs=(
        Job(date(2022, 1, 1), date(2024, 1, 1), frozenset({"Python", "SQL"})),
        Job(date(2014, 1, 1), date(2020, 1, 1), frozenset()),
    ),
)


def offer(**facts: Any) -> CollectedOffer:
    base = CollectedOffer(
        source="site.example",
        external_id="1",
        url="https://site.example/1",
        title="Data Analyst H/F",
        description="Texte",
        description_complete=True,
        location="Paris 9e",
        country="France",
    )
    return replace(base, **facts)


def match(skill: str, importance: Importance = Importance.ELIMINATORY) -> SkillMatch:
    return SkillMatch(skill, skill.lower(), importance, f"Phrase sur {skill}.")


STRONG_SKILLS = (
    match("Python"),
    match("SQL"),
    match("Tableau", Importance.PREFERRED),
    match("Gestion des données"),
)


def analysis(**facts: Any) -> PostingAnalysis:
    base = PostingAnalysis(
        rules_version="analyse-test",
        description="Texte de l'annonce, avec pandas.",
        skills=STRONG_SKILLS,
        contracts=(Contract.PERMANENT,),
        remote=RemoteMode.HYBRID,
        salary=Salary(45_000, 55_000, "EUR", SalaryPeriod.YEARLY, False, "45-55 k€"),
        experience=ExperienceNeed(2, "2 ans d'expérience"),
        languages=(LanguageNeed("en", LanguageLevel.B2, "Anglais B2"),),
    )
    return replace(base, **facts)


def scored(
    posting: PostingAnalysis | None = None,
    collected: CollectedOffer | None = None,
    profile: ScoringProfile = PROFILE,
) -> TrackScore:
    return score(posting or analysis(), collected or offer(), profile, today=TODAY).best


def value(result: TrackScore, code: ComponentCode) -> float | None:
    return result.component(code).value


# A full match.


def test_a_posting_that_fits_everything_scores_100_with_high_confidence() -> None:
    result = scored()

    assert result.display == 100
    assert result.confidence.level == ConfidenceLevel.HIGH
    assert result.caps == ()
    assert result.gaps == ()
    assert result.track_name == "Data"


def test_every_component_explains_itself() -> None:
    result = scored()

    assert [item.code for item in result.components] == list(ComponentCode)
    assert all(item.detail for item in result.components)
    assert (
        "Python (éliminatoire, clé, prouvée, 1,5 pt)"
        in result.component(ComponentCode.SKILLS).evidence[0]
    )


# Skills: evidence points, minimal evidence (Q2, Q3, Q26).


def test_one_or_two_skills_never_fill_the_skills_component() -> None:
    result = scored(analysis(skills=(match("Python"), match("SQL"))))

    # Python key and proven 1.5 + SQL proven 1 = 2.5 points of 4.
    assert value(result, ComponentCode.SKILLS) == pytest.approx(2.5 / 4)


def test_importance_key_flag_and_proof_weigh_a_skill() -> None:
    mentioned = scored(analysis(skills=(match("SQL", Importance.DETECTED),)))
    unproven = scored(analysis(skills=(match("Tableau"),)))

    assert value(mentioned, ComponentCode.SKILLS) == pytest.approx(0.3 / 4)
    assert value(unproven, ComponentCode.SKILLS) == pytest.approx(0.7 / 4)


def test_a_requirement_outside_the_profile_costs_one_point_and_is_a_gap() -> None:
    result = scored(analysis(requirements=("Expérience impérative sur Informatica.",)))

    assert value(result, ComponentCode.SKILLS) == pytest.approx((4.42 - 1) / 4)
    assert "Exigence hors profil : « Expérience impérative sur Informatica. »" in (
        result.gaps
    )


def test_requirements_never_bring_the_evidence_below_zero() -> None:
    result = scored(
        analysis(skills=(match("SQL", Importance.DETECTED),), requirements=("A.", "B."))
    )

    assert value(result, ComponentCode.SKILLS) == 0.0
    assert result.features["net_evidence"] == 0.0


# Title (Q4).


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Data Analyst (H/F)", 1.0),
        ("Data Analysts", 1.0),
        ("Data Protection Analyst - Freelance", 0.5),
        ("Analyste Data Marketing", 0.25),
        ("Comptable", 0.0),
    ],
)
def test_title_is_compared_with_the_titles_of_the_track(
    title: str, expected: float
) -> None:
    result = scored(collected=offer(title=title))

    assert value(result, ComponentCode.TITLE) == pytest.approx(expected)


def test_title_keeps_the_best_title_of_the_track() -> None:
    result = scored(collected=offer(title="Data Scientist confirmé"))

    assert result.features["track_title"] == "Data Scientist"


def test_a_track_without_title_scores_0_on_the_title() -> None:
    profile = replace(PROFILE, tracks=(replace(DATA, titles=()),))

    assert value(scored(profile=profile), ComponentCode.TITLE) == 0.0


# Caps: excluded words and conditions (Q5, Q6, Q14).


def test_an_excluded_word_in_the_title_caps_the_score() -> None:
    result = scored(collected=offer(title="Stage Data Analyst"))

    assert result.value == CAP
    assert result.uncapped > CAP
    assert [(cap.kind, cap.label) for cap in result.caps] == [
        (CapKind.EXCLUDED_WORD, "Mot exclu : stage")
    ]


def test_an_excluded_word_in_the_description_is_only_shown() -> None:
    result = scored(analysis(description="Poste commercial, au contact des clients."))

    assert result.caps == ()
    assert "Mot exclu dans la description : commercial" in result.notes


def test_a_condition_caps_the_score_as_blocking() -> None:
    condition = Condition(
        ConditionKind.CLEARANCE, "Habilitation secret défense requise."
    )
    result = scored(analysis(conditions=(condition,)))

    assert result.value == CAP
    assert result.caps[0].label == "Bloquant : Habilitation"
    assert result.caps[0].evidence == "Habilitation secret défense requise."


def test_caps_add_up_and_the_score_keeps_the_single_cap() -> None:
    condition = Condition(ConditionKind.DRIVING_LICENCE, "Permis B exigé.")
    result = scored(
        analysis(conditions=(condition,)), offer(title="Stage Data Analyst")
    )

    assert len(result.caps) == 2
    assert result.value == CAP


# Contract, remote work (Q7).


def test_an_unwanted_contract_costs_only_its_points() -> None:
    result = scored(analysis(contracts=(Contract.INTERNSHIP,)))

    assert value(result, ComponentCode.CONTRACT) == 0.0
    assert result.caps == ()
    assert result.display == 90  # 10 of 100 lost: the other components are full.


def test_remote_mode_is_compared_with_the_preferences() -> None:
    assert value(scored(analysis(remote=RemoteMode.ON_SITE)), ComponentCode.REMOTE) == 0


def test_a_component_without_information_is_left_out() -> None:
    result = scored(analysis(contracts=(), remote=None))

    assert value(result, ComponentCode.CONTRACT) is None
    assert value(result, ComponentCode.REMOTE) is None
    assert result.display == 100


# Location (Q9, Q15).


@pytest.mark.parametrize(
    ("location", "country", "remote", "expected"),
    [
        ("8ème Arrondissement, Paris", "France", RemoteMode.HYBRID, 1.0),
        ("Chartres", "FR", RemoteMode.ON_SITE, 0.3),
        ("Lyon", "France", RemoteMode.HYBRID, 0.5),
        ("New York", "US", RemoteMode.HYBRID, 0.0),
        ("New York", "US", RemoteMode.FULL_REMOTE, 0.5),
        ("Lyon", "France", RemoteMode.FULL_REMOTE, None),
        (None, None, RemoteMode.HYBRID, None),
    ],
)
def test_location_rules(
    location: str | None,
    country: str | None,
    remote: RemoteMode,
    expected: float | None,
) -> None:
    result = scored(analysis(remote=remote), offer(location=location, country=country))

    assert value(result, ComponentCode.LOCATION) == expected


def test_a_foreign_full_remote_posting_says_what_to_check() -> None:
    result = scored(
        analysis(remote=RemoteMode.FULL_REMOTE), offer(location="Austin", country="US")
    )

    assert (
        "vérifier le droit au travail"
        in result.component(ComponentCode.LOCATION).detail
    )


def test_an_unknown_country_is_read_as_france_and_said() -> None:
    result = scored(collected=offer(location="Lille", country=None))

    assert value(result, ComponentCode.LOCATION) == 0.5
    assert "Pays non précisé : l'offre est lue comme en France" in result.notes


def test_full_remote_in_france_is_neutral_and_does_not_lower_confidence() -> None:
    result = scored(
        analysis(remote=RemoteMode.FULL_REMOTE, contracts=(), salary=None),
        offer(location="Lyon"),
    )

    assert result.component(ComponentCode.LOCATION).neutral
    assert result.confidence.level == ConfidenceLevel.HIGH


def test_a_track_location_named_france_covers_the_whole_country() -> None:
    profile = replace(PROFILE, tracks=(replace(DATA, locations=("France",)),))

    assert value(scored(profile=profile), ComponentCode.LOCATION) == 1.0


# Salary (Q8, Q24).


def test_a_daily_rate_is_compared_with_the_minimum_daily_rate() -> None:
    salary = Salary(300, 350, "EUR", SalaryPeriod.DAILY, False, "TJM 300-350 €")
    result = scored(analysis(salary=salary))

    assert value(result, ComponentCode.SALARY) == pytest.approx(350 / 400)
    assert result.component(ComponentCode.SALARY).evidence == ("TJM 300-350 €",)


def test_a_monthly_salary_is_compared_over_a_year() -> None:
    salary = Salary(3_000, 3_000, "EUR", SalaryPeriod.MONTHLY, False)

    assert value(
        scored(analysis(salary=salary)), ComponentCode.SALARY
    ) == pytest.approx(36_000 / 45_000)


def test_a_deduced_period_halves_the_salary_weight_and_lowers_confidence() -> None:
    salary = Salary(50_000, 50_000, "EUR", SalaryPeriod.YEARLY, True)
    result = scored(analysis(salary=salary))

    assert result.component(ComponentCode.SALARY).weight == 2.5
    assert result.confidence.level == ConfidenceLevel.MEDIUM
    assert "Période du salaire déduite du montant" in result.confidence.reasons


@pytest.mark.parametrize(
    ("salary", "detail"),
    [
        (
            Salary(20, 25, "EUR", SalaryPeriod.HOURLY, False),
            "Salaire horaire, non comparé",
        ),
        (
            Salary(90_000, 120_000, "USD", SalaryPeriod.YEARLY, False),
            "Salaire en USD, non comparé",
        ),
    ],
)
def test_a_salary_that_cannot_be_compared_is_left_out(
    salary: Salary, detail: str
) -> None:
    result = scored(analysis(salary=salary))

    assert value(result, ComponentCode.SALARY) is None
    assert result.component(ComponentCode.SALARY).detail == detail


# Experience and languages (Q10, Q22, Q23).


def test_experience_counts_the_jobs_linked_to_the_skills_found() -> None:
    result = scored(analysis(experience=ExperienceNeed(4, "4 ans minimum")))

    # Two relevant years (2022-2024) of four asked; eight years of jobs in all.
    assert value(result, ComponentCode.EXPERIENCE) == pytest.approx(0.5)
    assert result.features["relevant_years"] == 2.0
    assert result.features["total_years"] == 8.0
    assert (
        "sur des postes utilisant Python, SQL"
        in result.component(ComponentCode.EXPERIENCE).detail
    )


def test_overlapping_jobs_are_counted_once() -> None:
    profile = replace(
        PROFILE,
        jobs=(
            Job(date(2020, 1, 1), date(2022, 1, 1), frozenset({"Python"})),
            Job(date(2021, 1, 1), None, frozenset({"SQL"})),
        ),
    )
    result = scored(profile=profile)

    assert result.features["relevant_years"] == pytest.approx(6.7)


@pytest.mark.parametrize(
    ("need", "expected"),
    [
        (LanguageNeed("en", LanguageLevel.C1, "Anglais C1"), 0.5),
        (LanguageNeed("en", None, "Anglais courant"), 1.0),
        (LanguageNeed("de", None, "Allemand"), 0.0),
    ],
)
def test_languages_compare_levels(need: LanguageNeed, expected: float) -> None:
    result = scored(analysis(languages=(need,)))

    assert value(result, ComponentCode.LANGUAGES) == expected


# Confidence (Q11, Q25).


def test_an_incomplete_description_gives_low_confidence() -> None:
    result = scored(
        collected=offer(description_complete=False, incomplete_reason="Extrait Adzuna")
    )

    assert result.confidence.level == ConfidenceLevel.LOW
    assert "Description incomplète : Extrait Adzuna" in result.confidence.reasons


def test_little_evidence_gives_low_confidence_without_changing_the_score() -> None:
    few = scored(analysis(skills=(match("SQL"),)))

    assert few.confidence.level == ConfidenceLevel.LOW
    assert few.confidence.reasons[0].startswith("Preuves insuffisantes")


def test_three_optional_components_without_information_give_medium_confidence() -> None:
    result = scored(analysis(contracts=(), remote=None, salary=None))

    assert result.confidence.level == ConfidenceLevel.MEDIUM


# Tracks (Q1, Q20).


def test_each_active_track_has_its_score_and_the_best_one_wins() -> None:
    sales = ScoringTrack(
        id=2, name="Ventes", titles=("Commercial",), locations=("Lyon",)
    )
    result = score(
        analysis(), offer(), replace(PROFILE, tracks=(sales, DATA)), today=TODAY
    )

    assert [track.track_name for track in result.tracks] == ["Ventes", "Data"]
    assert result.best.track_name == "Data"


def test_without_an_active_track_neither_title_nor_place_is_compared() -> None:
    result = scored(profile=replace(PROFILE, tracks=()))

    assert result.track_id is None
    assert value(result, ComponentCode.TITLE) is None
    assert value(result, ComponentCode.LOCATION) is None
    assert result.confidence.level == ConfidenceLevel.LOW


def test_keywords_found_are_kept_as_features_without_weight() -> None:
    result = scored()

    assert result.features["keywords_found"] == ["pandas"]


# Threshold, purity and stored form (Q12, Q18, Q21).


def test_the_threshold_gives_its_reason() -> None:
    low = score(analysis(skills=()), offer(title="Comptable"), PROFILE, today=TODAY)
    high = score(analysis(), offer(), PROFILE, today=TODAY)

    assert low.threshold_reason == f"Score sous le seuil ({low.best.display} < 50)"
    assert high.threshold_reason is None


def test_scoring_changes_nothing_it_reads() -> None:
    posting, collected = analysis(), offer()
    before = (repr(posting), repr(collected), repr(PROFILE))

    score(posting, collected, PROFILE, today=TODAY)

    assert (repr(posting), repr(collected), repr(PROFILE)) == before


def test_the_score_goes_through_json_unchanged() -> None:
    condition = Condition(ConditionKind.NATIONALITY, "Nationalité française.")
    result = score(analysis(conditions=(condition,)), offer(), PROFILE, today=TODAY)

    stored = json.loads(json.dumps(result.to_json()))

    assert Score.from_json(stored) == result
    assert stored["rules_version"] == RULES_VERSION
    assert stored["analysis_rules_version"] == "analyse-test"


# From the profile.


def test_scoring_profile_reads_proof_active_tracks_and_jobs() -> None:
    def skill(skill_id: int, label: str, *, key: bool = False) -> Skill:
        return Skill(
            skill_id, SkillDraft(Text(label), SkillCategory.TECHNICAL, is_key=key)
        )

    def experience(
        kind: ExperienceKind, skill_ids: tuple[int, ...]
    ) -> ProfileExperience:
        return ProfileExperience(
            1,
            ExperienceDraft(
                kind, Text("Poste"), "Org", date(2020, 1, 1), skill_ids=skill_ids
            ),
        )

    profile = Profile(
        id=1,
        account_id=1,
        identity=Identity(),
        preferences=Preferences(),
        onboarding=OnboardingState(),
        tracks=(
            Track(1, TrackStatus.ACTIVE, TrackDraft("Data", titles=("Data Analyst",))),
            Track(2, TrackStatus.PAUSED, TrackDraft("Pause")),
            Track(3, TrackStatus.ARCHIVED, TrackDraft("Ancienne")),
        ),
        skills=(skill(1, "Python", key=True), skill(2, "SQL"), skill(3, "Tableau")),
        languages=(Language(1, LanguageDraft("en", LanguageLevel.C1)),),
        experiences=(
            experience(ExperienceKind.JOB, (1,)),
            experience(ExperienceKind.EDUCATION, (2,)),
        ),
        projects=(Project(1, ProjectDraft(Text("Projet"), skill_ids=(2,))),),
    )

    result = scoring_profile(profile)

    assert [track.name for track in result.tracks] == ["Data"]
    assert [(s.label, s.is_key, s.proven) for s in result.skills] == [
        ("Python", True, True),
        ("SQL", False, True),
        ("Tableau", False, False),
    ]
    assert result.jobs == (Job(date(2020, 1, 1), None, frozenset({"Python"})),)
    assert result.languages == (("en", LanguageLevel.C1),)
