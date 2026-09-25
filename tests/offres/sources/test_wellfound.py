from __future__ import annotations

from datetime import date

import pytest

from rocky.offres.sources.model import (
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.offres.sources.wellfound import WellfoundSource, parse_page, slug
from tests.offres.sources.replay import Replay, answer, html_answer

ROLE_IN_PARIS = ("GET", "/role/l/data-analyst/paris")


def test_search_reads_the_recorded_role_page_of_a_place() -> None:
    replay = Replay({ROLE_IN_PARIS: html_answer("wellfound/role-location.html")})

    offers = WellfoundSource(replay.http()).search(
        SearchQuery("Data analyst", "Paris"), 20
    )

    assert len(offers) == 6
    first = offers[0]
    assert first.source is SourceCode.WELLFOUND
    assert first.external_id == "3122521"
    assert first.title == "Senior Data Consultant - Paris"
    assert (
        first.url == "https://wellfound.com/jobs/3122521-senior-data-consultant-paris"
    )
    assert (first.company, first.location, first.contract) == (
        "Artefact",
        "Paris",
        "full-time",
    )
    assert first.published_on == date(2024, 10, 9)
    assert first.description.startswith("**Qui sommes-nous?**")
    assert first.description_complete is True


def test_a_role_page_without_place_is_asked_for_a_query_without_location() -> None:
    replay = Replay(
        {("GET", "/role/r/data-analyst"): html_answer("wellfound/role-location.html")}
    )

    WellfoundSource(replay.http()).search(SearchQuery("Data analyst"), 20)

    assert replay.requests[0].url.path == "/role/r/data-analyst"


def test_a_role_or_place_unknown_to_wellfound_is_skipped() -> None:
    replay = Replay({("GET", "/role/l/data-analyst/saint-malo"): answer(status=404)})

    with pytest.raises(
        QuerySkippedError, match="pas de page pour « Data analyst » à « Saint-Malo »"
    ):
        WellfoundSource(replay.http()).search(
            SearchQuery("Data analyst", "Saint-Malo"), 20
        )


def test_a_cdn_refusal_stops_without_any_fallback() -> None:
    replay = Replay({ROLE_IN_PARIS: answer(status=403, content_type="text/html")})

    with pytest.raises(SourceRefusedError):
        WellfoundSource(replay.http()).search(SearchQuery("Data analyst", "Paris"), 20)

    assert len(replay.requests) == 1


def test_a_page_without_its_data_fails_readably() -> None:
    with pytest.raises(SourceFailedError, match="n'a pas fourni de données"):
        parse_page("<html><body>Maintenance</body></html>")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Data analyst", "data-analyst"),
        ("Île-de-France", "ile-de-france"),
        ("C++ / Qt", "c-qt"),
    ],
)
def test_slug(value: str, expected: str) -> None:
    assert slug(value) == expected
