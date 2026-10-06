"""A template derived from an imported CV (decision D2, Q15–Q24, Q29–Q33), on a fictional designed CV made for the
test: only the skills and the projects follow the profile, everything else stays as the imported CV drew it."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import ImageFilter
from pypdf import PdfWriter

from rocky.profil.cv.check import Fact, check_cv
from rocky.profil.cv.content import cv_content
from rocky.profil.cv.derived import (
    OLD_FORMAT,
    TEMPLATE_FILE,
    _by_column,
    _continued,
    derived_facts,
    draw_derived,
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
from rocky.profil.cv.rendering import CvRefusedError
from rocky.profil.cv.semantics import BlockRole, Role
from rocky.profil.model import Profile, Text
from rocky.system.files import FileStore
from rocky.system.pdf_read import read_pdf
from rocky.system.render import compare, rasterize
from tests.profil.cv.fixtures import (
    LISTED_PROFILE,
    PROFILE,
    TODAY,
    ReaderModel,
    Shared,
    image_only_cv,
    imported,
    listed_cv,
    listed_reader,
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


def test_stacked_projects_are_numbered_from_the_top_whatever_the_model_says() -> None:
    """Step G5, Q3: cards stacked in one column were one project (their names overlap horizontally)."""
    layout = _layout(
        ("Projet du haut", 10, 100),
        ("Problème : en haut", 10, 112),
        ("suite du problème", 10, 122),  # right under a part: not a name
        ("Projet du bas", 10, 200),
        ("Problème : en bas", 10, 212),
    )
    roles = [
        BlockRole(0, Role.PROJECT_NAME, 1),
        BlockRole(1, Role.PROJECT_PROBLEM, 1, "Problème"),
        BlockRole(2, Role.PROJECT_NAME, 1),
        BlockRole(3, Role.PROJECT_NAME, 0),
        BlockRole(4, Role.PROJECT_PROBLEM, 0, "Problème"),
    ]

    assert [role.index for role in _by_column(layout, roles)] == [0, 0, 0, 1, 1]


def test_a_project_line_opening_with_another_part_label_is_that_part() -> None:
    """Step G5, Q3: « Stack : … » given the problem's label went into the problem."""
    layout = _layout(
        ("Problème : des milliers", 10, 100),
        ("Stack : Python, FastAPI", 10, 112),
        ("Stack : Pandas", 300, 112),
    )
    roles = [
        BlockRole(0, Role.PROJECT_PROBLEM, 0, "Problème"),
        BlockRole(1, Role.PROJECT_PROBLEM, 0, "Problème"),
        BlockRole(2, Role.PROJECT_STACK, 1, "Stack"),
    ]

    fixed = _continued(layout, roles)

    assert [(role.role, role.label) for role in fixed] == [
        (Role.PROJECT_PROBLEM, "Problème"),
        (Role.PROJECT_STACK, "Stack"),
        (Role.PROJECT_STACK, "Stack"),
    ]


def test_a_title_spaced_letter_by_letter_reads_as_words() -> None:
    assert unspaced("P R O J E T S") == "PROJETS"
    assert unspaced("T E C H N I C A L   S K I L L S") == "TECHNICAL SKILLS"
    assert unspaced("C   O   N   T") == "CONT"


# The room of a block (decision G5, Q2): its own lines, or the card drawn around it


def _region(template: dict[str, object], kind: str) -> dict[str, Any]:
    regions = template["regions"]
    assert isinstance(regions, list)
    return next(region for region in regions if region["kind"] == kind)


def _bottom(box: dict[str, float]) -> float:
    return box["y"] + box["height"]


def test_a_project_block_may_fill_its_drawn_card_and_no_more(shared: Shared) -> None:
    """Step G5: the room was the original lines plus one line, whatever the card drawn around them; a text could
    leave the card unreported (« Pilotage d'association sportive », D3)."""
    template = json.loads(shared.files()[TEMPLATE_FILE])
    body, name = _region(template, "project_body"), _region(template, "project_name")

    # The card of the fictional design: 200–370 × 330–490 pt, the text 15 pt from its left edge; its widest line
    # reaches 360.5 pt (a room never shrinks below the original lines).
    room = body["room"]
    assert 360 <= room["x"] + room["width"] <= 363
    assert 474 <= _bottom(room) <= 476
    # Never over the text below: the name's room stops above the ink of the body's first line.
    body_ink_top = body["room"]["y"] + 1 + (body["line_height"] - body["ink"]) / 2
    assert _bottom(name["room"]) <= body_ink_top


