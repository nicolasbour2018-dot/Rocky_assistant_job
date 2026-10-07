"""What rocky.js does in a real browser (decision G6): the keys struck while an HTMX request is on its way (A8; constat
B4 → C7), the window (R2, R3), the wait (Q8). Nothing leaves the test: the page and its answers are given by the
browser's routing, an answer held while the test acts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, sync_playwright

STATIC = Path(__file__).resolve().parents[2] / "rocky" / "system" / "static"
ORIGIN = "http://rocky.test"
PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>.busybar { visibility: hidden; } .is-busy .busybar { visibility: visible; }</style>
<script src="/static/htmx-2.0.11.min.js"></script><script src="/static/rocky.js"></script></head>
<body hx-boost="true">
  <div class="busybar">attente</div>
  <div id="zone">
    <button type="button" data-key="i" hx-get="/motifs" hx-target="#zone" hx-swap="innerHTML">Intéressé</button>
  </div>
  <button type="button" id="ouvrir" data-key="o" hx-get="/fenetre" hx-target="#fenetre-contenu"
    hx-swap="innerHTML">Fiche</button>
  <p id="journal"></p>
  <dialog id="fenetre"><div id="fenetre-contenu"></div></dialog>
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
        elif path in ("/motifs", "/fenetre"):
            held.append(route)  # answered when the test says
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


# The window as ui.html renders it: its head with « Fermer » (Escape), a field and a reason.
WINDOW = (
    '<div class="window-head"><h2 id="fenetre-titre">Fiche</h2>'
    '<button type="button" data-close-window data-key="Escape">Fermer</button></div>'
    '<input type="text" id="precision">'
    f'<button type="button" data-key="1" onclick="{WRITE.format("1")}">métier visé</button>'
)


def open_window(page: Page, held: list[Route]) -> None:
    page.keyboard.press("o")
    page.wait_for_function("() => document.getElementById('ouvrir').disabled")
    held.pop().fulfill(body=WINDOW, content_type="text/html")
    page.wait_for_function("() => document.getElementById('fenetre').open")


def test_the_window_opens_with_its_fragment_takes_the_keys_and_closes(
    page: Page,
) -> None:
    held: list[Route] = []
    serve(page, held)

    open_window(page, held)
    page.keyboard.press("i")  # behind the window: nothing moves
    page.keyboard.press("1")
    page.keyboard.press("Escape")

    assert held == []
    assert page.text_content("#journal") == "1"
    assert page.evaluate("document.getElementById('fenetre').open") is False
    assert page.inner_html("#fenetre-contenu") == ""


def test_escape_in_a_field_of_the_window_keeps_it_open(page: Page) -> None:
    held: list[Route] = []
    serve(page, held)
    open_window(page, held)

    page.fill("#precision", "en cours")
    page.press("#precision", "Escape")

    assert page.evaluate("document.getElementById('fenetre').open") is True
    assert page.input_value("#precision") == "en cours"


def test_the_gesture_waits_disabled_and_the_bar_shows_after_300_ms(page: Page) -> None:
    held: list[Route] = []
    serve(page, held)

    page.click("#ouvrir")
    disabled = page.evaluate("document.getElementById('ouvrir').disabled")
    early = page.evaluate("document.documentElement.classList.contains('is-busy')")
    page.wait_for_function(
        "document.documentElement.classList.contains('is-busy')", timeout=2000
    )
    held.pop().fulfill(body=WINDOW, content_type="text/html")
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('is-busy')"
    )

    assert disabled is True
    assert early is False
    assert page.evaluate("document.getElementById('ouvrir').disabled") is False
