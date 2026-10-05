"""The Rocky workstation, run on the user's computer: ``uv run rocky-poste`` (decisions D5, E5).

It listens on the loopback only and drives a visible Chromium (a persistent profile: the job sites remember the
user's logins). It never clicks anything and never solves a challenge: the user does, in the window.

- Lecture assistée (decision E5): it opens a posting in a tab (``/ouvrir``), then hands back the page as it is shown
  (``/lire``); the tab stays open (Q5).
- Prefilling (decision D5, Q1, Q4), DORMANT since the acceptance of 04/10 (``candidatures.web.PREFILL_ENABLED``): it
  fills what it recognises in a form and leaves the rest to the user, who sends it themselves.

Procedure: ``docs/procedures/d5-poste/``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import queue
import re
import secrets
import sys
import threading
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from playwright.sync_api import (
    BrowserContext,
    FilePayload,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError

from rocky.system.workstation import (
    FIELDS,
    FILE_KINDS,
    MAX_PAGE_BYTES,
    OPEN_PATH,
    PREFILL_PATH,
    READ_PATH,
    TIMEOUT_SECONDS,
    JobFile,
    PrefillJob,
    PrefillReport,
    ShownPage,
    tab_to_read,
    url_to_open,
)

DEFAULT_PORT = 8765
DEFAULT_PROFILE = Path.home() / ".rocky" / "navigateur"
MAX_BODY_BYTES = 30 * 1024 * 1024  # two PDFs in base64, with room to spare
OPEN_TIMEOUT_MS = 60_000
SETTLE_MS = 1_500  # pages that draw their form after loading
CANDIDATES = 5  # elements tried per selector

# Recognised by their attributes (the selectors of the old Rocky), then by their label (FR, EN).
SELECTORS: Mapping[str, tuple[str, ...]] = {
    "full_name": (
        "input[autocomplete='name']",
        "input[name*='fullname' i]",
        "input[name*='full_name' i]",
        "input[id*='fullname' i]",
        "input[id*='full_name' i]",
    ),
    "email": (
        "input[type='email']",
        "input[autocomplete='email']",
        "input[name*='email' i]",
    ),
    "phone": (
        "input[type='tel']",
        "input[autocomplete='tel']",
        "input[name*='phone' i]",
    ),
    "city": (
        "input[autocomplete='address-level2']",
        "input[name*='city' i]",
        "input[name*='ville' i]",
    ),
    "postal_code": (
        "input[autocomplete='postal-code']",
        "input[name*='postal' i]",
        "input[name*='zip' i]",
    ),
    "linkedin": ("input[name*='linkedin' i]", "input[id*='linkedin' i]"),
    "github": ("input[name*='github' i]", "input[id*='github' i]"),
    "portfolio": (
        "input[name*='portfolio' i]",
        "input[name*='website' i]",
        "input[id*='portfolio' i]",
    ),
    "message": (
        "textarea[name*='message' i]",
        "textarea[name*='motivation' i]",
        "textarea[name*='cover' i]",
        "textarea[id*='message' i]",
        "textarea[id*='motivation' i]",
        "textarea[id*='cover' i]",
    ),
}
LABELS: Mapping[str, str] = {
    "full_name": r"nom complet|full name|nom et prénom",
    "email": r"e-?mail|courriel",
    "phone": r"téléphone|telephone|phone|mobile",
    "city": r"^\s*ville|\bcity\b",
    "postal_code": r"code postal|postal code|zip",
    "linkedin": r"linkedin",
    "github": r"github",
    "portfolio": r"portfolio|site web|site personnel|website",
    "message": r"message|motivation|cover letter",
}
FILE_MARKERS: Mapping[str, tuple[str, ...]] = {
    "cv": ("cv", "resume", "résumé"),
    "letter": ("cover", "letter", "lettre", "motivation"),
}


def fill_form(page: Page, job: PrefillJob) -> PrefillReport:
    """Fill what is recognised on ``page``; never click, never submit. A field already filled (by the site or the
    user) is left as it is. Every value or file not placed is reported with its reason."""
    filled: list[str] = []
    missing: list[str] = []
    for key, value in job.fields:
        label = FIELDS[key]
        reason = _fill_field(page, key, value)
        if reason is None:
            filled.append(label)
        else:
            missing.append(f"{label} : {reason}")
    placed, left = _drop_files(page, job.files)
    filled.extend(placed)
    missing.extend(left)
    return PrefillReport(tuple(filled), tuple(missing))


def _fill_field(page: Page, key: str, value: str) -> str | None:
    """None when filled; else why not."""
    already = False
    for candidate in _candidates(page, key):
        try:
            if not (candidate.is_visible() and candidate.is_editable()):
                continue
            if candidate.input_value():
                already = True
                continue
            candidate.fill(value)
        except PlaywrightError as error:
            return f"échec ({_first_line(error)})"
        return None
    return "déjà rempli, laissé tel quel" if already else "champ introuvable"


def _candidates(page: Page, key: str) -> list[Locator]:
    found: list[Locator] = []
    for selector in SELECTORS[key]:
        locator = page.locator(selector)
        found.extend(locator.nth(i) for i in range(min(locator.count(), CANDIDATES)))
    by_label = page.get_by_label(re.compile(LABELS[key], re.IGNORECASE))
    for i in range(min(by_label.count(), CANDIDATES)):
        candidate = by_label.nth(i)
        tag = candidate.evaluate("e => e.tagName + ':' + (e.type || '')").lower()
        if tag.startswith("textarea") or (
            tag.startswith("input") and not tag.endswith(":file")
        ):
            found.append(candidate)
    return found


def _drop_files(page: Page, files: tuple[JobFile, ...]) -> tuple[list[str], list[str]]:
    """Each file into the file field that names it, else into the first field left (CV first)."""
    placed: list[str] = []
    errors: dict[str, str] = {}
    left = list(files)
    inputs = page.locator("input[type='file']")
    for index in range(inputs.count()):
        if not left:
            break
        field = inputs.nth(index)
        chosen: JobFile | None = None
        try:
            described = _description(field)
            chosen = next(
                (f for f in left if any(m in described for m in FILE_MARKERS[f.kind])),
                None,
            ) or _unnamed(left, described)
            if chosen is None:
                continue
            field.set_input_files(
                FilePayload(
                    name=chosen.name, mimeType="application/pdf", buffer=chosen.content
                )
            )
        except PlaywrightError as error:
            errors.setdefault(
                chosen.kind if chosen else "cv", f"échec ({_first_line(error)})"
            )
            continue
        placed.append(FILE_KINDS[chosen.kind])
        left.remove(chosen)
    missing = [
        f"{FILE_KINDS[f.kind]} : {errors.get(f.kind, 'aucun champ de fichier pour lui')}"
        for f in left
    ]
    return placed, missing


def _description(field: Locator) -> str:
    attributes = ("name", "id", "aria-label", "accept", "title")
    parts = [field.get_attribute(name) or "" for name in attributes]
    labels: str = field.evaluate(
        "e => [...(e.labels || [])].map(l => l.textContent).join(' ')"
    )
    return " ".join([*parts, labels]).lower()


def _unnamed(left: list[JobFile], described: str) -> JobFile | None:
    """A field naming no document takes the next file (the CV first), unless it names another kind of file."""
    names_any = any(
        m in described for markers in FILE_MARKERS.values() for m in markers
    )
    return None if names_any else left[0]


def _first_line(error: PlaywrightError) -> str:
    return (
        error.message.strip().splitlines()[0]
        if error.message.strip()
        else "erreur du navigateur"
    )


# The tabs of the lecture assistée (decision E5).


class BrowserFailedError(Exception):
    """The browser could not do what was asked; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


