"""The keyboard of Rocky in a real browser (decision G6, A8; constat B4 → C7): a key struck while an HTMX request is on
its way waits for the answer, then acts on it. Nothing leaves the test: the page and its answers are given by the
browser's routing, the answer held until the keys are struck."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, sync_playwright

STATIC = Path(__file__).resolve().parents[2] / "rocky" / "system" / "static"
ORIGIN = "http://rocky.test"
PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<script src="/static/htmx-2.0.11.min.js"></script><script src="/static/rocky.js"></script></head>
<body hx-boost="true">
  <div id="zone">
    <button type="button" data-key="i" hx-get="/motifs" hx-target="#zone" hx-swap="innerHTML">Intéressé</button>
  </div>
  <p id="journal"></p>
</body></html>"""
WRITE = "document.getElementById('journal').textContent += '{}'"
# The panel of the reasons, as it arrives: a reason under « 1 », the validation under « Entrée ».
PANEL = (
    f'<button type="button" data-key="1" onclick="{WRITE.format("1")}">métier visé</button>'
    f'<button type="button" data-key="Enter" onclick="{WRITE.format("⏎")}">Valider</button>'
)


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser.new_page()
        finally:
            browser.close()


def serve(page: Page, held: list[Route]) -> None:
    def answer(route: Route) -> None:
        path = route.request.url.removeprefix(ORIGIN)
        if path.startswith("/static/"):
            route.fulfill(path=STATIC / path.removeprefix("/static/"))
        elif path == "/motifs":
            held.append(route)  # answered once the keys are struck
        else:
            route.fulfill(body=PAGE, content_type="text/html")

    page.route(f"{ORIGIN}/**", answer)
    page.goto(f"{ORIGIN}/")


def test_the_keys_struck_while_the_panel_arrives_act_on_it(page: Page) -> None:
    held: list[Route] = []
    serve(page, held)

    page.keyboard.press("i")
    page.wait_for_function(
        "document.querySelector('#zone button').classList.contains('htmx-request')"
    )
    page.keyboard.press("1")
    page.keyboard.press("Enter")
    assert len(held) == 1
    held[0].fulfill(body=PANEL, content_type="text/html")

    page.wait_for_function(
        "document.getElementById('journal').textContent.length === 2", timeout=3000
    )
    assert page.text_content("#journal") == "1⏎"


def test_a_key_with_nothing_on_its_way_acts_at_once(page: Page) -> None:
    serve(page, [])
    page.evaluate(
        "html => { document.getElementById('zone').innerHTML = html; }", PANEL
    )

    page.keyboard.press("1")

    assert page.text_content("#journal") == "1"
