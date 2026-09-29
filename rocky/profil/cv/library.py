"""The free fonts shipped with Rocky (decision D2, Q19, Q22): served to the renderer, never fetched from the network.

A font named in a PDF (``ABCDEF+Poppins-Bold``) is matched to a shipped file by family, weight and style; a family
Rocky does not ship is replaced by the default one, and the replacement is reported, never silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONTS_DIR = Path(__file__).parent / "fonts"
DEFAULT_FAMILY = "Poppins"


@dataclass(frozen=True)
class FontFile:
    family: str
    weight: int
    italic: bool
    file: str


FONTS = (
    FontFile("Poppins", 400, False, "Poppins-Regular.ttf"),
    FontFile("Poppins", 700, False, "Poppins-Bold.ttf"),
    FontFile("Poppins", 400, True, "Poppins-Italic.ttf"),
    FontFile("Questrial", 400, False, "Questrial-Regular.ttf"),
    FontFile("Glacial Indifference", 400, False, "GlacialIndifference-Regular.otf"),
    FontFile("Glacial Indifference", 700, False, "GlacialIndifference-Bold.otf"),
)
FAMILIES = tuple(dict.fromkeys(font.family for font in FONTS))


@dataclass(frozen=True)
class Match:
    family: str
    weight: int
    italic: bool
    replaced: bool  # the family is not shipped: ``family`` stands in for it


def match_pdf_font(name: str) -> Match:
    """``ABCDEF+GlacialIndifference-Regu`` → Glacial Indifference, 400, upright."""
    base = name.split("+", 1)[-1]
    key = _key(base)
    weight = 700 if re.search(r"bold|black|heavy|semibold", key) else 400
    italic = bool(re.search(r"italic|oblique", key))
    for family in FAMILIES:
        if key.startswith(_key(family)):
            return Match(family, weight, italic, replaced=False)
    return Match(DEFAULT_FAMILY, weight, italic, replaced=True)


def font_faces(prefix: str = "fonts/") -> str:
    """``@font-face`` rules for every shipped file, under ``prefix`` (the renderer serves ``font_assets``)."""
    return "\n".join(
        f'@font-face {{ font-family: "{font.family}"; src: url("{prefix}{font.file}"); '
        f"font-weight: {font.weight}; font-style: {'italic' if font.italic else 'normal'}; }}"
        for font in FONTS
    )


@cache
def font_assets(prefix: str = "fonts/") -> dict[str, bytes]:
    return {
        f"{prefix}{font.file}": (FONTS_DIR / font.file).read_bytes() for font in FONTS
    }


def _key(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


@dataclass(frozen=True)
class TextPath:
    d: str  # SVG path, in points, baseline at y = ascent
    width: float
    height: float
    ascent: float


def text_path(
    text: str,
    family: str,
    weight: int,
    italic: bool,
    size: float,
    letter_spacing: float = 0.0,
) -> TextPath:
    """``text`` drawn as outlines of a shipped font (decision D2): visible like text, never read as text.

    Used for the titles a design spaces letter by letter: as text, PDF readers would find « E D U C A T I O N ».
    """
    font = _ttfont(_file_of(family, weight, italic))
    scale = size / font["head"].unitsPerEm
    ascent = font["hhea"].ascent * scale
    descent = -font["hhea"].descent * scale
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    parts: list[str] = []
    x = 0.0
    for character in text:
        name = cmap.get(ord(character))
        if name is None:
            name = ".notdef"
        pen = SVGPathPen(glyphs)
        transform = TransformPen(pen, (scale, 0, 0, -scale, x, ascent))
        glyphs[name].draw(transform)
        if pen.getCommands():
            parts.append(pen.getCommands())
        x += glyphs[name].width * scale + letter_spacing
    return TextPath(
        " ".join(parts),
        round(max(x - letter_spacing, 0.0), 2),
        round(ascent + descent, 2),
        round(ascent, 2),
    )


def _file_of(family: str, weight: int, italic: bool) -> str:
    candidates = [font for font in FONTS if font.family == family] or [
        font for font in FONTS if font.family == DEFAULT_FAMILY
    ]
    best = min(candidates, key=lambda f: (f.italic != italic, abs(f.weight - weight)))
    return best.file


@cache
def _ttfont(file: str) -> TTFont:
    return TTFont(FONTS_DIR / file)