TAB_CLOSED = "l'onglet de l'annonce a été fermé, rouvre-la dans le navigateur"
TAB_UNKNOWN = "cet onglet n'est plus connu du poste (relancé depuis ?), rouvre l'annonce dans le navigateur"


class Tabs:
    """The tabs opened for a reading, named by a random token. Used by the browser's thread only."""

    def __init__(self) -> None:
        self._pages: dict[str, Page] = {}

    def open(self, window: BrowserContext, url: str) -> str:
        """``url`` in a new tab, brought to the front; the tab stays open for the user and their challenge."""
        self._pages = {
            tab: page for tab, page in self._pages.items() if not page.is_closed()
        }
        page = window.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=OPEN_TIMEOUT_MS)
        page.bring_to_front()
        tab = secrets.token_urlsafe(16)
        self._pages[tab] = page
        return tab

    def read(self, tab: str) -> ShownPage:
        """The page shown in ``tab`` now: its address and its HTML as drawn (``page.content``, not the source)."""
        page = self._pages.get(tab)
        if page is None:
            raise BrowserFailedError(TAB_UNKNOWN)
        if page.is_closed():
            del self._pages[tab]
            raise BrowserFailedError(TAB_CLOSED)
        shown = ShownPage(page.url, page.content())
        if len(shown.html.encode()) > MAX_PAGE_BYTES:
            raise BrowserFailedError(
                f"la page affichée est trop lourde (plus de {MAX_PAGE_BYTES // 1_000_000} Mo)"
            )
        return shown

    def forget(self) -> None:
        """The window was closed: so were its tabs."""
        self._pages.clear()


