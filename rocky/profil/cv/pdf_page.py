"""The geometry of a CV page, read without guessing (decision D2, Q15, Q20, Q25): text blocks with their fonts,
images, and the vector drawing of the page as SVG, from which texts and the photo can be taken out.

pdfminer.six gives the text blocks, lines and characters (font, size, colour); pypdfium2 gives the images at their
original resolution; ``pdftocairo -svg`` (poppler, a separate program) gives the drawing. No AGPL library.
"""

from __future__ import annotations

import io
import math
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pypdfium2
from pdfminer.high_level import extract_pages
from pdfminer.layout import (
    LAParams,
    LTChar,
    LTFigure,
    LTImage,
    LTPage,
    LTTextBox,
    LTTextLine,
)
from PIL import Image

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
HREF = f"{{{XLINK}}}href"
PDFTOCAIRO_TIMEOUT_SECONDS = 60

ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)


class PageError(Exception):
    """The PDF cannot give a template; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Box:
    """A rectangle in points, origin at the top left of the page (as CSS draws it)."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, x: float, y: float, margin: float = 0.0) -> bool:
        return (
            self.x - margin <= x <= self.right + margin
            and self.y - margin <= y <= self.bottom + margin
        )

    def union(self, other: Box) -> Box:
        x, y = min(self.x, other.x), min(self.y, other.y)
        return Box(
            x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y
        )

    def overlap(self, other: Box) -> float:
        """Share of this box covered by ``other``."""
        width = min(self.right, other.right) - max(self.x, other.x)
        height = min(self.bottom, other.bottom) - max(self.y, other.y)
        area = self.width * self.height
        return max(width, 0) * max(height, 0) / area if area else 0.0


@dataclass(frozen=True)
class Style:
    font: str  # PDF name without subset prefix: « Poppins-Bold »
    size: float  # points
    color: str  # #rrggbb

    @property
    def bold(self) -> bool:
        return bool(re.search(r"bold|black|heavy", self.font, re.IGNORECASE))

    @property
    def italic(self) -> bool:
        return bool(re.search(r"italic|oblique", self.font, re.IGNORECASE))


@dataclass(frozen=True)
class Run:
    """Consecutive characters of one style on one line."""

    text: str
    style: Style


