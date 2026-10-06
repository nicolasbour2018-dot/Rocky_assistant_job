"""The neutral CV rendered for real (headless Chromium): stable, one page, refused rather than wrong (D2, Q6, Q13);
a paragraph longer than its limit is cut, and the cut named (G5, Q1).

The reference images show a fictional profile (public repository) as rendered on Linux, where the verification and
the application run. They change only on purpose, rendered in the check container, then looked at:

    docker compose run --rm -e ROCKY_REGENERATE_CV_REFERENCES=1 \\
      -v ./tests/profil/cv/reference:/app/tests/profil/cv/reference check pytest tests/profil/cv/test_rendering.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from rocky.profil.cv.content import (
    CvContent,
    CvEntry,
    CvProject,
    Span,
    cv_content,
    paragraphs,
)
from rocky.profil.cv.rendering import (
    ELLIPSIS,
    NEUTRAL_LIMITS,
    CvRefusedError,
    fit_neutral,
    neutral_html,
    render_neutral,
    shortened,
)
from rocky.system.pdf_read import read_pdf
from rocky.system.render import compare, rasterize
from tests.profil.cv.sample import TODAY, sample_profile

REFERENCES = Path(__file__).parent / "reference"
DPI = 60
# Strict where the reference was made; on a Mac (quick local loop), anti-aliasing and sub-pixel placement differ
# by about 0.5 % of the page, so only a gross change fails there.
MAX_CHANGED_RATIO = 0.0005 if sys.platform == "linux" else 0.01


@pytest.mark.parametrize("language", ["fr", "en"])
def test_the_neutral_cv_matches_its_reference(language: str) -> None:
    document = render_neutral(cv_content(sample_profile(), language, TODAY), None)
    image = rasterize(document.pdf, DPI)[0]
    reference = REFERENCES / f"neutre-{language}.png"

    if os.environ.get("ROCKY_REGENERATE_CV_REFERENCES") == "1":
        reference.parent.mkdir(exist_ok=True)
        image.save(reference, optimize=True)
    difference = compare(Image.open(reference), image)

    assert difference.ratio <= MAX_CHANGED_RATIO, (
        f"{difference.changed_pixels} pixels changed"
    )


def test_the_same_content_gives_the_same_html() -> None:
    content = cv_content(sample_profile(), "fr", TODAY)

    assert neutral_html(content, with_photo=False) == neutral_html(
        content, with_photo=False
    )
    assert (
        render_neutral(content, None).html_sha256
        == render_neutral(content, None).html_sha256
    )


def test_every_reader_finds_the_cv_texts() -> None:
    document = render_neutral(cv_content(sample_profile(), "fr", TODAY), None)

    for reading in read_pdf(document.pdf):
        text = " ".join(reading.text.split())
        for expected in (
            "CAMILLE MARTIN",
            "camille.martin@example.org",
            "Tri des messages clients",
            "Pédagogie",
        ):
            assert expected in text, f"{reading.reader} misses {expected!r}"


def test_an_overflowing_column_is_refused_by_name() -> None:
    """No paragraph is too long, but there are too many of them: nothing is removed, the CV is refused (Q6, Q10)."""
    content = cv_content(sample_profile(), "fr", TODAY)
    content = replace(content, experiences=content.experiences * 8)

    with pytest.raises(CvRefusedError, match="colonne principale"):
        render_neutral(content, None)


# Limits of the neutral template (decision G5, Q1)

SENTENCE = (
    "Conception et mise en production d'un modèle de prévision de la demande pour les "
    "entrepôts régionaux, avec suivi des écarts, tableaux de bord partagés et alertes "
    "hebdomadaires aux équipes d'exploitation. "
)


def _text_of(length: int) -> str:
    """A French text of exactly ``length`` characters, ending a sentence."""
    return (SENTENCE * 4)[: length - 1].rstrip().ljust(length - 1, "x") + "."


def long_career(language: str) -> CvContent:
    """The career the limits are set for, every paragraph at its limit: 3 jobs of 3 bullets, 4 trainings of 2
    bullets, 3 projects, a headline (the shape of Nicolas's profile, with room)."""
    limits = NEUTRAL_LIMITS
    job = CvEntry(
        "2019 – 2022",
        "Responsable des opérations logistiques",
        "Entreprise Exemple",
        "Lyon",
        tuple(_text_of(limits.job_bullet) for _ in range(3)),
    )
    training = CvEntry(
        "2018",
        "Master Science des données appliquée",
        "Université Exemple",
        "Paris",
        tuple(_text_of(limits.education_bullet) for _ in range(2)),
    )
    project = CvProject(
        "Prévision de la demande",
        _text_of(limits.project_part),
        _text_of(limits.project_part),
        "",
        ("Python", "Pandas", "Scikit-learn", "SQL", "Docker", "FastAPI"),
    )
    return replace(
        cv_content(sample_profile(), language, TODAY),
        headline=paragraphs(_text_of(limits.headline)),
        experiences=(job,) * 3,
        education=(training,) * 4,
        projects=(project,) * 3,
    )


@pytest.mark.parametrize("language", ["fr", "en"])
def test_a_long_career_at_the_limits_holds_one_page_uncut(language: str) -> None:
    """Step G5: Nicolas's career overflowed the neutral template by 77 mm in English."""
    content = long_career(language)

    document = render_neutral(content, None)

    assert document.notices == ()
    assert fit_neutral(content) == (content, ())


def test_a_paragraph_beyond_its_limit_is_cut_and_named() -> None:
    content = long_career("fr")
    job = content.experiences[0]
    longer = replace(
        job, bullets=(job.bullets[0] + " Et un peu plus.", *job.bullets[1:])
    )
    content = replace(content, experiences=(longer, *content.experiences[1:]))

    fitted, cuts = fit_neutral(content)

    bullet = fitted.experiences[0].bullets[0]
    assert len(bullet) <= NEUTRAL_LIMITS.job_bullet and bullet.endswith(ELLIPSIS)
    assert cuts == (
        (
            "Expérience « Responsable des opérations logistiques », puce 1 : "
            "coupé à 140 caractères."
        ),
    )
    document = render_neutral(content, None)
    assert document.notices == cuts
    assert bullet in " ".join(read_pdf(document.pdf)[0].text.split())


def test_a_text_is_cut_after_a_whole_word() -> None:
    assert shortened("Données opérationnelles", 30) is None
    assert shortened("Données opérationnelles du quotidien", 20) == "Données…"
    assert shortened("Données, opérationnelles", 12) == "Données…"


def test_a_long_headline_keeps_its_bold_and_drops_the_paragraphs_beyond() -> None:
    content = cv_content(sample_profile(), "fr", TODAY)
    headline = (
        (Span("Data scientist issue de la "), Span("logistique", bold=True)),
        (Span(_text_of(NEUTRAL_LIMITS.headline)),),
        (Span("Un troisième paragraphe."),),
    )

    fitted, cuts = fit_neutral(replace(content, headline=headline))

    first, second = fitted.headline
    assert first == headline[0]
    assert second[-1] == Span(ELLIPSIS)
    assert sum(
        len(span.text) for paragraph in fitted.headline for span in paragraph
    ) <= (NEUTRAL_LIMITS.headline)
    assert cuts == ("Accroche : coupée à 300 caractères.",)


def test_an_english_cv_with_french_texts_is_refused_before_rendering() -> None:
    with pytest.raises(CvRefusedError, match="puces"):
        render_neutral(cv_content(sample_profile(english=False), "en", TODAY), None)
