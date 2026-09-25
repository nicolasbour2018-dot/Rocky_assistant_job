from __future__ import annotations

from datetime import date

import httpx2
import pytest

from rocky.offres.sources.linkedin import (
    NO_DESCRIPTION_REASON,
    SEARCH_URL,
    LinkedInSource,
)
from rocky.offres.sources.model import (
    SearchQuery,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from tests.offres.sources.replay import Replay, answer, html_answer

SEARCH = ("GET", httpx2.URL(SEARCH_URL).path)


def test_search_reads_the_recorded_public_cards() -> None:
    replay = Replay({SEARCH: html_answer("linkedin/search.html")})

    offers = LinkedInSource(replay.http()).search(
        SearchQuery("Data analyst", "Paris"), 20
    )

    params = replay.params()
    assert (params["keywords"], params["location"]) == ("Data analyst", "Paris")
    assert params["f_TPR"] == "r2592000"
    assert len(offers) == 10
    first = offers[0]
    assert first.source is SourceCode.LINKEDIN
    assert first.external_id == "4423942204"
    assert first.title == "Data Analyst Power BI / GCP H/F"
    assert (first.company, first.location) == ("NEXTON", "Paris")
    assert first.published_on == date(2026, 9, 19)
    # Tracking parameters are dropped from the address.
    assert first.url == (
        "https://fr.linkedin.com/jobs/view/data-analyst-power-bi-gcp-h-f-at-nexton-4423942204"
    )
    assert first.description == ""
    assert first.incomplete_reason == NO_DESCRIPTION_REASON


def test_a_query_without_location_searches_france() -> None:
    replay = Replay({SEARCH: html_answer("linkedin/search.html")})

    offers = LinkedInSource(replay.http()).search(SearchQuery("Data analyst"), 4)

    assert replay.params()["location"] == "France"
    assert len(offers) == 4


def test_an_empty_answer_is_no_result() -> None:
    replay = Replay({SEARCH: answer("", content_type="text/html")})

    assert LinkedInSource(replay.http()).search(SearchQuery("Data analyst"), 20) == []


def test_a_sign_in_wall_is_a_refusal_not_zero_offers() -> None:
    wall = '<html><body><form action="https://www.linkedin.com/uas/login-submit"></form></body></html>'
    replay = Replay({SEARCH: answer(wall, content_type="text/html")})

    with pytest.raises(SourceRefusedError, match="demande de se connecter"):
        LinkedInSource(replay.http()).search(SearchQuery("Data analyst"), 20)


def test_a_page_without_cards_is_a_visible_failure() -> None:
    replay = Replay(
        {
            SEARCH: answer(
                "<html><body><ul></ul></body></html>", content_type="text/html"
            )
        }
    )

    with pytest.raises(SourceFailedError, match="page sans liste d'offres"):
        LinkedInSource(replay.http()).search(SearchQuery("Data analyst"), 20)