@dataclass(frozen=True)
class Line:
    box: Box
    baseline: float  # y of the baseline, from the top
    runs: tuple[Run, ...]
    letter_spacing: float  # points added between characters (Canva's spaced headings)

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass(frozen=True)
class Block:
    id: int
    box: Box
    lines: tuple[Line, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def style_counts(self) -> Counter[Style]:
        counts: Counter[Style] = Counter()
        for line in self.lines:
            for run in line.runs:
                counts[run.style] += len(run.text.strip())
        return counts


@dataclass(frozen=True)
class PageImage:
    box: Box
    image: Image.Image  # at its original resolution


@dataclass(frozen=True)
class PageLayout:
    width: float
    height: float
    blocks: tuple[Block, ...]
    images: tuple[PageImage, ...]
    background: str  # colour of the page corners, #rrggbb


def read_page(pdf: bytes) -> PageLayout:
    """The layout of a one-page CV; refused with its reason otherwise (Q6, Q20)."""
    pages = _page_count(pdf)
    if pages != 1:
        raise PageError(
            f"Ton CV fait {pages} pages : Rocky reproduit un CV d'une page (A4)."
        )
    page = next(extract_pages(io.BytesIO(pdf), laparams=LAParams(all_texts=True)))
    blocks = tuple(_blocks(page))
    if sum(len(block.text.strip()) for block in blocks) < 50:
        raise PageError(
            "Ce PDF ne contient pas de texte lisible (c'est sans doute une image) : "
            "Rocky ne peut pas en déduire un gabarit."
        )
    return PageLayout(
        width=page.width,
        height=page.height,
        blocks=blocks,
        images=tuple(_images(pdf, page)),
        background=_background(pdf),
    )


def _page_count(pdf: bytes) -> int:
    try:
        document = pypdfium2.PdfDocument(pdf)
    except pypdfium2.PdfiumError as error:
        raise PageError("Ce fichier n'est pas un PDF lisible.") from error
    try:
        return len(document)
    finally:
        document.close()


def _walk(container: Any) -> Iterator[Any]:
    for item in container:
        if isinstance(item, LTFigure):
            yield from _walk(item)
        else:
            yield item


def _blocks(page: LTPage) -> Iterator[Block]:
    """One block per text line: a line belongs to one rubric only (a box may join a heading and its content)."""
    lines = [
        line
        for box in _walk(page)
        if isinstance(box, LTTextBox)
        for item in box
        if isinstance(item, LTTextLine)
        and (line := _line(item, page.height)) is not None
    ]
    lines.sort(key=lambda line: (round(line.box.y), line.box.x))
    for index, line in enumerate(lines):
        yield Block(index, line.box, (line,))


def _line(line: LTTextLine, height: float) -> Line | None:
    chars = [c for c in line if isinstance(c, LTChar)]
    if not chars:
        return None
    runs: list[Run] = []
    for item in line:
        text = item.get_text()
        style = (
            _style(item)
            if isinstance(item, LTChar)
            else (runs[-1].style if runs else _style(chars[0]))
        )
        if runs and runs[-1].style == style:
            runs[-1] = Run(runs[-1].text + text, style)
        else:
            runs.append(Run(text, style))
    cleaned = tuple(
        Run(run.text.replace("\n", ""), run.style)
        for run in runs
        if run.text.strip("\n")
    )
    return Line(
        box=_box(line.bbox, height),
        # The text matrix holds the baseline; the character box starts at the descent.
        baseline=round(height - float(chars[0].matrix[5]), 2),
        runs=cleaned,
        letter_spacing=_letter_spacing(chars),
    )


def _style(char: LTChar) -> Style:
    return Style(
        font=char.fontname.split("+", 1)[-1],
        size=round(char.size, 1),
        color=_color(char.graphicstate.ncolor),
    )


def _letter_spacing(chars: Sequence[LTChar]) -> float:
    """Median gap between two letters, over the spaces between them: ordinary text gives 0, a title spaced
    letter by letter (« P R O J E T S ») gives its pitch."""
    letters = [c for c in chars if c.get_text().strip()]
    gaps = sorted(b.x0 - (a.x0 + a.adv) for a, b in pairwise(letters))
    if not gaps:
        return 0.0
    middle = gaps[len(gaps) // 2]
    return round(middle, 2) if middle > 0.3 else 0.0


def _color(value: Any) -> str:
    """pdfminer gives a grey level, an RGB or a CMYK tuple, in 0–1."""
    if isinstance(value, int | float):
        channels = [float(value)] * 3
    elif isinstance(value, list | tuple) and len(value) == 3:
        channels = [float(v) for v in value]
    elif isinstance(value, list | tuple) and len(value) == 4:
        c, m, y, k = (float(v) for v in value)
        channels = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    else:
        channels = [0.0, 0.0, 0.0]
    return "#" + "".join(f"{round(max(0, min(1, v)) * 255):02x}" for v in channels)


def _box(bbox: tuple[float, float, float, float], height: float) -> Box:
    x0, y0, x1, y1 = bbox
    return Box(
        round(x0, 2), round(height - y1, 2), round(x1 - x0, 2), round(y1 - y0, 2)
    )


def _images(pdf: bytes, page: LTPage) -> Iterator[PageImage]:
    """Positions from pdfminer (on the page), pixels from pypdfium2 (whose positions stay in their form's
    space): paired by pixel size, in drawing order."""
    placed = [item for item in _walk(page) if isinstance(item, LTImage)]
    document = pypdfium2.PdfDocument(pdf)
    try:
        bitmaps = [
            item.get_bitmap(render=False).to_pil().convert("RGBA")
            for item in document[0].get_objects(
                filter=(pypdfium2.raw.FPDF_PAGEOBJ_IMAGE,), max_depth=16
            )
        ]
    finally:
        document.close()
    for item in placed:
        size = tuple(int(v) for v in item.srcsize)
        found = next((b for b in bitmaps if b.size == size), None)
        if found is None:
            continue
        bitmaps.remove(found)
        yield PageImage(box=_box(item.bbox, page.height), image=found)


def _background(pdf: bytes) -> str:
    image = render_page(pdf, 20)
    points = (
        (1, 1),
        (image.width - 2, 1),
        (1, image.height - 2),
        (image.width - 2, image.height - 2),
    )
    corners = [_rgb(image, point) for point in points]
    red, green, blue = Counter(corners).most_common(1)[0][0]
    return f"#{red:02x}{green:02x}{blue:02x}"


def _rgb(image: Image.Image, point: tuple[int, int]) -> tuple[int, int, int]:
    pixel = image.getpixel(point)
    if not isinstance(pixel, tuple):
        raise TypeError("an RGB image was expected")
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def render_page(pdf: bytes, dpi: int) -> Image.Image:
    document = pypdfium2.PdfDocument(pdf)
    try:
        image: Image.Image = document[0].render(scale=dpi / 72).to_pil()
        return image.convert("RGB")
    finally:
        document.close()


def photo_candidate(layout: PageLayout) -> PageImage | None:
    """The image most likely to be a portrait: rich in colours, not tiny, not a page-wide decoration."""
    best: tuple[float, PageImage] | None = None
    for item in layout.images:
        if min(item.box.width, item.box.height) < 40:
            continue
        if item.box.width * item.box.height > 0.25 * layout.width * layout.height:
            continue
        sample = item.image.convert("RGB").resize((64, 64))
        colours = len(sample.getcolors(maxcolors=64 * 64) or ())
        entropy = sample.convert("L").entropy()
        score = entropy * math.log(colours + 1)
        if best is None or score > best[0]:
            best = (score, item)
    if best is None or best[0] < 20:
        return None
    return best[1]


@dataclass(frozen=True)
class PhotoFrame:
    image: Box  # where the whole image lies (it may be larger than what shows)
    visible: Box  # what the page shows of it (a clip, often a circle)
    round: bool


def _close(pixel: Any, wanted: tuple[int, ...]) -> bool:
    return all(abs(int(a) - b) <= 12 for a, b in zip(pixel[:3], wanted, strict=False))


# The drawing of the page as SVG, with some texts and the photo taken out.


def page_svg(pdf: bytes) -> str:
    program = shutil.which("pdftocairo")
    if program is None:
        raise PageError("pdftocairo (poppler) est absent de l'installation.")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "cv.pdf"
        target = Path(directory) / "cv.svg"
        source.write_bytes(pdf)
        try:
            subprocess.run(  # noqa: S603  (resolved program, paths of our own temporary directory)
                [program, "-svg", "-f", "1", "-l", "1", str(source), str(target)],
                check=True,
                capture_output=True,
                timeout=PDFTOCAIRO_TIMEOUT_SECONDS,
            )
        except subprocess.CalledProcessError as error:
            raise PageError(
                "pdftocairo n'a pas pu dessiner la page de ce PDF."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise PageError("Le dessin de la page a pris trop de temps.") from error
        return target.read_text(encoding="utf-8")


@dataclass(frozen=True)
class SvgCut:
    svg: str
    glyphs_removed: int
    images_removed: int
    paths_removed: int


def cut_svg(
    svg: str,
    *,
    text_areas: Sequence[Box],
    image_areas: Sequence[Box],
    decoration_areas: Sequence[Box] = (),
) -> SvgCut:
    """Remove the glyphs drawn inside ``text_areas``, the images covering ``image_areas``, and the small paths
    lying wholly inside ``decoration_areas`` (bullets and underlines drawn for the old texts).

    Poppler draws each form of the PDF as a ``source-N`` group used once, placed by a matrix: the matrices are
    composed from the page down to each glyph and image to know where they land.
    """
    root = ET.fromstring(svg)  # noqa: S314  (SVG produced by poppler from the user's own PDF, no entity expansion)
    ids = {element.get("id"): element for element in root.iter() if element.get("id")}
    parents = {child: parent for parent in root.iter() for child in parent}
    glyphs: list[ET.Element] = []
    images: list[ET.Element] = []
    paths: list[ET.Element] = []

    def visit(element: ET.Element, matrix: Matrix, depth: int) -> None:
        if depth > 64:
            return
        matrix = matrix @ _transform(element.get("transform"))
        tag = element.tag.split("}")[-1]
        if tag == "defs" and depth == 1:
            return
        if tag == "use":
            href = (element.get(HREF) or "").lstrip("#")
            offset = Matrix.translate(
                float(element.get("x", 0)), float(element.get("y", 0))
            )
            if href.startswith("glyph"):
                x, y = (matrix @ offset).apply(0, 0)
                if any(area.contains(x, y, margin=1.5) for area in text_areas):
                    glyphs.append(element)
                return
            target = ids.get(href)
            if target is not None:
                visit(target, matrix @ offset, depth + 1)
            return
        if tag == "image":
            width, height = (
                float(element.get("width", 0)),
                float(element.get("height", 0)),
            )
            x0, y0 = matrix.apply(
                float(element.get("x", 0)), float(element.get("y", 0))
            )
            x1, y1 = matrix.apply(
                float(element.get("x", 0)) + width, float(element.get("y", 0)) + height
            )
            drawn = Box(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            if any(
                drawn.overlap(area) > 0.8 and area.overlap(drawn) > 0.8
                for area in image_areas
            ):
                images.append(element)
            return
        if tag == "path" and decoration_areas:
            drawn_path = _path_box(element.get("d", ""), matrix)
            if drawn_path is not None and any(
                drawn_path.overlap(area) > 0.99 for area in decoration_areas
            ):
                paths.append(element)
            return
        for child in list(element):
            visit(child, matrix, depth + 1)

    visit(root, Matrix.identity(), 0)
    for element in (*glyphs, *images, *paths):
        parent = parents.get(element)
        if parent is not None and element in list(parent):
            parent.remove(element)
    return SvgCut(
        ET.tostring(root, encoding="unicode"), len(glyphs), len(images), len(paths)
    )


def _path_box(d: str, matrix: Matrix) -> Box | None:
    """Bounds of an absolute poppler path (M, L, C, Z commands), control points included."""
    numbers = [float(n) for n in re.findall(_NUMBER, d)]
    if len(numbers) < 2 or re.search(r"[a-y]", d.replace("e-", "")):
        return None  # relative commands: not what poppler writes; left alone
    points = [
        matrix.apply(x, y) for x, y in zip(numbers[::2], numbers[1::2], strict=False)
    ]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


@dataclass(frozen=True)
class Matrix:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def identity(cls) -> Matrix:
        return cls(1, 0, 0, 1, 0, 0)

    @classmethod
    def translate(cls, x: float, y: float) -> Matrix:
        return cls(1, 0, 0, 1, x, y)

    def __matmul__(self, other: Matrix) -> Matrix:
        return Matrix(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f


_NUMBER = r"-?[\d.]+(?:e-?\d+)?"


def _transform(value: str | None) -> Matrix:
    if not value:
        return Matrix.identity()
    result = Matrix.identity()
    for name, arguments in re.findall(r"(\w+)\(([^)]*)\)", value):
        numbers = [float(n) for n in re.findall(_NUMBER, arguments)]
        if name == "matrix" and len(numbers) == 6:
            result = result @ Matrix(*numbers)
        elif name == "translate":
            result = result @ Matrix.translate(
                numbers[0], numbers[1] if len(numbers) > 1 else 0
            )
        elif name == "scale":
            sx = numbers[0]
            sy = numbers[1] if len(numbers) > 1 else sx
            result = result @ Matrix(sx, 0, 0, sy, 0, 0)
    return result
