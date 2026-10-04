"""The Rocky workstation (decision D5): what Rocky and the workstation exchange, the guards of the workstation, and
the filling of a form in a headless Chromium — which never submits it. No network: a mocked transport, or the
loopback of the test itself."""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Callable, Iterator

import httpx2
import pytest
from playwright.sync_api import Page, sync_playwright

from rocky.system.workstation import (
    NOT_RUNNING,
    JobFile,
    PrefillJob,
    PrefillReport,
    WorkstationClient,
    WorkstationUnavailableError,
)
from rocky.system.workstation_host import (
    PrefillFailedError,
    allowed_hosts,
    answer,
    fill_form,
    make_server,
)

CV = JobFile("cv", "CV_Camille_Martin_FR.pdf", b"%PDF-cv")
LETTER = JobFile("letter", "Lettre_Camille_Martin_FR.pdf", b"%PDF-letter")
JOB = PrefillJob(
    "https://jobs.acme.fr/apply?ref=1",
    (
        ("full_name", "Camille Martin"),
        ("email", "camille@example.fr"),
        ("phone", "0601020304"),
        ("city", "Chartres"),
        ("github", "https://github.com/camille"),
        ("message", "Bonjour, je vous propose ma candidature."),
    ),
    (CV, LETTER),
)
PORT = 8765
HEADERS = {"Host": f"127.0.0.1:{PORT}", "Content-Type": "application/json"}
REPORT = PrefillReport(("Nom complet",), ("GitHub : champ introuvable",))


# What they exchange.


def test_a_job_goes_and_comes_back_as_it_was() -> None:
    assert PrefillJob.from_json(json.loads(json.dumps(JOB.to_json()))) == JOB


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(target_url="file:///etc/passwd"),
        lambda data: data["fields"].append(["password", "x"]),
        lambda data: data["files"][0].update(
            content=base64.b64encode(b"other").decode()
        ),
        lambda data: data["files"][0].update(name="../cv.pdf"),
        lambda data: data["files"][0].update(kind="photo"),
    ],
)
def test_a_malformed_or_altered_job_is_refused(
    change: Callable[[dict[str, object]], None],
) -> None:
    data = JOB.to_json()
    change(data)

    with pytest.raises(ValueError):
        PrefillJob.from_json(data)


def client(handler: Callable[[httpx2.Request], httpx2.Response]) -> WorkstationClient:
    return WorkstationClient(
        "http://poste:8765/", transport=httpx2.MockTransport(handler)
    )


def test_the_client_hands_the_job_and_reads_the_report() -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=REPORT.to_json())

    assert client(handler).prefill(JOB) == REPORT
    (request,) = sent
    assert (request.method, str(request.url)) == (
        "POST",
        "http://poste:8765/preremplir",
    )
    assert request.headers["content-type"] == "application/json"
    assert "origin" not in request.headers
    assert PrefillJob.from_json(json.loads(request.content)) == JOB


def raising(error: Exception) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (raising(httpx2.ConnectError("refused")), NOT_RUNNING),
        (raising(httpx2.ReadTimeout("slow")), "à temps"),
        (
            lambda request: httpx2.Response(
                502, json={"error": "la page ne s'est pas ouverte"}
            ),
            "refusé le formulaire : la page ne s'est pas ouverte",
        ),
        (lambda request: httpx2.Response(200, text="<html>"), "illisible"),
        (lambda request: httpx2.Response(200, json={"filled": [1]}), "illisible"),
    ],
)
def test_a_workstation_that_does_not_take_the_form_says_why(
    handler: Callable[[httpx2.Request], httpx2.Response], reason: str
) -> None:
    with pytest.raises(WorkstationUnavailableError) as raised:
        client(handler).prefill(JOB)

    assert reason in raised.value.reason


# The guards of the workstation, without sockets nor browser.


def ok(job: PrefillJob) -> PrefillReport:
    return REPORT


def ask(
    headers: dict[str, str] = HEADERS,
    method: str = "POST",
    path: str = "/preremplir",
    body: bytes | None = None,
    run: Callable[[PrefillJob], PrefillReport] = ok,
) -> tuple[int, dict[str, object]]:
    found = answer(
        method,
        path,
        headers,
        json.dumps(JOB.to_json()).encode() if body is None else body,
        PORT,
        run,
    )
    return found.status, found.body


