"""HTML → PDF with headless Chromium (Playwright), cut off from the network; overflow measured, pages rasterised.

Decision ``docs/decisions/D2-cv-rendu.md`` (Q6, Q13, Q17):
- the page and its assets are served from memory under a fictitious origin; every other request is refused, so a
  render depends only on the bytes it is given and never calls out;
- every element marked ``data-box="<name>"`` is measured after layout: content wider or taller than the box is an
  overflow, reported by name; nothing is shrunk;
- the PDF bytes change with each render (creation date): stability is judged on the rasterised pages.
"""

from __future__ import annotations

import io
import mimetypes
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pypdfium2
from PIL import Image, ImageChops
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Route, sync_playwright

from rocky.system.errors import UserFacingError

ORIGIN = "http://rocky.cv/"
PAGE = "index.html"
TOLERANCE_PX = 1  # sub-pixel rounding of the layout

_MEASURE = """() => {
  const boxes = [];
  for (const el of document.querySelectorAll('[data-box]')) {
    const extraX = el.scrollWidth - el.clientWidth;
    const extraY = el.scrollHeight - el.clientHeight;
    boxes.push({name: el.dataset.box, extraX, extraY});
  }
  return {boxes, fonts: [...document.fonts].filter(f => f.status === 'error').map(f => f.family)};
}"""
# Every declared font is loaded, used or not: a font file that fails is then an error, never a silent fallback.
_LOAD_FONTS = (
    "Promise.allSettled([...document.fonts].map(f => f.load())).then(() => true)"
)


class RenderError(UserFacingError):
    """The browser could not render the page; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Overflow:
    box: str
    extra_width_px: int
    extra_height_px: int


@dataclass(frozen=True)
class Rendered:
    pdf: bytes
    page_count: int
    overflows: tuple[Overflow, ...]
    missing_fonts: tuple[str, ...]  # declared fonts whose file failed to load
    refused_requests: tuple[str, ...]  # requests outside the given assets


def render_pdf(html: str, assets: Mapping[str, bytes] | None = None) -> Rendered:
    """Render ``html`` (A4 by its own ``@page`` rule); ``assets`` are served by relative path (``fonts/a.ttf``)."""
    files = {PAGE: html.encode(), **(assets or {})}
    refused: list[str] = []

    def serve(route: Route) -> None:
        url = route.request.url
        name = url[len(ORIGIN) :].split("?", 1)[0] if url.startswith(ORIGIN) else None
        if name is None or name not in files:
            refused.append(url)
            route.abort()
            return
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
        route.fulfill(status=200, body=files[name], content_type=kind)

    try:
        with sync_playwright() as playwright:
            # Without hinting, glyph advances match the PDF fonts: readers see words, not spaced letters.
            browser = playwright.chromium.launch(args=["--font-render-hinting=none"])
            try:
                page = browser.new_page()
                page.route("**/*", serve)
                page.goto(ORIGIN + PAGE, wait_until="load")
                page.evaluate(_LOAD_FONTS)
                page.evaluate("document.fonts.ready.then(() => true)")
                measured: dict[str, Any] = page.evaluate(_MEASURE)
                pdf = page.pdf(prefer_css_page_size=True, print_background=True)
            finally:
                browser.close()
    except PlaywrightError as error:
        raise RenderError(f"Le rendu du PDF a échoué ({error.message}).") from error
    return Rendered(
        pdf=pdf,
        page_count=page_count(pdf),
        overflows=_overflows(measured["boxes"]),
        missing_fonts=tuple(sorted(set(measured["fonts"]))),
        refused_requests=tuple(refused),
    )


def render_image(
    svg: str, width_pt: float, height_pt: float, dpi: int = 300
) -> Image.Image:
    """An SVG drawing as an opaque RGB image, rendered on screen by Chromium, cut off from the network.

    A design's transparency (masks, soft masks) becomes luminosity masks in a PDF, which some readers draw black
    (Apple's Preview): as one opaque image, the drawing looks the same in every reader.
    """
    width, height = width_pt * 96 / 72, height_pt * 96 / 72  # CSS pixels
    html = (
        "<!doctype html><html><head><style>html, body { margin: 0; background: white; }</style></head>"
        f'<body><img src="{ORIGIN}drawing.svg" style="display:block; width:{width}px; height:{height}px">'
        "</body></html>"
    )
    files = {PAGE: html.encode(), "drawing.svg": svg.encode()}

    def serve(route: Route) -> None:
        name = route.request.url.removeprefix(ORIGIN)
        if name not in files:
            route.abort()
            return
        kind = "image/svg+xml" if name.endswith(".svg") else "text/html"
        route.fulfill(status=200, body=files[name], content_type=kind)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": round(width), "height": round(height)},
                    device_scale_factor=dpi / 96,
                )
                page.route("**/*", serve)
                page.goto(ORIGIN + PAGE, wait_until="load")
                png = page.screenshot(full_page=True, type="png")
            finally:
                browser.close()
    except PlaywrightError as error:
        raise RenderError(
            f"Le dessin du gabarit a échoué ({error.message})."
        ) from error
    return Image.open(io.BytesIO(png)).convert("RGB")


def page_count(pdf: bytes) -> int:
    document = pypdfium2.PdfDocument(pdf)
    try:
        return len(document)
    finally:
        document.close()


def rasterize(pdf: bytes, dpi: int = 100) -> list[Image.Image]:
    """Each page as an RGB image at ``dpi``."""
    document = pypdfium2.PdfDocument(pdf)
    try:
        return [
            page.render(scale=dpi / 72).to_pil().convert("RGB") for page in document
        ]
    finally:
        document.close()


@dataclass(frozen=True)
class Difference:
    changed_pixels: int
    total_pixels: int
    image: Image.Image  # changed pixels in red over a faded copy of ``expected``

    @property
    def ratio(self) -> float:
        return self.changed_pixels / self.total_pixels if self.total_pixels else 0.0


def compare(
    expected: Image.Image,
    actual: Image.Image,
    *,
    threshold: int = 16,
    mask: Sequence[tuple[int, int, int, int]] = (),
) -> Difference:
    """Pixels whose channels differ by more than ``threshold``, outside the ``mask`` rectangles (x0, y0, x1, y1)."""
    if expected.size != actual.size:
        raise ValueError(f"sizes differ: {expected.size} != {actual.size}")
    delta = ImageChops.difference(expected.convert("RGB"), actual.convert("RGB"))
    changed = delta.convert("L").point(lambda value: 255 if value > threshold else 0)
    if mask:
        hidden = Image.new("L", changed.size, 255)
        for box in mask:
            hidden.paste(0, box)
        changed = ImageChops.multiply(changed, hidden)
    histogram = changed.histogram()
    faded = Image.blend(
        expected.convert("RGB"), Image.new("RGB", expected.size, "white"), 0.7
    )
    faded.paste((220, 0, 0), mask=changed)
    return Difference(
        changed_pixels=histogram[255],
        total_pixels=changed.size[0] * changed.size[1],
        image=faded,
    )


def _overflows(boxes: Sequence[Mapping[str, Any]]) -> tuple[Overflow, ...]:
    found = [
        Overflow(
            box=str(box["name"]),
            extra_width_px=max(int(box["extraX"]), 0),
            extra_height_px=max(int(box["extraY"]), 0),
        )
        for box in boxes
        if box["extraX"] > TOLERANCE_PX or box["extraY"] > TOLERANCE_PX
    ]
    return tuple(found)
