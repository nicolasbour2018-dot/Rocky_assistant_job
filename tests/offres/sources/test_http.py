from __future__ import annotations

import logging
import socket

import httpx2
import pytest

from rocky.offres.sources.http import Page, PublicHttp, is_public_address, resolve
from rocky.offres.sources.model import (
    InvalidLinkError,
    NotFoundError,
    SourceFailedError,
    SourceRefusedError,
)
from tests.offres.sources.replay import Answer, Replay, answer

URL = "https://jobs.example/search"
ROUTE = ("GET", "/search")
KEY = "k-123-secret"


def get(replay: Replay) -> object:
    return replay.http().get_json("Exemple", URL, params={"app_key": KEY})


@pytest.mark.parametrize("status", [403, 429, 999])
def test_a_refusal_status_is_a_refusal_and_is_never_retried(status: int) -> None:
    replay = Replay({ROUTE: answer(status=status)})

    with pytest.raises(SourceRefusedError) as error:
        get(replay)

    assert error.value.reason == (
        "Refusé par Exemple : la plateforme bloque les requêtes automatiques "
        f"(HTTP {status})."
    )
    assert len(replay.requests) == 1


def test_a_cloudflare_challenge_is_a_refusal_whatever_its_status() -> None:
    replay = Replay({ROUTE: answer(status=503, headers={"cf-mitigated": "challenge"})})

    with pytest.raises(SourceRefusedError):
        get(replay)


def test_the_datadome_marker_alone_is_not_a_refusal() -> None:
    # Apec marks every answer DataDome lets through with this header (recorded on 25/09/2026).
    replay = Replay({ROUTE: answer("[]", headers={"x-datadome": "protected"})})

    assert get(replay) == []


def test_a_missing_page_is_a_readable_failure() -> None:
    replay = Replay({ROUTE: answer(status=404)})

    with pytest.raises(NotFoundError, match=r"HTTP 404"):
        get(replay)


def test_a_server_error_is_a_failure_that_never_quotes_the_address() -> None:
    replay = Replay({ROUTE: answer(status=500)})

    with pytest.raises(SourceFailedError) as error:
        get(replay)

    assert error.value.reason == "Exemple a répondu par une erreur (HTTP 500)."
    assert KEY not in error.value.reason


def test_an_unreadable_body_is_a_failure() -> None:
    replay = Replay({ROUTE: answer("<html>")})

    with pytest.raises(SourceFailedError, match="réponse illisible"):
        get(replay)


def test_an_empty_body_is_no_data() -> None:
    replay = Replay({ROUTE: answer(status=204)})

    assert get(replay) is None


def raise_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out", request=request)


def raise_network_error(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)


def test_a_timeout_is_a_failure() -> None:
    replay = Replay({ROUTE: raise_timeout})

    with pytest.raises(SourceFailedError, match="délai dépassé"):
        get(replay)


def test_a_network_error_is_logged_by_class_without_the_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    replay = Replay({ROUTE: raise_network_error})

    with caplog.at_level(logging.DEBUG), pytest.raises(SourceFailedError) as error:
        get(replay)

    assert error.value.reason == "Exemple est injoignable (erreur réseau)."
    assert "ConnectError" in caplog.text
    assert KEY not in caplog.text
    assert KEY not in error.value.reason