def test_rocky_from_docker_or_the_loopback_is_answered() -> None:
    assert allowed_hosts(PORT) == {
        "127.0.0.1:8765",
        "localhost:8765",
        "host.docker.internal:8765",
    }
    assert ask() == (200, REPORT.to_json())
    assert ask({**HEADERS, "Host": "host.docker.internal:8765"})[0] == 200


@pytest.mark.parametrize(
    ("headers", "method", "path", "status"),
    [
        (
            {**HEADERS, "Host": "evil.example:8765"},
            "POST",
            "/preremplir",
            403,
        ),  # DNS rebinding
        (
            {**HEADERS, "Origin": "https://evil.example"},
            "POST",
            "/preremplir",
            403,
        ),  # a web page
        (
            {**HEADERS, "Content-Type": "text/plain"},
            "POST",
            "/preremplir",
            415,
        ),  # a form without preflight
        (HEADERS, "GET", "/preremplir", 405),
        (HEADERS, "POST", "/autre", 404),
    ],
)
def test_anything_but_rocky_is_refused(
    headers: dict[str, str], method: str, path: str, status: int
) -> None:
    called: list[PrefillJob] = []

    def run(job: PrefillJob) -> PrefillReport:
        called.append(job)
        return REPORT

    found = ask(headers, method, path, run=run)

    assert found[0] == status
    assert called == []


def test_a_malformed_job_or_a_page_that_fails_is_answered_with_its_reason() -> None:
    def failing(job: PrefillJob) -> PrefillReport:
        raise PrefillFailedError("la page ne s'est pas ouverte (timeout)")

    assert ask(body=b"{")[0] == 400
    assert ask(run=failing) == (
        502,
        {"error": "la page ne s'est pas ouverte (timeout)"},
    )


def test_the_server_answers_rocky_s_client_on_the_loopback() -> None:
    server = make_server(0, ok)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        assert WorkstationClient(f"http://127.0.0.1:{port}").prefill(JOB) == REPORT
    finally:
        server.shutdown()
        server.server_close()


# The filling, in a headless Chromium.

FORM = """<!doctype html><html><body>
<form id="apply" onsubmit="window.submitted = true; return false;">
  <label>Nom complet <input name="candidate_fullname"></label>
  <label for="mail">Adresse e-mail</label><input id="mail" type="email">
  <label>Téléphone <input name="tel_number" value="0699999999"></label>
  <label>Ville <input name="ville"></label>
  <label>Lettre de motivation (fichier) <input type="file" name="lettre_motivation"></label>
  <label>CV <input type="file" name="resume"></label>
  <label>Votre message <textarea name="message"></textarea></label>
  <button type="submit">Envoyer</button>
</form>
<script>window.submitted = false;</script>
</body></html>"""


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser.new_page()
        finally:
            browser.close()


def test_the_form_is_filled_and_never_submitted(page: Page) -> None:
    page.set_content(FORM)

    report = fill_form(page, JOB)

    assert page.input_value("[name=candidate_fullname]") == "Camille Martin"
    assert page.input_value("#mail") == "camille@example.fr"
    assert page.input_value("[name=ville]") == "Chartres"
    assert page.input_value("[name=message]").startswith("Bonjour")
    # A field the site or the user filled is left as it is.
    assert page.input_value("[name=tel_number]") == "0699999999"
    names = page.evaluate(
        "[...document.querySelectorAll('input[type=file]')].map(i => i.files[0] && i.files[0].name)"
    )
    assert names == ["Lettre_Camille_Martin_FR.pdf", "CV_Camille_Martin_FR.pdf"]
    assert page.evaluate("window.submitted") is False
    assert set(report.filled) == {
        "Nom complet",
        "E-mail",
        "Ville",
        "Message d'accompagnement",
        "CV",
        "Lettre",
    }
    assert set(report.missing) == {
        "Téléphone : déjà rempli, laissé tel quel",
        "GitHub : champ introuvable",
    }


def test_a_file_without_a_field_is_reported(page: Page) -> None:
    page.set_content("<form><input type='file' name='cv'></form>")

    report = fill_form(page, PrefillJob("https://a.fr", (), (CV, LETTER)))

    assert report.filled == ("CV",)
    assert report.missing == ("Lettre : aucun champ de fichier pour lui",)
