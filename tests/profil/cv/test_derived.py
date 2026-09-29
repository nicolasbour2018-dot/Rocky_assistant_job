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
from rocky.profil.cv.derived import (
    TEMPLATE_FILE,
    _by_column,
    _continued,
    _title_line,
    derive,
    render_derived,
    slots_of,
    unspaced,
)
from rocky.profil.cv.importer import (
    IMPORTS,
    ImportedCv,
    ImportRefusedError,
    import_cv,
    read_proposals,
)
from rocky.profil.cv.pdf_page import (
    Block,
    Box,
    Line,
    PageLayout,
    Run,
    Style,
    read_page,
    render_page,
)
from rocky.profil.cv.proposals import preview_profile
from rocky.profil.cv.rendering import Photo
from rocky.profil.cv.semantics import BlockRole, Role, block_roles, prompt
from rocky.system.files import FileStore
from rocky.system.pdf_read import read_pdf
from rocky.system.render import compare, rasterize
from tests.profil.cv.fixtures import (
    PROFILE,
    ReaderModel,
    designed_cv,
    image_only_cv,
    scanned_cv,
)

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
    # Drawn as outlines, spaced like the design; read as words through their invisible text.
    assert "PROJECTS" in text
    assert "P R O J" not in text
    assert "PROJETS" not in text
    assert "Designed for responsible reading" in text


def test_french_titles_stay_in_the_layer_and_are_read_as_words(
    designed: bytes, tmp_path: Path
) -> None:
    files, proposals, _ = stored(tmp_path, imported(designed, tmp_path))

    document = render_derived(
        files, cv_content(preview_profile(proposals), "fr", TODAY), None
    )

    text = " ".join(read_pdf(document.pdf)[0].text.split())
    assert "PROJETS" in text
    assert "EXPÉRIENCES" in text
    assert "P R O J" not in text


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


def _layout(*lines: tuple[str, float]) -> PageLayout:
    style = Style("Poppins-Regular", 7.0, "#000000")
    blocks = tuple(
        Block(
            i,
            Box(10, y, 100, 8),
            (Line(Box(10, y, 100, 8), y + 7, (Run(text, style),), 0.0),),
        )
        for i, (text, y) in enumerate(lines)
    )
    return PageLayout(595, 842, blocks, (), "#ffffff")


def test_a_project_line_continues_the_part_whose_label_opens_above_it() -> None:
    layout = _layout(
        ("Problématique : Combiner des", 100),
        ("données sportives.", 110),
        ("Stack technique : Python,", 130),
        ("Projections d'effectifs", 140),
        ("comptables, automatisation", 150),
    )
    roles = [
        BlockRole(0, Role.PROJECT_PROBLEM, 1, "Problématique"),
        BlockRole(
            1, Role.PROJECT_PROBLEM, 1, "Problématique"
        ),  # the label repeated on a following line
        BlockRole(2, Role.PROJECT_STACK, 1, "Stack technique"),
        BlockRole(
            3, Role.PROJECT_NAME, 1
        ),  # a line of the stack taken for the project's name
        BlockRole(4, Role.PROJECT_PROBLEM, 1, "Problématique"),
    ]

    fixed = [role.role for role in _continued(layout, roles)]

    assert fixed == [
        Role.PROJECT_PROBLEM,
        Role.PROJECT_PROBLEM,
        Role.PROJECT_STACK,
        Role.PROJECT_STACK,
        Role.PROJECT_STACK,
    ]


def test_a_title_on_two_lines_is_translated_whole_then_spread_over_them() -> None:
    layout = _layout(("C O M P É T E N C E S", 100), ("T E C H N I Q U E S", 115))
    roles = [
        BlockRole(0, Role.HEADING, text_en="S K I L L S"),
        BlockRole(1, Role.HEADING),
    ]

    spread = [
        _title_line(role, layout, [((0, 1), "TECHNICAL SKILLS")]) for role in roles
    ]

    assert [role.text_en for role in spread] == ["TECHNICAL", "SKILLS"]
    spaced = _title_line(
        roles[0], layout, [((0, 1), "T E C H N I C A L   S K I L L S")]
    )
    assert spaced.text_en == "T E C H N I C A L"
    assert unspaced("T E C H N I C A L   S K I L L S") == "TECHNICAL SKILLS"