def test_requests_to_one_host_are_paused() -> None:
    now = [100.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    replay = Replay({ROUTE: answer("[]"), ("GET", "/other"): answer("[]")})
    http = PublicHttp(
        transport=httpx2.MockTransport(replay._handle),
        pause_seconds=2.0,
        clock=lambda: now[0],
        sleep=sleep,
    )

    http.get_json("Exemple", URL)
    now[0] += 0.5
    http.get_json("Exemple", URL)
    http.get_json("Autre", "https://other.example/other")

    assert waits == [1.5]


# Posting pages given by the user (import by URL, step C2).

PAGE = "https://www.site.example/offre/1"
PAGE_ROUTE = ("GET", "/offre/1")
HTML = "<html><body><h1>Data analyst</h1></body></html>"


def page_answer(
    content: str = HTML,
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
) -> Answer:
    return answer(content, status, content_type=content_type)


def redirect(location: str) -> Answer:
    return answer(status=302, headers={"location": location})


def test_a_page_is_read_with_its_address_after_redirections() -> None:
    replay = Replay({("GET", "/o/1"): redirect("/offre/1"), PAGE_ROUTE: page_answer()})

    page = replay.http().get_page("https://www.site.example/o/1")

    assert page == Page(PAGE, HTML)
    assert len(replay.requests) == 2


def test_a_redirection_to_a_private_address_is_never_followed() -> None:
    replay = Replay({PAGE_ROUTE: redirect("http://intranet.site.example/admin")})
    addresses = {
        "www.site.example": ["93.184.215.14"],
        "intranet.site.example": ["10.0.0.7"],
    }

    with pytest.raises(InvalidLinkError) as error:
        replay.http(resolver=lambda host: addresses[host]).get_page(PAGE)

    assert error.value.reason == (
        "Le lien vise une adresse privée ou locale (intranet.site.example) : "
        "Rocky ne lit que des sites publics."
    )
    assert [request.url.host for request in replay.requests] == ["www.site.example"]


@pytest.mark.parametrize(
    "link",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_an_address_written_in_the_link_is_checked_without_resolving(link: str) -> None:
    replay = Replay({})
    # The replay resolver calls every name public: an address literal must not depend on it.
    with pytest.raises(InvalidLinkError):
        replay.http().get_page(link)

    assert replay.requests == []


def test_a_host_with_one_private_address_among_public_ones_is_not_read() -> None:
    replay = Replay({PAGE_ROUTE: page_answer()})

    with pytest.raises(InvalidLinkError):
        replay.http(resolver=lambda host: ["93.184.215.14", "127.0.0.1"]).get_page(PAGE)

    assert replay.requests == []


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.215.14", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("192.168.1.10", False),
        ("169.254.169.254", False),  # cloud metadata service
        ("100.64.0.1", False),  # shared address space
        ("0.0.0.0", False),
        ("224.0.0.1", False),  # multicast, which ipaddress counts as global
        ("::1", False),
        ("fd00::1", False),
        ("::ffff:127.0.0.1", False),
    ],
)
def test_only_global_unicast_addresses_are_public(address: str, public: bool) -> None:
    assert is_public_address(address) is public


def test_endless_redirections_stop_with_their_reason() -> None:
    replay = Replay({PAGE_ROUTE: redirect(PAGE)})

    with pytest.raises(SourceFailedError) as error:
        replay.http().get_page(PAGE)

    assert error.value.reason == (
        "site.example redirige sans fin (plus de 5 redirections)."
    )
    assert len(replay.requests) == 6


def test_a_refused_page_names_the_site_by_its_host() -> None:
    replay = Replay({PAGE_ROUTE: page_answer(status=403)})

    with pytest.raises(SourceRefusedError) as error:
        replay.http().get_page(PAGE)

    assert error.value.reason.startswith("Refusé par site.example :")


def test_a_pdf_is_not_a_page_and_says_what_to_do() -> None:
    replay = Replay(
        {PAGE_ROUTE: page_answer("%PDF-1.7", content_type="application/pdf")}
    )

    with pytest.raises(SourceFailedError) as error:
        replay.http().get_page(PAGE)

    assert error.value.reason == (
        "site.example renvoie un PDF, pas une page web : colle le texte de l'annonce."
    )


def test_an_answer_of_another_type_is_not_a_page() -> None:
    replay = Replay({PAGE_ROUTE: page_answer("{}", content_type="application/json")})

    with pytest.raises(
        SourceFailedError, match=r"ne renvoie pas une page web \(application/json\)"
    ):
        replay.http().get_page(PAGE)


def test_a_page_too_large_is_not_read_to_the_end() -> None:
    replay = Replay({PAGE_ROUTE: page_answer("x" * 3_000_001)})

    with pytest.raises(SourceFailedError, match="trop volumineuse"):
        replay.http().get_page(PAGE)


def test_a_page_is_decoded_with_its_charset() -> None:
    body = "<p>Rémunération</p>".encode("latin-1")
    replay = Replay(
        {
            PAGE_ROUTE: lambda request: httpx2.Response(
                200,
                content=body,
                headers={"content-type": "text/html; charset=iso-8859-1"},
            )
        }
    )

    assert replay.http().get_page(PAGE).html == "<p>Rémunération</p>"


def test_an_unknown_site_is_an_invalid_link_with_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unknown(*args: object, **kwargs: object) -> object:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    # No DNS query leaves the machine in the tests.
    monkeypatch.setattr(socket, "getaddrinfo", unknown)

    with pytest.raises(InvalidLinkError) as error:
        resolve("site-inexistant.invalid")

    assert error.value.reason == (
        "Le site site-inexistant.invalid est introuvable (nom de domaine inconnu)."
    )
