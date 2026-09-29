"""The content of a CV: only what the master CV holds, in its order; English never replaced by French (D2, Q10, Q11)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from rocky.profil.cv.content import Span, cv_content, paragraphs
from tests.profil.cv.sample import TODAY, sample_profile


def test_the_layout_decides_what_is_shown_and_in_which_order() -> None:
    content = cv_content(sample_profile(), "fr", TODAY)

    assert [group.name for group in content.groups] == [
        "Langages et données",
        "Science des données",
        "Déploiement",
    ]
    assert content.groups[0].skills == ("Python", "SQL", "Pandas")
    assert content.transversal == ("Curiosité", "Gestion de projet", "Pédagogie")
    assert [project.name for project in content.projects] == [
        "Tri des messages clients",
        "Prévision des stocks",
    ]
    assert [entry.title for entry in content.experiences] == [
        "Data scientist",
        "Responsable d'exploitation",
    ]
    assert content.experiences[0].period == "2023 – aujourd’hui"
    assert content.education[0].period == "2021 – 2022"
    assert content.age == "36 ans"
    assert content.missing == ()


def test_an_english_cv_lists_every_text_still_in_french() -> None:
    content = cv_content(sample_profile(english=False), "en", TODAY)

    assert content.missing == ("Expérience « Data scientist » : puces",)
    assert cv_content(sample_profile(), "en", TODAY).age == "36 years old"


def test_the_age_is_shown_only_when_asked() -> None:
    profile = sample_profile()
    hidden = replace(profile, identity=replace(profile.identity, show_age=False))

    assert cv_content(hidden, "fr", date(2026, 5, 1)).age is None


def test_bold_words_and_paragraphs_of_the_headline() -> None:
    assert paragraphs("Un **mot** fort.\n\nSecond  paragraphe") == (
        (Span("Un "), Span("mot", bold=True), Span(" fort.")),
        (Span("Second paragraphe"),),
    )
