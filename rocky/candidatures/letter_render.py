"""An application's letter as a PDF (decision D4, Q5, Q10): one A4 page, rendered by ``system.render``.

A letter is refused, with its reasons, rather than delivered wrong: a text overflowing the page, a second page, a
font that did not load. Nothing is shrunk to fit: the user shortens a paragraph.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from rocky.candidatures.letter import LetterSheet
from rocky.profil.cv.library import font_assets, font_faces
from rocky.profil.cv.rendering import PX_TO_MM
from rocky.system.render import Rendered, render_pdf

LETTER_DIR = Path(__file__).parent / "letter_pdf"
SUBJECT_LABELS = {"fr": "Objet :", "en": "Subject:"}

_environment = Environment(
    loader=FileSystemLoader(LETTER_DIR),
    autoescape=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


class LetterRefusedError(Exception):
    """The letter cannot be delivered as it is; ``reasons`` are shown as they are (French)."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


def letter_html(sheet: LetterSheet) -> str:
    return _environment.get_template("letter.html").render(
        sheet=sheet,
        subject_label=SUBJECT_LABELS[sheet.language],
        font_faces=Markup(font_faces()),
    )


def letter_fingerprint(sheet: LetterSheet) -> str:
    """What the PDF of the letter is made from, its date aside (decision D5): a revision is stale once this changes;
    the date it carries is frozen with it."""
    return hashlib.sha256(
        letter_html(replace(sheet, place_date="")).encode()
    ).hexdigest()


def draw_letter(sheet: LetterSheet) -> tuple[bytes, tuple[str, ...]]:
    """The PDF of the letter as it comes, and what makes it unfit (the preview shows both); raises ``RenderError``
    when the browser fails."""
    rendered = render_pdf(letter_html(sheet), font_assets())
    return rendered.pdf, problems(rendered)


def render_letter(sheet: LetterSheet) -> bytes:
    """The PDF of the letter; raises ``LetterRefusedError`` (or ``RenderError`` when the browser fails)."""
    pdf, reasons = draw_letter(sheet)
    if reasons:
        raise LetterRefusedError(reasons)
    return pdf


def problems(rendered: Rendered) -> tuple[str, ...]:
    found = [
        f"La lettre dépasse sa page d'environ "
        f"{max(overflow.extra_height_px, overflow.extra_width_px) * PX_TO_MM:.0f} mm : raccourcis un paragraphe."
        for overflow in rendered.overflows
        if overflow.box != "page"
    ]
    if rendered.page_count != 1:
        found.append(f"La lettre fait {rendered.page_count} pages au lieu d'une.")
    if rendered.missing_fonts:
        found.append("Police non chargée : " + ", ".join(rendered.missing_fonts) + ".")
    if rendered.refused_requests:
        found.append(
            "La lettre demande un fichier absent : "
            + ", ".join(rendered.refused_requests)
            + "."
        )
    return tuple(found)
