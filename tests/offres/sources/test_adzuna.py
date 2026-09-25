from __future__ import annotations

from datetime import date

import httpx2
import pytest

from rocky.offres.sources.adzuna import (
    EXCERPT_REASON,
    SEARCH_URL,
    AdzunaSource,
    without_tracking,
)
from rocky.offres.sources.model import (
    Availability,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from tests.offres.sources.replay import Replay, answer, json_answer

SEARCH = ("GET", httpx2.URL(SEARCH_URL).path)
KEY = "cle-secrete-123"


def adzuna(replay: Replay) -> AdzunaSource:
    return AdzunaSource(replay.http(), "app-id", KEY)


def test_without_keys_the_source_is_not_configured() -> None:
    assert AdzunaSource(Replay({}).http(), None, KEY).availability() is (
        Availability.NOT_CONFIGURED
    )
    assert adzuna(Replay({})).availability() is Availability.READY


def test_search_sends_title_and_place_and_maps_the_offers() -> None:
    replay = Replay({SEARCH: json_answer("adzuna/search.json")})

    offers = adzuna(replay).search(SearchQuery("Data analyst", "Paris"), 20)

    params = replay.params()
    assert (params["what"], params["where"]) == ("Data analyst", "Paris")
    assert params["results_per_page"] == "20"
    assert params["sort_by"] == "date"
    first, estimated = offers
    assert first.source is SourceCode.ADZUNA
    assert (first.external_id, first.title) == ("4012345678", "Data Analyst H/F")
    assert (first.company, first.location) == (
        "Exemple Conseil",
        "Paris, Ile-de-France",
    )
    assert first.contract == "permanent full_time"
    assert (first.salary_min, first.salary_max, first.salary_period) == (
        42000.0,
        48000.0,
        "year",
    )
    assert first.sector == "Emplois Informatique"
    assert first.published_on == date(2026, 9, 24)
    assert first.url == "https://www.adzuna.fr/details/4012345678"
    assert first.description_complete is False
    assert first.incomplete_reason == EXCERPT_REASON
    # A salary estimated by Adzuna is not a fact of the posting.
    assert (estimated.salary_min, estimated.salary_max, estimated.salary_currency) == (
        None,
        None,
        None,
    )
    assert estimated.url == "https://www.adzuna.fr/land/ad/4012345679?se=abc&v=1"


def test_a_query_without_location_sends_no_place() -> None:
    replay = Replay({SEARCH: json_answer("adzuna/search.json")})

    adzuna(replay).search(SearchQuery("Data analyst"), 20)

    assert "where" not in replay.params()


def test_a_refused_key_is_a_failure_that_never_quotes_the_key() -> None:
    replay = Replay({SEARCH: answer('{"exception": "AUTH_FAIL"}', status=401)})

    with pytest.raises(SourceFailedError) as error:
        adzuna(replay).search(SearchQuery("Data analyst"), 20)

    assert error.value.reason == "Adzuna a répondu par une erreur (HTTP 401)."


def test_without_tracking_keeps_the_other_parameters() -> None:
    assert (
        without_tracking("https://a.example/x?utm_source=id&se=1")
        == "https://a.example/x?se=1"
    )
