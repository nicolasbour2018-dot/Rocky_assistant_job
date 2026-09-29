"""« Vérifier mon CV »: facts found by each PDF reader, concrete warnings, no composite score (D2, Q12)."""

from __future__ import annotations

import io

from PIL import Image

from rocky.profil.cv.check import (
    Fact,
    check_cv,
    expected_facts,
    normalise,
    spaced_letters_ratio,
)
from rocky.profil.cv.content import cv_content
from rocky.profil.cv.rendering import neutral_headings, render_neutral
from rocky.system.render import render_pdf
from tests.profil.cv.sample import TODAY, sample_profile

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0; }} body {{ margin: 20mm; font: 12pt sans-serif; }}</style></head>
<body>{body}</body></html>"""


def test_the_neutral_cv_is_read_whole_by_every_reader() -> None:
    content = cv_content(sample_profile(), "fr", TODAY)
    facts = expected_facts(content, neutral_headings(content))

    check = check_cv(render_neutral(content, None).pdf, facts)

    assert check.readable, check.warnings
    assert check.found_by_all == len(facts)
    assert Fact("Section", "Expériences") in facts
    assert Fact("Compétence", "Pédagogie") in facts
    assert Fact("Année", "2016") in facts
    assert [reader.reader for reader in check.readers] == [
        "pypdf",
        "pdfminer.six",
        "pypdfium2",
    ]


def test_widely_spaced_letters_and_missing_texts_are_reported() -> None:
    pdf = render_pdf(
        PAGE.format(
            body='<h1 style="letter-spacing: 0.6em">EXPÉRIENCES</h1><p>Camille Martin</p>'
        )
    ).pdf

    check = check_cv(
        pdf,
        (
            Fact("Section", "Expériences"),
            Fact("Nom", "Camille Martin"),
            Fact("Projet", "Absent"),
        ),
    )

    assert not check.readable
    assert any(w.startswith("Projet « Absent » : non lu par") for w in check.warnings)
    spaced = next(item for item in check.facts if item.fact.text == "Expériences")
    assert len(spaced.found_by) < len(check.readers)


def test_a_page_made_of_an_image_is_reported_as_such() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 560), "white").save(buffer, format="PNG")
    pdf = render_pdf(
        PAGE.format(body='<img src="page.png" style="width:170mm">'),
        {"page.png": buffer.getvalue()},
    ).pdf

    check = check_cv(pdf, (Fact("Nom", "Camille Martin"),))

    assert any("aucun texte" in warning for warning in check.warnings)


def test_comparison_ignores_case_line_breaks_and_line_end_hyphens() -> None:
    assert normalise("CAMILLE\nMARTIN") == normalise("Camille Martin")
    assert "camille-martin" in normalise("linkedin.com/in/camille-\nmartin")
    assert normalise("aujourd’hui") == "aujourd'hui"
    assert spaced_letters_ratio("C O N T A C T") == 1.0
    assert spaced_letters_ratio("Contact") == 0.0
