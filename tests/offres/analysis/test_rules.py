"""Analysis rules on short postings; each trap met in the measure sample (docs/procedures/c3-mesure/) has its case."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from rocky.offres.analysis.model import (
    RULES_VERSION,
    ConditionKind,
    Importance,
    PostingAnalysis,
    SalaryPeriod,
)
from rocky.offres.analysis.rules import account_skills, analyze, deduced_period
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Contract, LanguageLevel, RemoteMode
from rocky.profil.rules import make_skill

TODAY = date(2026, 9, 25)
SKILLS = account_skills(
    [
        make_skill(label_fr="Python", category="technical"),
        make_skill(label_fr="SQL", category="technical"),
        make_skill(label_fr="Rigueur", label_en="Rigor", category="soft"),
        make_skill(label_fr="Autonomie", label_en="Autonomy", category="soft"),
        make_skill(label_fr="Agile", category="business"),
        make_skill(
            label_fr="Gestion des données",
            label_en="Data management",
            category="business",
        ),
        make_skill(
            label_fr="NLP",
            aliases=["Traitement du langage naturel (NLP)"],
            category="technical",
        ),
        make_skill(label_fr="Java", category="technical"),
    ]
)


def posting(description: str, **facts: Any) -> CollectedOffer:
    offer = CollectedOffer(
        source="site.example",
        external_id="1",
        url="https://site.example/1",
        title="Data analyst",
        description=description,
        description_complete=True,
    )
    return replace(offer, **facts)


def analysis(description: str, **facts: Any) -> PostingAnalysis:
    return analyze(posting(description, **facts), SKILLS, today=TODAY)


def importance(result: PostingAnalysis, skill: str) -> Importance | None:
    return next(
        (match.importance for match in result.skills if match.skill == skill), None
    )


# Skills.


def test_a_name_x_y_answers_to_x_and_to_y() -> None:
    nlp = next(skill for skill in SKILLS if skill.label == "NLP")

    assert {
        "nlp",
        "traitement du langage naturel",
        "traitement du langage naturel nlp",
    } <= nlp.terms


def test_skills_are_found_by_any_of_their_names_with_evidence() -> None:
    result = analysis(
        "Vous pratiquez le traitement du langage naturel et le data management, pas le JavaScript."
    )

    found = {match.skill: match for match in result.skills}
    assert set(found) == {"NLP", "Gestion des données"}
    assert found["NLP"].term == "traitement du langage naturel"
    assert found["NLP"].evidence.startswith("Vous pratiquez")


def test_a_marker_in_brackets_only_concerns_the_word_before_it() -> None:
    result = analysis("Maîtrise des outils : Python (obligatoire), SQL.")

    assert importance(result, "Python") == Importance.ELIMINATORY
    assert importance(result, "SQL") == Importance.DETECTED


def test_a_section_heading_gives_its_weight_to_its_lines() -> None:
    result = analysis(
        "The following skills are essential for the role:\n- Python\n- Autonomy and rigor\n"
        "The following skills may help you stand out:\n- SQL"
    )

    assert importance(result, "Python") == Importance.ELIMINATORY
    assert importance(result, "Autonomie") == Importance.ELIMINATORY
    assert importance(result, "SQL") == Importance.DETECTED


def test_a_marker_far_away_in_a_run_on_text_does_not_apply() -> None:
    far = "des sujets variés " * 12
    result = analysis(
        f"Compétences indispensables Expérience en SQL {far} Votre rigueur Votre autonomie"
    )

    assert importance(result, "SQL") == Importance.ELIMINATORY
    assert importance(result, "Rigueur") == Importance.DETECTED


def test_a_denied_requirement_is_not_one() -> None:
    result = analysis(
        "Python n'est pas requis. Aucune expérience en SQL n'est requise."
    )

    assert importance(result, "Python") == Importance.DETECTED
    assert importance(result, "SQL") == Importance.DETECTED


def test_a_candidate_who_appreciates_something_is_not_a_preference() -> None:
    result = analysis("Vous appréciez le travail en mode agile. Python est un plus.")

    assert importance(result, "Agile") == Importance.DETECTED
    assert importance(result, "Python") == Importance.PREFERRED


def test_the_strongest_mention_wins() -> None:
    result = analysis("Stack : Python, SQL. Python obligatoire.")

    assert importance(result, "Python") == Importance.ELIMINATORY


def test_a_section_title_and_an_english_application_sentence_are_not_requirements() -> (
    None
):
    result = analysis(
        "Skills And Experience Required\n- Good knowledge of Excel.\n"
        "If your application is in line with the required profile, you will be contacted."
    )

    assert result.requirements == ()


def test_required_sentences_outside_the_skills_are_kept_but_not_the_application() -> (
    None
):
    result = analysis(
        "Expérience impérative sur Informatica MDM. L'envoi du CV est obligatoire."
    )

    assert result.requirements == ("Expérience impérative sur Informatica MDM.",)


# Conditions.


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Nationalité française exigée.", ConditionKind.NATIONALITY),
        (
            "We are not able to consider candidates who currently or in the future will require visa sponsorship.",
            ConditionKind.NATIONALITY,
        ),
        ("Must be authorized to work in the United States.", ConditionKind.NATIONALITY),
        (
            "La personne retenue fera l'objet d'une procédure d'habilitation.",
            ConditionKind.CLEARANCE,
        ),
        ("Permis B obligatoire.", ConditionKind.DRIVING_LICENCE),
    ],
)
def test_a_condition_is_found_with_its_sentence(text: str, kind: ConditionKind) -> None:
    conditions = analysis(text).conditions

    assert [condition.kind for condition in conditions] == [kind]
    assert conditions[0].evidence == text


@pytest.mark.parametrize(
    "text",
    [
        "Quels que soient votre âge, votre handicap, votre origine ou votre nationalité.",
        "Précisez la nationalité et le confidential defense ou non.",
        "Visa sponsorship available for this role.",
        "Permis B apprécié.",
    ],
)
def test_a_mention_that_asks_nothing_is_not_a_condition(text: str) -> None:
    assert analysis(text).conditions == ()


# Contracts.


def test_the_title_names_the_contract_before_the_text_and_the_source() -> None:
    result = analysis(
        "Stage de 6 mois, CDI à la clé.",
        title="Stage Data Scientist",
        source="adzuna",
        contract="permanent",
    )

    assert result.contracts == (Contract.INTERNSHIP,)


@pytest.mark.parametrize(
    ("source", "raw", "expected"),
    [
        ("wttj", "full_time", (Contract.PERMANENT,)),
        ("adzuna", "permanent full_time", (Contract.PERMANENT,)),
        ("adzuna", "contract", ()),  # a fixed term or a mission: not enough alone
        ("site.example", "FULL_TIME", ()),  # JSON-LD: a working time, not a contract
        ("site.example", "CONTRACTOR", (Contract.FREELANCE,)),
        ("apec", "CDI", (Contract.PERMANENT,)),
        ("apec", "Stage", (Contract.INTERNSHIP,)),
        (
            "apec",
            "CDI - Alternance - Contrat d'apprentissage",
            (Contract.PERMANENT, Contract.APPRENTICESHIP),
        ),
        ("apec", "Mission d'intérim", (Contract.TEMPORARY,)),
        ("wellfound", "contract", (Contract.FREELANCE,)),
    ],
)
def test_source_facts_are_decoded_per_source(
    source: str, raw: str, expected: tuple[Contract, ...]
) -> None:
    assert (
        analysis("Rejoignez-nous.", source=source, contract=raw).contracts == expected
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Contrat à durée indéterminée, statut cadre.", (Contract.PERMANENT,)),
        ("Location: Paris, France\n\nContract type: Permanent", (Contract.PERMANENT,)),
        ("Taux journalier (TJM) : 450-500.", (Contract.FREELANCE,)),
        ("Une première expérience (stage, alternance ou premier emploi).", ()),
        ("Poste en alternance de 24 mois.", (Contract.APPRENTICESHIP,)),
    ],
)
def test_contracts_written_in_the_text(
    text: str, expected: tuple[Contract, ...]
) -> None:
    assert analysis(text).contracts == expected


# Remote work.


@pytest.mark.parametrize(
    ("text", "facts", "expected"),
    [
        ("Rejoignez-nous.", {"source": "wttj", "remote": "partial"}, RemoteMode.HYBRID),
        (
            "Rejoignez-nous.",
            {"source": "wttj", "remote": "fulltime"},
            RemoteMode.FULL_REMOTE,
        ),
        ("Rejoignez-nous.", {"source": "wttj", "remote": "unknown"}, None),
        (
            "Rejoignez-nous.",
            {"source": "apec", "remote": "Partiel possible"},
            RemoteMode.HYBRID,
        ),
        (
            "Rejoignez-nous.",
            {"source": "apec", "remote": "Non autorisé"},
            RemoteMode.ON_SITE,
        ),
        (
            "Rejoignez-nous.",
            {"remote": "TELECOMMUTE"},
            None,
        ),  # platforms use it for any remote possibility
        ("Jusqu'à 2 jours de télétravail par semaine.", {}, RemoteMode.HYBRID),
        ("Télétravail : 3 jours par semaine.", {}, RemoteMode.HYBRID),
        ("This is a fully remote opportunity.", {}, RemoteMode.FULL_REMOTE),
        ("Poste à Vélizy (pas de full remote).", {}, None),
        (
            "Hybrid: 2 to 3 days at the office. 30% of us work fully remotely.",
            {},
            RemoteMode.HYBRID,
        ),
        ("Options de télétravail indemnisé.", {}, None),
        ("Pas de télétravail possible.", {}, RemoteMode.ON_SITE),
    ],
)
def test_remote_work(
    text: str, facts: dict[str, object], expected: RemoteMode | None
) -> None:
    assert analysis(text, **facts).remote == expected


# Salary.


def test_a_written_day_rate_gives_the_period() -> None:
    salary = analysis(
        "Taux journalier (TJM): 450-500", salary_min=450.0, salary_max=500.0
    ).salary

    assert salary is not None
    assert (salary.minimum, salary.maximum, salary.period) == (
        450,
        500,
        SalaryPeriod.DAILY,
    )
    assert salary.period_deduced is False


def test_without_a_written_period_it_is_deduced_and_said_so() -> None:
    salary = analysis(
        "Rejoignez-nous.", salary_min=40000.0, salary_max=60000.0, salary_currency="EUR"
    ).salary

    assert salary is not None
    assert (salary.period, salary.period_deduced, salary.currency) == (
        SalaryPeriod.YEARLY,
        True,
        "EUR",
    )


def test_the_unit_of_the_source_is_a_written_period() -> None:
    salary = analysis(
        "Rejoignez-nous.", salary_min=450.0, salary_max=450.0, salary_period="DAY"
    ).salary

    assert salary is not None
    assert (salary.period, salary.period_deduced) == (SalaryPeriod.DAILY, False)


@pytest.mark.parametrize(
    ("text", "bounds", "currency", "period", "deduced"),
    [
        (
            "Fourchette de salaire\n45-55 k€",
            (45000, 55000),
            "EUR",
            SalaryPeriod.YEARLY,
            True,
        ),
        (
            "Annual gross fixed salary: €46,000 – €52,000;",
            (46000, 52000),
            "EUR",
            SalaryPeriod.YEARLY,
            False,
        ),
        (
            "Salaire : 16 € - 17 € par heure",
            (16, 17),
            "EUR",
            SalaryPeriod.HOURLY,
            False,
        ),
        (
            "Base salary for this role: $175k to $225k.",
            (175000, 225000),
            "USD",
            SalaryPeriod.YEARLY,
            True,
        ),
        (
            "Salaire : 2800€ brut mensuel",
            (2800, 2800),
            "EUR",
            SalaryPeriod.MONTHLY,
            False,
        ),
    ],
)
def test_a_salary_written_in_the_text(
    text: str,
    bounds: tuple[int, int],
    currency: str,
    period: SalaryPeriod,
    deduced: bool,
) -> None:
    salary = analysis(text).salary

    assert salary is not None
    assert (salary.minimum, salary.maximum) == bounds
    assert (salary.currency, salary.period, salary.period_deduced) == (
        currency,
        period,
        deduced,
    )
    assert salary.evidence


@pytest.mark.parametrize(
    "text",
    [
        "Titres restaurant d'une valeur de 11,52 €.",
        "En 2025, le Groupe a réalisé un chiffre d'affaires de 5,6 milliards d'euros.",
        "Participation symbolique au capital (20 EUR).",
        "We raised $475M from our investors.",
    ],
)
def test_an_amount_that_is_not_a_salary_is_ignored(text: str) -> None:
    assert analysis(text).salary is None


def test_an_hourly_rate_next_to_a_yearly_range_does_not_change_its_period() -> None:
    salary = analysis(
        "Salary Range: $100,000 – $180,000 (Calculated at $50 – $90/hr)",
        salary_min=100000.0,
        salary_max=180000.0,
        salary_currency="USD",
    ).salary

    assert salary is not None
    assert (salary.period, salary.period_deduced) == (SalaryPeriod.YEARLY, True)


@pytest.mark.parametrize(
    ("amount", "period"),
    [
        (18, SalaryPeriod.HOURLY),
        (150, SalaryPeriod.HOURLY),
        (151, SalaryPeriod.DAILY),
        (2000, SalaryPeriod.DAILY),
        (3200, SalaryPeriod.MONTHLY),
        (15000, SalaryPeriod.MONTHLY),
        (15001, SalaryPeriod.YEARLY),
    ],
)
def test_the_deduction_thresholds_of_the_decision(
    amount: float, period: SalaryPeriod
) -> None:
    assert deduced_period(amount) == period


# Experience, languages, closing date.


@pytest.mark.parametrize(
    ("text", "years"),
    [
        ("3 à 5 ans d'expérience en tant que Data Scientist.", 3),
        ("Expérience : 2-3 ans minimum en Data Science.", 2),
        ("0 à 3 ans d'expérience en data science.", 0),
        ("Tu as au moins 5ans d'expérience dont 3 ans dans la banque.", 5),
        ("Fondée en 2025, ans d'avance sur le marché.", None),
        ("Two or more years of experience in product analytics.", 2),
        (
            "3+ years of data science experience. 5+ years of experience in a related field.",
            5,
        ),
        ("At least 3 years of professional experience working as a Data Analyst.", 3),
        ("Our science team has spent the past 2+ years pioneering new devices.", None),
        ("Moins de 5 ans, 5 à 10 ans, Plus de 10 ans.", None),
    ],
)
def test_experience_asked(text: str, years: int | None) -> None:
    experience = analysis(text).experience

    assert (experience.years if experience else None) == years


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Vous parlez français et anglais couramment.", {"fr": None, "en": None}),
        ("Un niveau d'anglais C1/C2.", {"en": LanguageLevel.C1}),
        ("Proficiency in professional French and English.", {"fr": None, "en": None}),
        ("Langues : Aucune langue attendue", {}),
        ("Rexel est le leader français de la distribution professionnelle.", {}),
        ("Des prestations dont bénéficient des millions de Français.", {}),
    ],
)
def test_languages_asked(text: str, expected: dict[str, LanguageLevel | None]) -> None:
    assert {need.code: need.level for need in analysis(text).languages} == expected


def test_the_closing_date_of_the_source_wins() -> None:
    result = analysis(
        "Date limite de candidature : 15/10/2026.", deadline=date(2026, 10, 20)
    )

    assert result.deadline == date(2026, 10, 20)


@pytest.mark.parametrize(
    ("text", "deadline"),
    [
        ("Date limite de candidature : 15/10/2026.", date(2026, 10, 15)),
        ("Candidatures jusqu'au 12 octobre 2026.", date(2026, 10, 12)),
        ("Postulez avant le 3 novembre.", date(2026, 11, 3)),
        ("Date limite : 31/02/2026.", None),
    ],
)
def test_a_closing_date_written_in_the_text(text: str, deadline: date | None) -> None:
    assert analysis(text).deadline == deadline


# The whole analysis.


def test_the_analysis_keeps_its_rules_version_and_a_readable_description() -> None:
    result = analysis("<p>Missions</p><ul><li>Python</li></ul>")

    assert result.rules_version == RULES_VERSION
    assert result.description == "Missions\n\n- Python"


def test_the_analysis_is_the_same_twice() -> None:
    offer = posting("Python obligatoire. 45-55 k€ de salaire. Anglais courant.")

    assert analyze(offer, SKILLS, today=TODAY) == analyze(offer, SKILLS, today=TODAY)
