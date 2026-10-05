"""Renders shared by the tests of ``profil`` for the whole run (decision G1).

The same fictional CV is imported, derived and rendered by several files (``cv/test_derived``, ``cv/test_english``,
``test_web``, ``test_english_web``): each derivation draws two 300 dpi layers in Chromium. A render depends only on
the bytes it is given (``rocky.system.render``), so the first render of given inputs is kept and handed back to the
next tests that ask for the same. Its stability is tested on real renders, in ``tests/system/test_render.py``.

The renders are replaced only during the tests of ``profil``: ``candidatures`` render the same CVs for real.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping

import pytest
from PIL import Image

from rocky.profil.cv import derived, rendering
from rocky.system.render import Rendered, render_image, render_pdf

_PDFS: dict[str, Rendered] = {}
_IMAGES: dict[str, Image.Image] = {}


def _key(*parts: str | bytes | float) -> str:
    digest = hashlib.sha256()
    for part in parts:
        data = part if isinstance(part, bytes) else repr(part).encode()
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def shared_pdf(html: str, assets: Mapping[str, bytes] | None = None) -> Rendered:
    files = sorted((assets or {}).items())
    key = _key(html, *(part for name, content in files for part in (name, content)))
    if key not in _PDFS:
        _PDFS[key] = render_pdf(html, assets)
    return _PDFS[key]


def shared_image(
    svg: str, width_pt: float, height_pt: float, dpi: int = 300
) -> Image.Image:
    key = _key(svg, width_pt, height_pt, dpi)
    if key not in _IMAGES:
        _IMAGES[key] = render_image(svg, width_pt, height_pt, dpi)
    return _IMAGES[key].copy()


SHARED: tuple[tuple[object, str, Callable[..., object]], ...] = (
    (rendering, "render_pdf", shared_pdf),
    (derived, "render_pdf", shared_pdf),
    (derived, "render_image", shared_image),
)


@pytest.fixture(autouse=True)
def shared_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    for module, name, shared in SHARED:
        monkeypatch.setattr(module, name, shared)
