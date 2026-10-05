"""The English version of a derived template (decision D3, Q8, Q16–Q21, Q24), on the fictional designed CV: the
design without any text, each kept text in the English the user validated, names and contacts copied."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from rocky.profil.cv.check import Fact, check_cv
from rocky.profil.cv.content import CvContent, cv_content
from rocky.profil.cv.derived import (
    LAYER,
    LAYER_BARE,
    TEMPLATE_FILE,
    derived_facts,
    draw_derived,
    english_template,
    kept_texts,
    render_derived,
)
from rocky.profil.cv.proposals import preview_profile
from rocky.profil.cv.rendering import CvRefusedError
from tests.profil.cv.fixtures import TODAY, Shared, imported
from tests.profil.cv.test_derived import _in_english, text_of

ENGLISH = {
    "DATA SCIENTIST": "DATA SCIENTIST",
    "Data scientist issue de la logistique, je transforme des données opérationnelles en outils de décision.": (
        "Data scientist from logistics, I turn operational data into decision tools."
    ),
    "CONTACT": "CONTACT",
    "PROJETS": "PROJECTS",
    "EXPÉRIENCES": "EXPERIENCE",
    "2023 - 2026 : Data scientist _- Transports Exemple -_": "2023 - 2026: Data scientist _- Transports Exemple -_",
    "• Prévision de la demande par entrepôt.": "• Demand forecasting per warehouse.",
    "Conçu pour une lecture responsable": "Designed for responsible reading",
    "Problématique": "Problem",
    "Stack technique": "Tech stack",
}


def translations(files: Mapping[str, bytes], **changed: str) -> dict[str, str]:
    return {
        text.id: changed.get(text.text, ENGLISH[text.text])
        for text in kept_texts(files)
    }


def content_of(shared: Shared) -> CvContent:
    return cv_content(_in_english(preview_profile(shared.proposals())), "en", TODAY)


def test_a_french_template_keeps_a_page_without_text_and_its_texts(
    shared: Shared,
) -> None:
    files = shared.files()
    texts = {text.text: text for text in kept_texts(files)}

    assert LAYER_BARE in files and files[LAYER_BARE] != files[LAYER]
    assert texts["EXPÉRIENCES"].where == "Titre de section : « EXPÉRIENCES »"
    assert "Problématique" in texts  # the labels of the project cards, once
    # The name and the contacts are never texts to translate (Q21).
    assert not {"CAMILLE MARTIN", "camille.martin@example.org", "06 00 00 00 00"} & set(
        texts
    )


def test_the_english_version_writes_each_kept_text_in_english(shared: Shared) -> None:
    files = english_template(shared.files(), translations(shared.files()), "fr-sha")
    content = content_of(shared)

    document = render_derived(files, content)
    text = text_of(document.pdf)

    assert "Demand forecasting per warehouse." in text
    assert "Prévision de la demande" not in text
    assert "camille.martin@example.org" in text
    assert "Problem: Thousands of messages" in text
    facts = derived_facts(files, content)
    assert Fact("Section", "EXPERIENCE") in facts
    assert Fact("Nom", "CAMILLE MARTIN") in facts
    check = check_cv(document.pdf, facts)
    assert check.readable, check.warnings
    assert b"/SMask" not in document.pdf
    template = json.loads(files[TEMPLATE_FILE])
    assert (template["language"], template["source_sha256"]) == ("en", "fr-sha")


def test_an_english_version_needs_every_text_but_a_preview_shows_the_french(
    shared: Shared,
) -> None:
    partial = {"u2": "Data scientist from logistics."}

    with pytest.raises(ValueError, match="no English"):
        english_template(shared.files(), partial, "fr-sha")
    preview = english_template(shared.files(), partial, "fr-sha", partial=True)
    rendered, _, _ = draw_derived(preview, content_of(shared))

    assert "Prévision de la demande par entrepôt." in text_of(rendered.pdf)


def test_a_translation_too_long_for_its_place_is_an_overflow_that_names_it(
    shared: Shared,
) -> None:
    long = " ".join(
        ["Data scientist from logistics turning operational data into tools."] * 6
    )
    files = english_template(
        shared.files(),
        translations(
            shared.files(),
            **{
                "Data scientist issue de la logistique, je transforme des données "
                "opérationnelles en outils de décision.": long
            },
        ),
        "fr-sha",
    )

    _, _, problems = draw_derived(files, content_of(shared))

    assert any("Accroche" in problem for problem in problems), problems


def test_a_template_made_before_its_units_were_kept_asks_for_a_new_import(
    shared: Shared,
) -> None:
    template = json.loads(shared.files()[TEMPLATE_FILE])
    older = {
        TEMPLATE_FILE: json.dumps(
            {**template, "format": "rocky-cv-gabarit/3"}
        ).encode(),
        LAYER: shared.files()[LAYER],
    }

    with pytest.raises(CvRefusedError, match="réimporte ton CV français"):
        kept_texts(older)


def test_the_same_cv_imported_again_reuses_the_models_answer(
    designed: bytes, shared: Shared
) -> None:
    calls = len(shared.model.prompts)

    again = imported(designed, shared.root, shared.model)

    assert len(shared.model.prompts) == calls
    assert shared.result.template is not None and again.template is not None
    assert again.template.sha256 == shared.result.template.sha256
