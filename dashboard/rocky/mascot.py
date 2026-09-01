"""Avatar Rocky basé sur la mascotte fournie par l'utilisateur.

L'illustration est conservée comme PNG local transparent. Les expressions sont
des micro-overlays SVG (pensée, curiosité, compassion, validation, etc.) : le
dessin original reste ainsi intact tout en donnant un retour vivant pendant le
chat.
"""

from __future__ import annotations

import base64
from pathlib import Path

EXPRESSIONS = (
    "smiling",
    "thinking",
    "remembering",
    "curious",
    "surprised",
    "compassionate",
    "good-job-check",
)

_ASSET_PATH = Path(__file__).resolve().parents[2] / "assets" / "rocky_mascot.png"
_PNG_DATA: str | None = None


def _png_data_uri() -> str:
    """Charge une seule fois la mascotte locale sous forme de data URI."""
    global _PNG_DATA  # noqa: PLW0603 - memoisation d'un asset lu une seule fois
    if _PNG_DATA is None:
        encoded = base64.b64encode(_ASSET_PATH.read_bytes()).decode("ascii")
        _PNG_DATA = f"data:image/png;base64,{encoded}"
    return _PNG_DATA


def _expression_overlay(expression: str) -> str:
    """Retourne un badge discret qui accompagne l'état conversationnel."""
    overlays = {
        "smiling": '<path d="M112 18l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" fill="#ffb454"/>',
        "thinking": '<circle cx="20" cy="30" r="4" fill="#08b5d1"/><circle cx="29" cy="21" r="6" fill="#08b5d1"/><circle cx="40" cy="12" r="8" fill="#08b5d1" opacity=".9"/>',
        "remembering": '<circle cx="116" cy="30" r="15" fill="#fff" stroke="#ffb454" stroke-width="3"/><path d="M116 21v10l7 4" fill="none" stroke="#18212b" stroke-width="3" stroke-linecap="round"/>',
        "curious": '<circle cx="117" cy="28" r="16" fill="#fff" stroke="#08b5d1" stroke-width="3"/><text x="117" y="35" text-anchor="middle" font-family="sans-serif" font-size="22" font-weight="700" fill="#18212b">?</text>',
        "surprised": '<path d="M111 5l5 10 11 1-8 7 3 11-10-6-10 6 3-11-8-7 11-1z" fill="#ff7f66" opacity=".95"/>',
        "compassionate": '<path d="M116 23c-9-10-22 2 0 17 22-15 9-27 0-17z" fill="#ff7f66"/>',
        "good-job-check": '<circle cx="116" cy="29" r="17" fill="#b9e769" stroke="#18212b" stroke-width="3"/><path d="M107 29l6 6 12-14" fill="none" stroke="#18212b" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    }
    return overlays[expression]


def mascot_svg(expression: str = "smiling") -> str:
    """Retourne la mascotte PNG intégrée dans un SVG expressif."""
    expression = expression if expression in EXPRESSIONS else "smiling"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 146 242" role="img" aria-label="Rocky, {expression}">
  <title>Rocky — {expression}</title>
  <image href="{_png_data_uri()}" x="0" y="0" width="146" height="242" preserveAspectRatio="xMidYMid meet"/>
  {_expression_overlay(expression)}
</svg>'''


def mascot_data_uri(expression: str = "smiling") -> str:
    """Encode l'expression dans une data URI utilisable par Streamlit/CSS."""
    encoded = base64.b64encode(mascot_svg(expression).encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
