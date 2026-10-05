from __future__ import annotations

import json
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


def test_search_sends_title_and_place_and_maps_the_recorded_offers() -> None:
    replay = Replay({SEARCH: json_answer("adzuna/search.json")})

    offers = adzuna(replay).search(SearchQuery("Data analyst", "Paris"), 20)

    params = replay.params()
    assert (params["what"], params["where"]) == ("Data analyst", "Paris")
    assert params["results_per_page"] == "20"
    assert params["sort_by"] == "date"
    assert len(offers) == 5
    first = offers[0]
    assert first.source is SourceCode.ADZUNA
    assert (first.external_id, first.title) == (
        "5897779542",
        "Data Analyst Pricing - Freelance",
    )
    assert (first.company, first.location) == (
        "Collective.work",
        "8ème Arrondissement, Paris",
    )
    assert first.contract == "contract full_time"
    assert first.sector is None  # "Unknown" is a placeholder
    assert first.published_on == date(2026, 9, 25)
    # Tracking parameters go, among them the application identifier (utm_source).
    assert first.url == "https://www.adzuna.fr/details/5897779542"
    # The API gives a 500-character snippet.
    assert first.description.endswith("…")
    assert first.description_complete is False
    assert first.incomplete_reason == EXCERPT_REASON
    # A freelance day rate comes as salary_min: kept as a number, without a period (read in C3).
    freelance = offers[3]
    assert (freelance.salary_min, freelance.salary_max, freelance.salary_period) == (
        450.0,
        450.0,
        None,
    )


def test_a_salary_estimated_by_adzuna_is_not_kept() -> None:
    job = {
        "id": "1",
        "title": "Analyste",
        "redirect_url": "https://www.adzuna.fr/details/1",
        "salary_min": 38540.12,
        "salary_max": 38540.12,
        "salary_is_predicted": "1",
    }
    replay = Replay({SEARCH: answer(json.dumps({"results": [job]}))})

    estimated = adzuna(replay).search(SearchQuery("Analyste"), 20)[0]

    assert (estimated.salary_min, estimated.salary_max, estimated.salary_currency) == (
        None,
        None,
        None,
    )


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