# The browser: one thread owns Playwright (its objects belong to the thread that made them).


class BrowserWorker:
    """A visible Chromium with a persistent profile, opened at the first request and again if its window was
    closed; one tab per posting or form, left open for the user. Every request runs on the browser's thread."""

    def __init__(self, profile_dir: Path, *, headless: bool = False) -> None:
        self._profile_dir = profile_dir
        self._headless = headless
        self._context: BrowserContext | None = None
        self._tabs = Tabs()
        self._tasks: queue.Queue[tuple[Callable[[Playwright], Any], Future[Any]]] = (
            queue.Queue()
        )
        self._thread = threading.Thread(
            target=self._run, name="navigateur", daemon=True
        )
        self._thread.start()

    def open_page(self, url: str) -> str:
        return cast(
            str, self._submit(lambda pw: self._tabs.open(self._window(pw), url))
        )

    def read_page(self, tab: str) -> ShownPage:
        return cast(ShownPage, self._submit(lambda pw: self._tabs.read(tab)))

    def prefill(self, job: PrefillJob) -> PrefillReport:
        return cast(PrefillReport, self._submit(lambda pw: self._prefill(pw, job)))

    def _submit(self, task: Callable[[Playwright], Any]) -> Any:
        done: Future[Any] = Future()
        self._tasks.put((task, done))
        # Answered before Rocky stops waiting: the user then reads the reason.
        return done.result(timeout=TIMEOUT_SECONDS - 10)

    def _run(self) -> None:
        with sync_playwright() as playwright:
            while True:
                task, done = self._tasks.get()
                try:
                    done.set_result(task(playwright))
                except BrowserFailedError as error:
                    done.set_exception(error)
                except PlaywrightError as error:
                    done.set_exception(
                        BrowserFailedError(
                            f"le navigateur a échoué ({_first_line(error)})"
                        )
                    )
                except Exception as error:  # the thread must live on: shown in the terminal and to Rocky
                    traceback.print_exc()
                    done.set_exception(
                        BrowserFailedError(f"erreur du poste ({type(error).__name__})")
                    )

    def _prefill(self, playwright: Playwright, job: PrefillJob) -> PrefillReport:
        page = self._window(playwright).new_page()
        page.goto(
            job.target_url, wait_until="domcontentloaded", timeout=OPEN_TIMEOUT_MS
        )
        page.wait_for_timeout(SETTLE_MS)
        report = fill_form(page, job)
        page.bring_to_front()
        return report

    def _window(self, playwright: Playwright) -> BrowserContext:
        """The browser window, opened again when the user has closed it (its events run on this thread)."""
        if self._context is None:
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = playwright.chromium.launch_persistent_context(
                str(self._profile_dir), headless=self._headless, no_viewport=True
            )
            self._context.on("close", self._forget)
        return self._context

    def _forget(self, _: BrowserContext) -> None:
        self._context = None
        self._tabs.forget()


