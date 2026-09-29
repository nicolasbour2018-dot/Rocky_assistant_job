"""The free fonts shipped with Rocky (decision D2, Q19, Q22): served to the renderer, never fetched from the network.

A font named in a PDF (``ABCDEF+Poppins-Bold``) is matched to a shipped file by family, weight and style; a family
Rocky does not ship is replaced by the default one, and the replacement is reported, never silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

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