def test_a_block_without_a_card_has_no_line_of_air(shared: Shared) -> None:
    """Step G5: a block on the page itself takes its own lines only; one more line would touch what is below."""
    groups = _region(json.loads(shared.files()[TEMPLATE_FILE]), "groups")

    assert groups["room"]["height"] < (groups["count"] + 0.5) * groups["line_height"]


def test_a_project_text_beyond_its_card_is_named(shared: Shared) -> None:
    def reasons(problem: str) -> tuple[str, ...]:
        project = {
            "name": "Tri des messages clients",
            "problem": problem,
            "stack": ["Python"],
        }
        profile = preview_profile({**PROFILE, "projects": [project]})
        return draw_derived(shared.files(), cv_content(profile, "fr", TODAY))[2]

    assert reasons("Des milliers de messages clients à orienter chaque jour") == ()
    assert any(
        "carte du projet 1" in reason
        for reason in reasons("Des milliers de messages. " * 30)
    )


def test_a_template_of_an_older_format_asks_for_a_new_import(shared: Shared) -> None:
    """Step G5: rooms are measured anew (format 5); the model's kept answer remakes the template without a call."""
    files = dict(shared.files())
    template = json.loads(files[TEMPLATE_FILE])
    files[TEMPLATE_FILE] = json.dumps(
        {**template, "format": "rocky-cv-gabarit/4"}
    ).encode()

    with pytest.raises(CvRefusedError, match=OLD_FORMAT):
        draw_derived(
            files, cv_content(preview_profile(shared.proposals()), "fr", TODAY)
        )


# A second design (decision G5, Q3): one column, project cards stacked, read two ways by the model


@pytest.fixture(scope="module")
def listed_imports(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Mapping[str, bytes], Mapping[str, bytes]]:
    """The second design imported twice, read carefully then otherwise by the model."""
    pdf = listed_cv()
    bundles = []
    for otherwise in (False, True):
        root = tmp_path_factory.mktemp("listed")
        result = imported(pdf, root, listed_reader(otherwise=otherwise))
        assert result.template is not None, result.template_refusal
        bundles.append(
            FileStore(root).read_bundle(result.template.path, result.template.sha256)
        )
    return bundles[0], bundles[1]


def test_two_readings_of_a_second_design_give_the_same_blocks(
    listed_imports: tuple[Mapping[str, bytes], Mapping[str, bytes]],
) -> None:
    """Step G5: the rules after the model (numbers by geometry, lines that continue a part) were set on one design,
    project cards side by side."""
    careful, otherwise = (json.loads(files[TEMPLATE_FILE]) for files in listed_imports)

    assert careful["regions"] == otherwise["regions"]
    bodies = [r for r in careful["regions"] if r["kind"] == "project_body"]
    assert [[part["role"] for part in body["parts"]] for body in bodies] == [
        ["project_problem", "project_stack", "project_results"]
    ] * 2
    assert [body["count"] for body in bodies] == [
        4,
        3,
    ]  # the problem's second line kept
    assert slots_of(careful).projects == 2


def test_each_design_writes_its_skills_its_own_way(
    shared: Shared,
    listed_imports: tuple[Mapping[str, bytes], Mapping[str, bytes]],
) -> None:
    """Step G5, Q3: a group's name on its own line and one soft skill per line was the only way (Nicolas's Canva)."""
    first = json.loads(shared.files()[TEMPLATE_FILE])
    second = json.loads(listed_imports[0][TEMPLATE_FILE])

    assert _region(first, "groups")["inline"] is False
    assert _region(first, "transversal")["separator"] is None
    assert _region(second, "groups")["inline"] is True
    assert _region(second, "transversal")["separator"] == " · "


def test_a_second_design_renders_each_project_in_its_own_card(
    listed_imports: tuple[Mapping[str, bytes], Mapping[str, bytes]],
) -> None:
    content = cv_content(preview_profile(LISTED_PROFILE), "fr", TODAY)

    texts = []
    for files in listed_imports:
        rendered, _, reasons = draw_derived(files, content)
        assert reasons == ()
        texts.append(text_of(rendered.pdf))

    assert texts[0] == texts[1]
    # Names keep the design's colon; skills are written on one line, as the design does.
    for expected in (
        "Prévision des stocks :",
        "Tri des messages :",
        "Résultats : 30 % de ruptures en moins.",
        "Langages : Python, SQL",
        "Rigueur · Écoute",
    ):
        assert expected in texts[0]
    # Each project stays in its own card (300–400 and 415–515 pt), the first one on top.
    template = json.loads(listed_imports[0][TEMPLATE_FILE])
    for region in template["regions"]:
        if region["kind"].startswith("project"):
            top = 300 + 115 * region["index"]
            assert top < region["room"]["y"] < _bottom(region["room"]) < top + 100
