from __future__ import annotations

from datetime import date

import httpx2
import pytest

from rocky.offres.sources.apec import (
    DETAIL_URL,
    EXCERPT_REASON,
    PLACES_URL,
    SEARCH_URL,
    ApecSource,
)
from rocky.offres.sources.model import (
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceRefusedError,
)
from tests.offres.sources.replay import Replay, answer, json_answer

SEARCH = ("POST", httpx2.URL(SEARCH_URL).path)
PLACES = ("GET", httpx2.URL(PLACES_URL).path)
DETAIL = ("GET", httpx2.URL(DETAIL_URL).path)


def places_of_paris(request: httpx2.Request) -> httpx2.Response:
    """Apec's reference, as recorded: "Paris" alone does not come out, "Paris -" does."""
    name = (
        "places-paris-dash.json"
        if request.url.params["q"].endswith("-")
        else "places-paris.json"
    )
    return json_answer(f"apec/{name}")(request)


def test_search_filters_on_apec_location_and_maps_the_recorded_offers() -> None:
    replay = Replay({PLACES: places_of_paris, SEARCH: json_answer("apec/search.json")})

    offers = ApecSource(replay.http()).search(SearchQuery("Data analyst", "Paris"), 20)

    assert [replay.params(i)["q"] for i in (0, 1)] == ["Paris", "Paris -"]
    payload = replay.body()
    assert isinstance(payload, dict)
    assert payload["motsCles"] == "Data analyst"
    assert payload["lieux"] == ["75"]
    assert payload["pagination"] == {"range": 20, "startIndex": 0}
    assert len(offers) == 5
    first = offers[0]
    assert first.source is SourceCode.APEC
    assert first.external_id == "179271987W"
    assert first.title == "Data Analyst / BI Analyst – Power BI F/H"
    assert first.company == "BRAIN LOGIC"
    assert first.location == "Paris 11 - 75"
    assert first.url.endswith("/detail-offre/179271987W")
    assert first.salary_text == "A négocier"
    assert first.published_on == date(2026, 9, 25)
    # The search gives an excerpt: kept, and said to be incomplete.
    assert first.description.endswith("...")
    assert first.description_complete is False
    assert first.incomplete_reason == EXCERPT_REASON
    assert offers[2].salary_text == "50 - 80 k€ brut annuel"


def test_a_location_is_resolved_once_per_collection() -> None:
    replay = Replay({PLACES: places_of_paris, SEARCH: json_answer("apec/search.json")})
    source = ApecSource(replay.http())

    source.search(SearchQuery("Data analyst", "Paris"), 20)
    source.search(SearchQuery("Data scientist", "paris"), 20)

    assert [request.url.path for request in replay.requests].count(PLACES[1]) == 2


def test_a_query_without_location_searches_all_of_france() -> None:
    replay = Replay({SEARCH: json_answer("apec/search.json")})

    ApecSource(replay.http()).search(SearchQuery("Data analyst"), 20)

    payload = replay.body()
    assert isinstance(payload, dict)
    assert payload["lieux"] == []


def test_an_unknown_location_is_skipped_with_its_reason() -> None:
    replay = Replay({PLACES: answer("[]")})

    with pytest.raises(
        QuerySkippedError, match="Lieu non reconnu par Apec : « Télétravail »"
    ):
        ApecSource(replay.http()).search(SearchQuery("Data analyst", "Télétravail"), 20)

    assert all(request.url.path == PLACES[1] for request in replay.requests)


def test_an_unknown_location_is_asked_once_for_all_the_job_titles() -> None:
    replay = Replay({PLACES: answer("[]")})
    source = ApecSource(replay.http())

    for title in ("Data analyst", "Data scientist", "BI analyst"):
        with pytest.raises(QuerySkippedError, match="Eure et Loire"):
            source.search(SearchQuery(title, "Eure et Loire"), 20)

    assert [replay.params(i)["q"] for i in range(len(replay.requests))] == [
        "Eure et Loire",
        "Eure et Loire -",
    ]


def test_an_ambiguous_location_is_skipped_and_asks_for_the_department() -> None:
    places = (
        '[{"lieuDisplay": "Saint-Denis - 93", "lieuId": 1, "lieuType": "FR_COMMUNE"},'
        ' {"lieuDisplay": "Saint-Denis - 974", "lieuId": 2, "lieuType": "FR_COMMUNE"}]'
    )
    replay = Replay({PLACES: answer(places)})

    with pytest.raises(QuerySkippedError, match="Lieu ambigu pour Apec") as error:
        ApecSource(replay.http()).search(SearchQuery("Data analyst", "Saint-Denis"), 20)

    assert "« Saint-Denis - 93 », « Saint-Denis - 974 »" in error.value.reason


def test_a_region_wins_over_a_wider_grouping_of_the_same_name() -> None:
    places = (
        '[{"lieuDisplay": "Ile de France", "lieuId": 800, "lieuType": "FR_GRANDE_REGION"},'
        ' {"lieuDisplay": "Ile-de-France", "lieuId": 711, "lieuType": "FR_REGION"}]'
    )
    replay = Replay({PLACES: answer(places), SEARCH: json_answer("apec/search.json")})

    ApecSource(replay.http()).search(SearchQuery("Data analyst", "Île-de-France"), 20)

    payload = replay.body()
    assert isinstance(payload, dict)
    assert payload["lieux"] == ["711"]


def test_the_detail_refused_by_datadome_stops_as_a_refusal() -> None:
    replay = Replay(
        {
            PLACES: places_of_paris,
            SEARCH: json_answer("apec/search.json"),
            DETAIL: json_answer(
                "apec/detail-refused.json", 403, {"x-datadome": "protected"}
            ),
        }
    )
    source = ApecSource(replay.http())
    offer = source.search(SearchQuery("Data analyst", "Paris"), 1)[0]

    with pytest.raises(SourceRefusedError, match=r"Refusé par Apec .* \(HTTP 403\)"):
        source.complete(offer)

    assert replay.params() == {"numeroOffre": "179271987W"}


def test_the_detail_when_apec_lets_it_through_gives_the_full_description() -> None:
    # Reconstructed dataset (see data/README.md): Apec refused every detail during the capture.
    replay = Replay(
        {
            SEARCH: json_answer("apec/search.json"),
            DETAIL: json_answer("apec/detail.json"),
        }
    )
    source = ApecSource(replay.http())
    offer = source.search(SearchQuery("Data analyst"), 1)[0]

    completed = source.complete(offer)

    assert completed.description_complete is True
    assert completed.incomplete_reason is None
    assert completed.description.startswith("Au sein de la Digital Factory")
    assert "- Concevoir des tableaux de bord Power BI" in completed.description
    assert "Profil recherché\nVous maîtrisez SQL" in completed.description
