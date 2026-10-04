"""A CV as a PDF: its content in a template, rendered by ``system.render`` (decision D2, Q6, Q11, Q13).

A CV is refused, with its reasons, rather than delivered wrong: English texts missing, a box overflowing, a second
page, a font that did not load. The hash of the rendered HTML identifies a rendering: the same content in the same
template gives the same hash (the PDF bytes themselves carry a creation date).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from rocky.profil.cv.content import CvContent
from rocky.profil.cv.library import font_assets, font_faces
from rocky.system.render import Rendered, render_pdf

NEUTRAL_DIR = Path(__file__).parent / "neutral"
PX_TO_MM = 25.4 / 96

LABELS = {
    "fr": {
        "contact": "Contact",
        "technical": "Compétences techniques",
        "transversal": "Compétences transversales",
        "languages": "Langues",
        "hobbies": "Loisirs",
        "experiences": "Expériences",
        "projects": "Projets",
        "education": "Formations",
        "problem": "Problème",
        "stack": "Stack",
        "work": "Réalisation",
        "results": "Résultats",
    },
    "en": {
        "contact": "Contact",
        "technical": "Technical skills",
        "transversal": "Soft skills",
        "languages": "Languages",
        "hobbies": "Interests",
        "experiences": "Experience",
        "projects": "Projects",
        "education": "Education",
        "problem": "Problem",
        "stack": "Stack",
        "work": "What I built",
        "results": "Results",
    },
}

_environment = Environment(
    loader=FileSystemLoader(NEUTRAL_DIR),
    autoescape=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


class CvRefusedError(Exception):
    """The CV cannot be delivered as it is; ``reasons`` are shown as they are (French)."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Photo:
    content: bytes
    suffix: str  # jpg, png, webp


@dataclass(frozen=True)
class CvPdf:
    pdf: bytes
    html_sha256: str
    template: str


def neutral_html(content: CvContent, *, with_photo: bool, suffix: str = "jpg") -> str:
    return _environment.get_template("cv.html").render(
        cv=content,
        labels=LABELS[content.language],
        font_faces=Markup(font_faces()),
        photo=f"photo.{suffix}" if with_photo else None,
    )


def neutral_headings(content: CvContent) -> tuple[str, ...]:
    """Section headings the neutral template writes for this content (checked by « Vérifier mon CV »)."""
    labels = LABELS[content.language]
    present = {
        "contact": True,
        "technical": bool(content.groups),
        "transversal": bool(content.transversal),
        "languages": bool(content.languages),
        "hobbies": bool(content.hobbies),
        "experiences": bool(content.experiences),
        "projects": bool(content.projects),
        "education": bool(content.education),
    }
    return tuple(labels[key] for key, shown in present.items() if shown)


# How a refusal for English still missing begins: the screens offer the translation after it (decision D3, Q5).
MISSING_ENGLISH = "Le CV anglais attend encore ces textes en anglais (profil) : "


def render_neutral(content: CvContent, photo: Photo | None) -> CvPdf:
    rendered, html, reasons = draw_neutral(content, photo)
    if reasons:
        raise CvRefusedError(reasons)
    return CvPdf(
        pdf=rendered.pdf,
        html_sha256=hashlib.sha256(html.encode()).hexdigest(),
        template="neutre",
    )


def draw_neutral(
    content: CvContent, photo: Photo | None
) -> tuple[Rendered, str, tuple[str, ...]]:
    """The rendering whatever its overflows, with them (a preview shows what spills over); English missing is still
    refused."""
    if content.missing:
        raise CvRefusedError((MISSING_ENGLISH + " ; ".join(content.missing) + ".",))
    html = neutral_html(
        content,
        with_photo=photo is not None,
        suffix=photo.suffix if photo else "jpg",
    )
    assets = dict(font_assets())
    if photo is not None:
        assets[f"photo.{photo.suffix}"] = photo.content
    rendered = render_pdf(html, assets)
    return rendered, html, problems(rendered)


def problems(rendered: Rendered) -> tuple[str, ...]:
    """What makes a rendering unfit, in the user's words (Q6: nothing is shrunk to fit)."""
    found = [
        f"Le contenu dépasse la {overflow.box} d'environ "
        f"{max(overflow.extra_height_px, overflow.extra_width_px) * PX_TO_MM:.0f} mm : "
        "raccourcis un texte ou retire un élément du CV."
        for overflow in rendered.overflows
        if overflow.box != "page"
    ]
    if rendered.page_count != 1:
        found.append(f"Le CV fait {rendered.page_count} pages au lieu d'une.")
    if rendered.missing_fonts:
        found.append("Police non chargée : " + ", ".join(rendered.missing_fonts) + ".")
    if rendered.refused_requests:
        found.append(
            "Le gabarit demande un fichier absent : "
            + ", ".join(rendered.refused_requests)
            + "."
        )
    return tuple(found)