# The HTTP side: only Rocky, from the loopback or from Docker, never a web page.


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset(
        f"{host}:{port}" for host in ("127.0.0.1", "localhost", "host.docker.internal")
    )


PATHS = frozenset({OPEN_PATH, READ_PATH, PREFILL_PATH})


def refusal(
    method: str, path: str, headers: Mapping[str, str], port: int
) -> tuple[int, str] | None:
    """Why a request is refused (status, French reason); None when it may go on. A page open in a browser cannot
    send JSON here without a CORS preflight, which is never answered; a DNS rebinding is stopped by ``Host``."""
    if path not in PATHS:
        return 404, "adresse inconnue"
    if method != "POST":
        return 405, "méthode refusée"
    if headers.get("Host", "").lower() not in allowed_hosts(port):
        return 403, "hôte refusé"
    if headers.get("Origin") is not None:
        return 403, "une page web ne peut pas appeler le poste"
    if (
        headers.get("Content-Type", "").split(";")[0].strip().lower()
        != "application/json"
    ):
        return 415, "JSON attendu"
    return None


@dataclass(frozen=True)
class Answer:
    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class Handlers:
    """What the workstation does for each request: the browser's, or fakes in the tests."""

    open_page: Callable[[str], str]
    read_page: Callable[[str], ShownPage]
    prefill: Callable[[PrefillJob], PrefillReport]


def answer(
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
    port: int,
    handlers: Handlers,
) -> Answer:
    """The whole request, without sockets: guards, reading of the request, the work done by ``handlers``."""
    refused = refusal(method, path, headers, port)
    if refused is not None:
        return Answer(refused[0], {"error": refused[1]})
    try:
        work = _work(path, json.loads(body), handlers)
    except ValueError as error:  # json.JSONDecodeError is a ValueError
        return Answer(400, {"error": f"demande illisible ({error})"})
    try:
        return Answer(200, work())
    except BrowserFailedError as error:
        return Answer(502, {"error": error.reason})
    except TimeoutError:
        return Answer(504, {"error": "le navigateur n'a pas fini à temps"})


def _work(path: str, data: Any, handlers: Handlers) -> Callable[[], dict[str, Any]]:
    """The work a request asks for, once read; raises ``ValueError`` for a malformed request."""
    if path == OPEN_PATH:
        url = url_to_open(data)
        return lambda: {"tab": handlers.open_page(url)}
    if path == READ_PATH:
        tab = tab_to_read(data)
        return lambda: handlers.read_page(tab).to_json()
    job = PrefillJob.from_json(data)
    return lambda: handlers.prefill(job).to_json()


def make_server(port: int, handlers: Handlers) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                found = Answer(413, {"error": "formulaire trop lourd"})
            else:
                body = self.rfile.read(length) if length else b""
                headers = dict(self.headers.items())
                found = answer(
                    self.command,
                    self.path,
                    headers,
                    body,
                    cast(ThreadingHTTPServer, self.server).server_port,
                    handlers,
                )
            content = json.dumps(found.body).encode()
            self.send_response(found.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self) -> None:  # name fixed by http.server
            self._handle()

        def do_GET(self) -> None:  # refused with its reason
            self._handle()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rocky-poste",
        description="Poste Rocky : ouvre dans un navigateur visible les annonces que Rocky doit lire.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--profil",
        type=Path,
        default=DEFAULT_PROFILE,
        help="dossier du profil du navigateur (connexions aux sites gardées)",
    )
    arguments = parser.parse_args(argv)
    worker = BrowserWorker(arguments.profil)
    server = make_server(
        arguments.port, Handlers(worker.open_page, worker.read_page, worker.prefill)
    )
    sys.stderr.write(
        f"Poste Rocky prêt sur http://127.0.0.1:{arguments.port} (profil : {arguments.profil}). "
        "Ctrl+C pour l'arrêter.\n"
    )
    try:
        # Ctrl+C is how the workstation stops.
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