def test_the_photo_shows_its_round_frame_not_its_whole_image(
    designed: bytes, tmp_path: Path
) -> None:
    files, _, _ = stored(tmp_path, imported(designed, tmp_path))
    photo = json.loads(files[TEMPLATE_FILE])["photo"]

    # The fixture shows a 140 × 140 pt disc of a 140 × 170 pt image.
    assert photo["round"]
    assert abs(photo["visible"]["height"] - 140) < 3
    assert photo["image"]["height"] > photo["visible"]["height"] + 20


def test_a_page_that_is_one_picture_gives_no_template_but_its_proposals(
    tmp_path: Path,
) -> None:
    result = imported(scanned_cv(), tmp_path)

    assert result.template is None
    assert result.template_refusal is not None
    assert "image de page" in result.template_refusal
    proposals, _ = read_proposals(FileStore(tmp_path), 1, result.proposals.sha256)
    assert proposals["full_name"] == "Camille Martin"


def test_the_cv_carries_no_transparency_mask_that_some_readers_draw_black(
    designed: bytes, tmp_path: Path
) -> None:
    files, proposals, photo = stored(tmp_path, imported(designed, tmp_path))

    document = render_derived(
        files,
        cv_content(preview_profile(proposals), "fr", TODAY),
        Photo(photo or b"", "jpg"),
    )

    # The imported page has a transparent image; drawn through SVG, it gave soft masks that Apple's Preview drew as
    # black blocks. The layer is one opaque image now.
    assert b"/SMask" in designed
    assert b"/SMask" not in document.pdf


def test_a_kept_rubric_stays_as_the_imported_cv_wrote_it_in_french(
    designed: bytes, tmp_path: Path
) -> None:
    layout = read_page(designed)
    roles = block_roles(
        ReaderModel().complete_json("", prompt(layout.blocks), {}), layout.blocks
    )
    derived = derive(designed, layout, roles, "essai", kept=frozenset({Role.PHONE}))
    profile = preview_profile({**PROFILE, "phone": "07 11 11 11 11"})

    french = " ".join(
        read_pdf(
            render_derived(derived.files, cv_content(profile, "fr", TODAY), None).pdf
        )[0].text.split()
    )
    english = cv_content(profile, "en", TODAY)
    english_text = " ".join(
        read_pdf(render_derived(derived.files, replace(english, missing=()), None).pdf)[
            0
        ].text.split()
    )

    assert (
        "06 00 00 00 00" in french
    )  # kept: drawn by the layer, readable through its invisible words
    assert "07 11 11 11 11" not in french
    assert "07 11 11 11 11" in english_text  # the English CV takes it from the profile


def test_projects_are_numbered_by_their_column_whatever_the_model_says() -> None:
    style = Style("Poppins-Regular", 7.0, "#000000")

    def block(i: int, text: str, x: float, y: float) -> Block:
        box = Box(x, y, 90, 8)
        return Block(i, box, (Line(box, y + 7, (Run(text, style),), 0.0),))

    layout = PageLayout(
        595,
        842,
        (
            block(0, "Projet gauche", 10, 100),
            block(1, "Projet droite", 300, 100),
            block(2, "Problématique : à gauche", 10, 120),
            block(3, "Problématique : à droite", 300, 120),
        ),
        (),
        "#ffffff",
    )
    roles = [
        BlockRole(0, Role.PROJECT_NAME, 1),
        BlockRole(1, Role.PROJECT_NAME, 0),
        BlockRole(
            2, Role.PROJECT_PROBLEM, 0, "Problématique"
        ),  # the model's numbers are crossed
        BlockRole(3, Role.PROJECT_PROBLEM, 1, "Problématique"),
    ]

    assert [role.index for role in _by_column(layout, roles)] == [0, 1, 0, 1]


def test_a_title_translation_without_words_keeps_the_english_of_each_line() -> None:
    layout = _layout(("C O M P É T E N C E S", 100), ("T E C H N I Q U E S", 115))
    roles = [
        BlockRole(0, Role.HEADING, text_en="S K I L L S"),
        BlockRole(1, Role.HEADING, text_en="T E C H N I C A L"),
    ]
    glued = [
        ((0, 1), "S K I L L S T E C H N I C A L")
    ]  # one run of letters: no word to spread

    assert [_title_line(role, layout, glued).text_en for role in roles] == [
        "S K I L L S",
        "T E C H N I C A L",
    ]
