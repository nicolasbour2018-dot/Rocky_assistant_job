"""Importing a link: every outcome gives a preview or its reason, never silence."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import httpx2
import pytest

from rocky.offres.imports.model import ImportMethod, ImportOutcome
from rocky.offres.imports.usecases import (
    NOT_FOUND_REASON,
    PASTE_HINT,
    TECHNICAL_REASON,
    import_link,
    link_sources,
)
from rocky.offres.sources.apec import DETAIL_URL, NO_DETAIL_REASON, ApecSource
from rocky.offres.sources.http import Page
from rocky.offres.sources.model import (
    LinkSource,
    NotFoundError,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.offres.sources.wttj import WelcomeToTheJungleSource
from tests.offres.sources.replay import Replay, answer, json_answer

TODAY = date(2026, 9, 25)
HELLOWORK = "https://www.hellowork.com/fr-fr/emplois/77695894.html"
APEC = (
    "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/179271987W"
)
APEC_DETAIL = ("GET", httpx2.URL(DETAIL_URL).path)
DATA = Path(__file__).parent / "data"


class FakeReader:
    """Gives one page, or raises one error; keeps the addresses it was asked."""

    def __init__(
        self, page: Page | None = None, error: Exception | None = None
    ) -> None:
        self._page = page
        self._error = error
        self.asked: list[str] = []

    def get_page(self, url: str) -> Page:
        self.asked.append(url)
        if self._error is not None:
            raise self._error
        assert self._page is not None
        return self._page


def hellowork_page() -> Page:
    return Page(HELLOWORK, (DATA / "hellowork.com/posting.html").read_text())


def test_a_posting_page_gives_its_preview() -> None:
    reader = FakeReader(hellowork_page())

    result = import_link(f"  {HELLOWORK}#postuler ", reader, {}, today=TODAY)

    assert result.outcome == ImportOutcome.OK
    assert result.reason is None
    assert result.preview is not None
    assert result.preview.method == ImportMethod.JSON_LD
    assert result.preview.offer.title == "Data Analyst Banque Expérimenté H/F"
    assert reader.asked == [HELLOWORK]


def test_an_invalid_link_gives_its_reason_and_is_never_read() -> None:
    reader = FakeReader(hellowork_page())

    result = import_link("pas-une-url", reader, {}, today=TODAY)

    assert result.outcome == ImportOutcome.INVALID
    assert result.reason == "Le lien doit commencer par http:// ou https://."
    assert result.preview is None
    assert reader.asked == []


def test_a_refusal_gives_its_reason_and_offers_to_paste() -> None:
    refusal = SourceRefusedError(
        "Refusé par hellowork.com : la plateforme bloque les requêtes automatiques (HTTP 403)."
    )

    result = import_link(HELLOWORK, FakeReader(error=refusal), {}, today=TODAY)

    assert result.outcome == ImportOutcome.REFUSED
    assert result.reason == f"{refusal.reason} {PASTE_HINT}"


def test_a_missing_posting_says_it_no_longer_exists() -> None:
    reader = FakeReader(
        error=NotFoundError("hellowork.com n'a pas de page (HTTP 404).")
    )

    result = import_link(HELLOWORK, reader, {}, today=TODAY)

    assert result.outcome == ImportOutcome.FAILED
    assert result.reason == NOT_FOUND_REASON


def test_a_failure_keeps_its_own_reason() -> None:
    reader = FakeReader(
        error=SourceFailedError("hellowork.com ne répond pas (délai dépassé).")
    )

    result = import_link(HELLOWORK, reader, {}, today=TODAY)

    assert result.outcome == ImportOutcome.FAILED
    assert result.reason == "hellowork.com ne répond pas (délai dépassé)."


def test_a_page_with_nothing_to_read_is_a_failure_with_its_reason() -> None:
    reader = FakeReader(
        Page(HELLOWORK, "<html><body><div id='app'></div></body></html>")
    )

    result = import_link(HELLOWORK, reader, {}, today=TODAY)

    assert result.outcome == ImportOutcome.FAILED
    assert result.reason is not None
    assert result.reason.startswith("La page ne contient aucun texte lisible")


def test_an_unexpected_error_is_a_failure_and_its_trace_is_logged_without_the_link(
    caplog: pytest.LogCaptureFixture,
) -> None:
    link = f"{HELLOWORK}?token=secret-123"
    reader = FakeReader(error=KeyError("boom"))

    with caplog.at_level(logging.ERROR):
        result = import_link(link, reader, {}, today=TODAY)

    assert result.outcome == ImportOutcome.FAILED
    assert result.reason == TECHNICAL_REASON
    assert "KeyError" in caplog.text  # the trace is kept
    assert "secret-123" not in caplog.text


def apec_sources(replay: Replay) -> dict[str, LinkSource]:
    http = replay.http()
    return link_sources([ApecSource(http), WelcomeToTheJungleSource(http)])


def test_only_the_sources_with_empty_pages_are_read_through_their_detail() -> None:
    assert set(apec_sources(Replay({}))) == {SourceCode.APEC}


def test_an_apec_link_is_read_through_the_public_detail() -> None:
    replay = Replay({APEC_DETAIL: json_answer("apec/detail.json")})
    reader = FakeReader()

    result = import_link(APEC, reader, apec_sources(replay), today=TODAY)

    assert result.outcome == ImportOutcome.OK
    assert result.preview is not None
    assert result.preview.method == ImportMethod.PLATFORM_DETAIL
    assert result.preview.offer.title == "Data Analyst / BI Analyst – Power BI F/H"
    assert result.preview.offer.description_complete is True
    assert replay.params() == {"numeroOffre": "179271987W"}
    assert reader.asked == []  # the page itself is an empty shell


def test_an_apec_detail_refused_by_datadome_offers_to_paste() -> None:
    replay = Replay(
        {
            APEC_DETAIL: json_answer(
                "apec/detail-refused.json", 403, {"x-datadome": "protected"}
            )
        }
    )

    result = import_link(APEC, FakeReader(), apec_sources(replay), today=TODAY)

    assert result.outcome == ImportOutcome.REFUSED
    assert result.reason is not None
    assert result.reason.startswith("Refusé par Apec")
    assert result.reason.endswith(PASTE_HINT)


def test_an_empty_apec_detail_leaves_the_offer_incomplete_with_its_reason() -> None:
    replay = Replay({APEC_DETAIL: answer("{}")})

    result = import_link(APEC, FakeReader(), apec_sources(replay), today=TODAY)

    assert result.preview is not None
    assert result.preview.offer.description_complete is False
    assert result.preview.offer.incomplete_reason == NO_DETAIL_REASON


def test_an_apec_link_that_is_not_a_posting_is_invalid() -> None:
    replay = Replay({})

    result = import_link(
        "https://www.apec.fr/candidat.html",
        FakeReader(),
        apec_sources(replay),
        today=TODAY,
    )

    assert result.outcome == ImportOutcome.INVALID
    assert replay.requests == []
