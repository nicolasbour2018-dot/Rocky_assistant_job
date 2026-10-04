"""The texts of an imported CV cut into units, the pieces its English version translates and places (decision D3,
Q20): a list stays a list, a wrapped line stays in its paragraph, a title on two lines is one title. Lines laid out
like those of a design tool's export, one block per line (fictional texts)."""

from __future__ import annotations

from typing import Any

from rocky.profil.cv.derived import _heading_html, _units, title_lines
from rocky.profil.cv.pdf_page import Block, Box, Line, Run, Style
from rocky.profil.cv.semantics import BlockRole, Role

SIZE = 9.0


def line(x: float, baseline: float, width: float, *runs: tuple[str, bool]) -> Line:
    styles = {
        bold: Style("Poppins-Bold" if bold else "Poppins-Regular", SIZE, "#222222")
        for bold in (True, False)
    }
    return Line(
        Box(x, baseline - SIZE * 0.75, width, SIZE * 0.8),
        baseline,
        tuple(Run(text, styles[bold]) for text, bold in runs),
        0.0,
    )


def units(role: Role, *lines: Line) -> list[dict[str, Any]]:
    kept = [
        (BlockRole(index, role), Block(index, item.box, (item,)))
        for index, item in enumerate(lines)
    ]
    return _units(kept)


def texts(found: list[dict[str, Any]]) -> list[str]:
    return [unit["text"] for unit in found]


def test_lines_opening_in_bold_one_after_another_are_items_of_a_list() -> None:
    found = units(
        Role.LANGUAGES,
        line(20, 560, 140, ("Allemand", True), (" (langue maternelle)", False)),
        line(20, 576, 126, ("Italien", True), (" (écrit et parlé) - C1", False)),
        line(20, 592, 135, ("Portugais", True), (" (écrit et parlé) - B2", False)),
    )

    assert texts(found) == [
        "**Allemand** (langue maternelle)",
        "**Italien** (écrit et parlé) - C1",
        "**Portugais** (écrit et parlé) - B2",
    ]


def test_a_bold_opening_after_a_sentence_starts_a_new_item() -> None:
    found = units(
        Role.EXPERIENCES,
        line(200, 500, 190, ("Pilotage :", True), (" suivi des budgets et des", False)),
        line(200, 512, 188, ("livrables de bout en bout (séjours).", False)),
        line(
            200, 524, 190, ("Restitution :", True), (" des indicateurs simples", False)
        ),
    )

    assert texts(found) == [
        "**Pilotage :** suivi des budgets et des livrables de bout en bout (séjours).",
        "**Restitution :** des indicateurs simples",
    ]


def test_a_bold_word_wrapped_in_the_middle_of_a_sentence_stays_in_its_paragraph() -> (
    None
):
    found = units(
        Role.HEADLINE,
        line(
            300, 20, 270, ("Profil varié", True), (", mon parcours associe la", False)
        ),
        line(300, 33, 252, ("recherche et le terrain afin de concevoir des", False)),
        line(
            300, 46, 240, ("méthodes claires", True), (" et des plans concrets.", False)
        ),
    )

    assert len(found) == 1


def test_a_short_line_is_wrapped_when_the_next_word_would_not_fit_at_its_end() -> None:
    found = units(
        Role.EXPERIENCES,
        line(200, 700, 190, ("Analyse des mesures recueillies chaque jour", False)),
        line(200, 712, 150, ("Traitement des données", False)),
        line(200, 724, 192, ("expérimentales, gestion des biais et lecture", False)),
    )

    assert len(found) == 1


def test_a_change_of_indent_starts_a_new_unit() -> None:
    found = units(
        Role.EXPERIENCES,
        line(
            188,
            740,
            180,
            ("-", True),
            (" Hôpital Exemple / Université", False),
            (" -", True),
        ),
        line(200, 752, 160, ("Analyse statistique des essais", False)),
    )

    assert texts(found) == [
        "**-** Hôpital Exemple / Université **-**",
        "Analyse statistique des essais",
    ]


def test_a_title_on_two_lines_is_one_title_keeping_each_line_in_its_place() -> None:
    found = units(
        Role.HEADING,
        line(28, 357, 128, ("COMPÉTENCES", False)),
        line(27, 376, 130, ("TECHNIQUES", False)),
        line(28, 545, 90, ("LANGUES", False)),
    )

    first, languages = found
    assert first["text"] == "COMPÉTENCES TECHNIQUES"
    assert [part["text"] for part in first["lines"]] == ["COMPÉTENCES", "TECHNIQUES"]
    assert languages["text"] == "LANGUES"
    drawn = _heading_html(first, "TECHNICAL SKILLS")
    assert drawn.count("<svg") == 2
    assert ">TECHNICAL SKILLS</div>" in drawn  # one line for PDF readers


def test_a_translated_title_is_cut_over_the_lines_of_the_french_one() -> None:
    assert title_lines("SOFT SKILLS", ["COMPÉTENCES", "TRANSVERSALES"]) == [
        "SOFT",
        "SKILLS",
    ]
    assert title_lines("SKILLS", ["COMPÉTENCES", "TECHNIQUES"]) == ["SKILLS", ""]
    assert title_lines("WORK EXPERIENCE", ["EXPÉRIENCES"]) == ["WORK EXPERIENCE"]
