"""A template derived from an imported CV (decision D2, Q15–Q24, Q29–Q33), on a fictional designed CV made for the
test: only the skills and the projects follow the profile, everything else stays as the imported CV drew it."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import ImageFilter
from pypdf import PdfWriter

from rocky.profil.cv.check import Fact, check_cv
from rocky.profil.cv.content import cv_content
from rocky.profil.cv.derived import (
    TEMPLATE_FILE,
    _by_column,
    _continued,
    derived_facts,
    render_derived,
    slots_of,
    unspaced,
)
from rocky.profil.cv.importer import (
    IMPORTS,
    ImportRefusedError,
    import_language,
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
from rocky.profil.cv.semantics import BlockRole, Role
from rocky.profil.model import Profile, Text
from rocky.system.files import FileStore
from rocky.system.pdf_read import read_pdf
from rocky.system.render import compare, rasterize
from tests.profil.cv.fixtures import (
    PROFILE,
    TODAY,
    ReaderModel,
    Shared,
    image_only_cv,
    imported,
    scanned_cv,
)


def text_of(pdf: bytes) -> str:
    return " ".join(read_pdf(pdf)[0].text.split())


def test_only_skills_and_projects_become_regions(shared: Shared) -> None:
    template = json.loads(shared.files()[TEMPLATE_FILE])

    assert shared.result.template_refusal is None
    assert shared.result.warnings == ()
    assert {region["kind"] for region in template["regions"]} == {
        "groups",
        "transversal",
        "project_name",
        "project_body",
    }
    (body,) = [r for r in template["regions"] if r["kind"] == "project_body"]
    assert [part["role"] for part in body["parts"]] == [
        "project_problem",
        "project_stack",
    ]
    assert (
        body["parts"][1]["gap"] > 0
    )  # the space the design left between the two parts
    assert slots_of(template).projects == 1
    assert template["language"] == "fr"


def test_the_design_and_the_kept_texts_stay_outside_the_variable_blocks(
    designed: bytes, shared: Shared
) -> None:
    files = shared.files()
    template = json.loads(files[TEMPLATE_FILE])
    document = render_derived(
        files, cv_content(preview_profile(shared.proposals()), "fr", TODAY)
    )

    original = render_page(designed, 72).filter(ImageFilter.GaussianBlur(1))
    reproduced = (
        rasterize(document.pdf, 72)[0]
        .resize(original.size)
        .filter(ImageFilter.GaussianBlur(1))
    )
    mask = [
        (
            int(r["room"]["x"]),
            int(r["room"]["y"]),
            int(r["room"]["x"] + r["room"]["width"]) + 1,
            int(r["room"]["y"] + r["room"]["height"]) + 1,
        )
        for r in template["regions"]
    ]
    outside = compare(original, reproduced, mask=mask, threshold=48)
    # Name, photo, contact, headline, titles, experiences and footer are the imported page itself.
    assert outside.ratio < 0.003, f"{outside.changed_pixels} pixels differ"


def test_the_profile_fills_the_variable_blocks_and_nothing_else(shared: Shared) -> None:
    profile = preview_profile(
        {
            **PROFILE,
            "phone": "07 11 11 11 11",  # the kept phone of the CV does not follow the profile
            "transversal": ["Écoute"],
            "projects": [
                {
                    "name": "Prévision des stocks",
                    "problem": "Ruptures",
                    "stack": ["Pandas"],
                }
            ],
        }
    )

    text = text_of(render_derived(shared.files(), cv_content(profile, "fr", TODAY)).pdf)

    assert "Prévision des stocks" in text
    assert "Stack technique : Pandas" in text
    assert "Écoute" in text
    assert "Tri des messages clients" not in text
    assert "06 00 00 00 00" in text  # kept, as invisible words over the layer
    assert "07 11 11 11 11" not in text


def test_the_whole_cv_is_read_as_words_by_every_reader(shared: Shared) -> None:
    files = shared.files()
    content = cv_content(preview_profile(shared.proposals()), "fr", TODAY)
    facts = derived_facts(files, content)
    document = render_derived(files, content)

    check = check_cv(document.pdf, facts)

    assert Fact("Section", "PROJETS") in facts  # « P R O J E T S » read as a word
    assert Fact("Nom", "CAMILLE MARTIN") in facts
    assert check.readable, check.warnings
    assert "Prévision de la demande par entrepôt." in text_of(document.pdf)


def _in_english(profile: Profile) -> Profile:
    """The variable blocks written in English; the experiences left French: this template never shows them."""
    return replace(
        profile,
        skills=tuple(
            replace(s, content=replace(s.content, label=Text(s.label.fr, s.label.fr)))
            for s in profile.skills
        ),
        cv=replace(
            profile.cv,
            groups=tuple(
                replace(g, name=Text(g.name.fr, "Languages")) for g in profile.cv.groups
            ),
        ),
        projects=tuple(
            replace(
                p,
                content=replace(
                    p.content,
                    name=Text(p.content.name.fr, "Message triage"),
                    problem=Text(p.content.problem.fr, "Thousands of messages"),
                    stack_en=p.content.stack,
                ),
            )
            for p in profile.projects
        ),
    )


def test_an_english_cv_asks_english_only_for_the_variable_blocks(
    designed: bytes, tmp_path: Path
) -> None:
    result = imported(designed, tmp_path, language="en")
    assert result.template is not None
    assert import_language(FileStore(tmp_path), 1, result.proposals.sha256) == "en"
    files = FileStore(tmp_path).read_bundle(
        result.template.path, result.template.sha256
    )
    content = cv_content(_in_english(preview_profile(PROFILE)), "en", TODAY)
    assert content.missing  # the experiences have no English

    text = text_of(render_derived(files, content).pdf)

    assert "Message triage" in text
    assert (
        "Stack technique: Python, Docker" in text
    )  # the label as the CV wrote it, English colon


def test_a_pdf_made_of_an_image_is_refused_with_its_reason(tmp_path: Path) -> None:
    with pytest.raises(ImportRefusedError, match="pas de texte lisible"):
        imported(image_only_cv(), tmp_path)


def test_a_page_that_is_one_picture_gives_no_template_but_its_proposals(
    tmp_path: Path,
) -> None:
    result = imported(scanned_cv(), tmp_path)

    assert result.template is None
    assert result.template_refusal is not None
    assert "image de page" in result.template_refusal
    proposals, _ = read_proposals(FileStore(tmp_path), 1, result.proposals.sha256)
    assert proposals["full_name"] == "Camille Martin"


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
    designed: bytes, shared: Shared
) -> None:
    (prompt,) = shared.model.prompts

    assert "CAMILLE MARTIN" in prompt
    assert "%PDF" not in prompt
    assert prompt.count("\n[") == len(read_page(designed).blocks)


def test_the_cv_carries_no_transparency_mask_that_some_readers_draw_black(
    designed: bytes, shared: Shared
) -> None:
    document = render_derived(
        shared.files(), cv_content(preview_profile(shared.proposals()), "fr", TODAY)
    )

    # The imported page has a transparent image; drawn through SVG, it gave soft masks that Apple's Preview drew
    # as black blocks. The layer is one opaque image.
    assert b"/SMask" in designed
    assert b"/SMask" not in document.pdf


def _layout(*lines: tuple[str, float, float]) -> PageLayout:
    style = Style("Poppins-Regular", 7.0, "#000000")
    blocks = tuple(
        Block(
            i,
            Box(x, y, 90, 8),
            (Line(Box(x, y, 90, 8), y + 7, (Run(text, style),), 0.0),),
        )
        for i, (text, x, y) in enumerate(lines)
    )
    return PageLayout(595, 842, blocks, (), "#ffffff")


def test_a_project_line_continues_the_part_whose_label_opens_above_it() -> None:
    layout = _layout(
        ("Problématique : Combiner des", 10, 100),
        ("données sportives.", 10, 110),
        ("Stack technique : Python,", 10, 130),
        ("Projections d'effectifs", 10, 140),
        ("comptables, automatisation", 10, 150),
    )
    roles = [
        BlockRole(0, Role.PROJECT_PROBLEM, 1, "Problématique"),
        BlockRole(1, Role.PROJECT_PROBLEM, 1, "Problématique"),  # label repeated below
        BlockRole(2, Role.PROJECT_STACK, 1, "Stack technique"),
        BlockRole(3, Role.PROJECT_NAME, 1),  # a line of the stack taken for the name
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


def test_projects_are_numbered_by_their_column_whatever_the_model_says() -> None:
    layout = _layout(
        ("Projet gauche", 10, 100),
        ("Projet droite", 300, 100),
        ("Problématique : à gauche", 10, 120),
        ("Problématique : à droite", 300, 120),
    )
    roles = [
        BlockRole(0, Role.PROJECT_NAME, 1),
        BlockRole(1, Role.PROJECT_NAME, 0),
        BlockRole(2, Role.PROJECT_PROBLEM, 0, "Problématique"),  # numbers crossed
        BlockRole(3, Role.PROJECT_PROBLEM, 1, "Problématique"),
    ]

    assert [role.index for role in _by_column(layout, roles)] == [0, 1, 0, 1]


def test_a_title_spaced_letter_by_letter_reads_as_words() -> None:
    assert unspaced("P R O J E T S") == "PROJETS"
    assert unspaced("T E C H N I C A L   S K I L L S") == "TECHNICAL SKILLS"
    assert unspaced("C   O   N   T") == "CONT"
