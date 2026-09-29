"""A template derived from an imported CV (decision D2, Q15–Q24), on a fictional designed CV made for the test."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from PIL import ImageFilter
from pypdf import PdfWriter

from rocky.profil.cv.content import cv_content
from rocky.profil.cv.derived import TEMPLATE_FILE, render_derived, slots_of
from rocky.profil.cv.importer import (
    IMPORTS,
    ImportedCv,
    ImportRefusedError,
    import_cv,
    read_proposals,
)
from rocky.profil.cv.pdf_page import read_page, render_page
from rocky.profil.cv.proposals import preview_profile
from rocky.profil.cv.rendering import Photo
from rocky.system.files import FileStore
from rocky.system.pdf_read import read_pdf
from rocky.system.render import compare, rasterize
from tests.profil.cv.fixtures import ReaderModel, designed_cv, image_only_cv

TODAY = date(2026, 9, 29)


@pytest.fixture(scope="module")
def designed() -> bytes:
    return designed_cv()


def imported(pdf: bytes, root: Path, model: ReaderModel | None = None) -> ImportedCv:
    return import_cv(
        pdf,
        model=model or ReaderModel(),
        files=FileStore(root),
        account_id=1,
        today=TODAY,
    )


def stored(
    root: Path, result: ImportedCv
) -> tuple[Mapping[str, bytes], Mapping[str, Any], bytes | None]:
    """The template files, the proposals and the photo of an import."""
    assert result.template is not None
    files = FileStore(root).read_bundle(result.template.path, result.template.sha256)
    proposals, photo = read_proposals(FileStore(root), 1, result.proposals.sha256)
    return files, proposals, photo


def test_the_template_reproduces_the_design_outside_its_text_regions(
    designed: bytes, tmp_path: Path
) -> None:
    result = imported(designed, tmp_path)

    assert result.template_refusal is None
    assert result.warnings == ()
    assert result.preview is not None
    files, proposals, photo = stored(tmp_path, result)
    template = json.loads(files[TEMPLATE_FILE])
    assert {region["role"] for region in template["regions"]} == {
        "name",
        "title",
        "headline",
        "email",
        "phone",
        "project_name",
        "project_problem",
        "experiences",
    }
    assert template["photo"]["round"]
    assert slots_of(template).projects == 1
    assert photo is not None

    content = cv_content(preview_profile(proposals), "fr", TODAY)
    document = render_derived(files, content, Photo(photo, "jpg"))

    original = render_page(designed, 72).filter(ImageFilter.GaussianBlur(1))
    reproduced = (
        rasterize(document.pdf, 72)[0]
        .resize(original.size)
        .filter(ImageFilter.GaussianBlur(1))
    )
    mask = [
        (
            int(r["box"]["x"]),
            int(r["box"]["y"]),
            int(r["box"]["x"] + r["box"]["width"]) + 1,
            int(r["box"]["y"] + r["box"]["height"]) + 1,
        )
        for r in template["regions"]
    ]
    outside = compare(original, reproduced, mask=mask, threshold=48)
    assert outside.ratio < 0.003, (
        f"{outside.changed_pixels} pixels differ outside the text regions"
    )


def test_the_english_cv_writes_the_translated_titles_again(
    designed: bytes, tmp_path: Path
) -> None:
    files, proposals, _ = stored(tmp_path, imported(designed, tmp_path))
    english = cv_content(preview_profile(proposals), "en", TODAY)
    assert (
        english.missing
    )  # the preview profile holds French texts only: pretend they are translated

    document = render_derived(files, replace(english, missing=()), None)

    text = " ".join(read_pdf(document.pdf)[0].text.split())
    assert "P R O J E C T S" in text
    assert "P R O J E T S" not in text
    assert "Designed for responsible reading" in text


def test_a_pdf_made_of_an_image_is_refused_with_its_reason(tmp_path: Path) -> None:
    with pytest.raises(ImportRefusedError, match="pas de texte lisible"):
        imported(image_only_cv(), tmp_path)


def test_a_cv_of_two_pages_is_refused(designed: bytes, tmp_path: Path) -> None:
    writer = PdfWriter()
    for _ in range(2):
        writer.append(io.BytesIO(designed))
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(ImportRefusedError, match="2 pages"):
        imported(buffer.getvalue(), tmp_path)


def test_lines_left_without_rubric_refuse_the_template_but_keep_the_proposals(
    designed: bytes, tmp_path: Path
) -> None:
    result = imported(designed, tmp_path, ReaderModel(skip=2))

    assert result.template is None
    assert result.template_refusal is not None
    assert "rattachés" in result.template_refusal
    assert (tmp_path / f"comptes/1/{IMPORTS}/{result.proposals.sha256}").is_dir()


def test_only_the_texts_reach_the_model_never_the_file(
    designed: bytes, tmp_path: Path
) -> None:
    model = ReaderModel()

    imported(designed, tmp_path, model)

    (prompt,) = model.prompts
    assert "CAMILLE MARTIN" in prompt
    assert "%PDF" not in prompt
    assert prompt.count("\n[") == len(read_page(designed).blocks)
