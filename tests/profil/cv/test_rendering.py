"""The neutral CV rendered for real (headless Chromium): stable, one page, refused rather than wrong (D2, Q6, Q13).

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

from rocky.profil.cv.content import cv_content
from rocky.profil.cv.rendering import CvRefusedError, neutral_html, render_neutral
from rocky.profil.model import Text
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
    profile = sample_profile()
    long_headline = Text("Une phrase qui revient encore et encore. " * 120)
    profile = replace(
        profile, identity=replace(profile.identity, headline=long_headline)
    )

    with pytest.raises(CvRefusedError, match="colonne principale"):
        render_neutral(cv_content(profile, "fr", TODAY), None)


def test_an_english_cv_with_french_texts_is_refused_before_rendering() -> None:
    with pytest.raises(CvRefusedError, match="puces"):
        render_neutral(cv_content(sample_profile(english=False), "en", TODAY), None)
