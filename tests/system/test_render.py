"""HTML → PDF: overflow named, network refused, stable raster (decision D2, Q6, Q13). Real headless Chromium."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from rocky.system.pdf_read import read_pdf
from rocky.system.render import compare, rasterize, render_pdf

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0; }}
body {{ margin: 0; font: 12px sans-serif; }}
.box {{ position: absolute; left: 20mm; top: 20mm; width: 60mm; height: 12mm; overflow: hidden; }}
</style></head><body>
<div class="box" data-box="summary">{text}</div>
{extra}
</body></html>"""


def test_a_page_renders_to_one_readable_pdf_page() -> None:
    rendered = render_pdf(PAGE.format(text="Data Scientist", extra=""))

    assert rendered.page_count == 1
    assert rendered.overflows == ()
    assert rendered.refused_requests == ()
    assert all("Data Scientist" in reading.text for reading in read_pdf(rendered.pdf))


def test_text_longer_than_its_box_is_an_overflow_named_by_the_box() -> None:
    rendered = render_pdf(PAGE.format(text="mot " * 200, extra=""))

    assert [overflow.box for overflow in rendered.overflows] == ["summary"]
    assert rendered.overflows[0].extra_height_px > 0


def test_every_request_outside_the_given_assets_is_refused() -> None:
    extra = '<img src="https://example.com/tracker.png"><img src="logo.png">'

    rendered = render_pdf(PAGE.format(text="x", extra=extra))

    assert rendered.refused_requests == (
        "https://example.com/tracker.png",
        "http://rocky.cv/logo.png",
    )


def test_given_assets_are_served() -> None:
    image = Image.new("RGB", (4, 4), "red")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_pdf(
        PAGE.format(text="x", extra='<img src="logo.png">'),
        {"logo.png": buffer.getvalue()},
    )

    assert rendered.refused_requests == ()


def test_the_same_page_rasterises_identically_twice() -> None:
    html = PAGE.format(text="Stable", extra="")

    first = rasterize(render_pdf(html).pdf)[0]
    second = rasterize(render_pdf(html).pdf)[0]

    assert compare(first, second).changed_pixels == 0


def test_compare_counts_changes_outside_the_mask_only() -> None:
    expected = Image.new("RGB", (10, 10), "white")
    actual = expected.copy()
    actual.paste((0, 0, 0), (0, 0, 2, 2))  # 4 pixels, masked
    actual.paste((0, 0, 0), (8, 8, 10, 10))  # 4 pixels, visible

    difference = compare(expected, actual, mask=[(0, 0, 2, 2)])

    assert difference.changed_pixels == 4
    assert difference.total_pixels == 100
