"""A CV as a PDF: its content in a template, rendered by ``system.render`` (decision D2, Q6, Q11, Q13).

A CV is refused, with its reasons, rather than delivered wrong: English texts missing, a box overflowing, a second
page, a font that did not load. The hash of the rendered HTML identifies a rendering: the same content in the same
template gives the same hash (the PDF bytes themselves carry a creation date).

The neutral template holds one page by cutting a paragraph longer than its limit, each cut named (decision G5, Q1:
visible, never silent); a box that overflows all the same is still refused.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from rocky.profil.cv.content import CvContent, CvEntry, CvProject, Span
from rocky.profil.cv.library import font_assets, font_faces
from rocky.system.errors import UserFacingError
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


class CvRefusedError(UserFacingError):
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
    # What the neutral template cut to hold one page (G5, Q1): shown beside the CV, never blocking.
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class NeutralLimits:
    """Characters a paragraph keeps in the neutral template (G5, Q1), set so that a full career holds one page:
    3 jobs of 3 bullets, 4 trainings of 2 bullets, 3 projects, a headline (``tests/profil/cv/test_rendering.py``)."""

    headline: int = 300
    job_bullet: int = 140
    education_bullet: int = 90
    project_part: int = 140


NEUTRAL_LIMITS = NeutralLimits()
ELLIPSIS = "…"


def shortened(text: str, limit: int) -> str | None:
    """``text`` cut after its last whole word within ``limit`` characters, ellipsis included; None when it fits."""
    if len(text) <= limit:
        return None
    head = text[: limit - len(ELLIPSIS)]
    if not text[len(head)].isspace() and " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:.–-") + ELLIPSIS


def fit_neutral(
    content: CvContent, limits: NeutralLimits = NEUTRAL_LIMITS
) -> tuple[CvContent, tuple[str, ...]]:
    """The content the neutral template draws, and each cut it made, in the user's words."""
    cuts: list[str] = []

    def fit(text: str, limit: int, where: str) -> str:
        short = shortened(text, limit)
        if short is None:
            return text
        cuts.append(f"{where} : coupé à {limit} caractères.")
        return short

    def entries(
        items: tuple[CvEntry, ...], what: str, limit: int
    ) -> tuple[CvEntry, ...]:
        return tuple(
            replace(
                entry,
                bullets=tuple(
                    fit(bullet, limit, f"{what} « {entry.title} », puce {number}")
                    for number, bullet in enumerate(entry.bullets, start=1)
                ),
            )
            for entry in items
        )

    def project(item: CvProject) -> CvProject:
        where = f"Projet « {item.name} »"
        return replace(
            item,
            problem=fit(item.problem, limits.project_part, f"{where}, problème"),
            work=fit(item.work, limits.project_part, f"{where}, réalisation"),
            results=fit(item.results, limits.project_part, f"{where}, résultats"),
        )

    headline = _fit_headline(content.headline, limits.headline)
    if headline != content.headline:
        cuts.append(f"Accroche : coupée à {limits.headline} caractères.")
    fitted = replace(
        content,
        headline=headline,
        experiences=entries(content.experiences, "Expérience", limits.job_bullet),
        projects=tuple(project(item) for item in content.projects),
        education=entries(content.education, "Formation", limits.education_bullet),
    )
    return fitted, tuple(cuts)


def _fit_headline(
    paragraphs: tuple[tuple[Span, ...], ...], limit: int
) -> tuple[tuple[Span, ...], ...]:
    """The paragraphs within ``limit`` characters in all; the one that reaches it is cut, the next ones dropped."""
    kept: list[tuple[Span, ...]] = []
    left = limit
    for paragraph in paragraphs:
        text = "".join(span.text for span in paragraph)
        if len(text) <= left:
            kept.append(paragraph)
            left -= len(text)
            continue
        short = shortened(text, left) if left > len(ELLIPSIS) else None
        if short is not None and short != ELLIPSIS:
            kept.append(_spans_within(paragraph, short))
        break
    return tuple(kept)


def _spans_within(paragraph: tuple[Span, ...], short: str) -> tuple[Span, ...]:
    """The spans of ``paragraph`` cut to the text of ``short`` (which ends with the ellipsis), bold kept."""
    body = short[: -len(ELLIPSIS)]
    spans: list[Span] = []
    position = 0
    for span in paragraph:
        if position >= len(body):
            break
        piece = span.text[: len(body) - position]
        position += len(span.text)
        if piece.strip():
            spans.append(Span(piece, span.bold))
    spans.append(Span(ELLIPSIS))
    return tuple(spans)


def neutral_html(content: CvContent, *, with_photo: bool, suffix: str = "jpg") -> str:
    """The neutral page of ``content``, cut to its limits (``fit_neutral``)."""
    content, _ = fit_neutral(content)
    return _environment.get_template("cv.html").render(
        cv=content,
        labels=LABELS[content.language],
        # French typography puts a (non-breaking) space before the colon.
        colon="\u00a0:" if content.language == "fr" else ":",
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
        notices=fit_neutral(content)[1],
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
