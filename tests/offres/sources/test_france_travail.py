from __future__ import annotations

from datetime import date

import httpx2
import pytest

from rocky.offres.sources.france_travail import (
    SEARCH_URL,
    TOKEN_URL,
    FranceTravailSource,
)
from rocky.offres.sources.model import (
    Availability,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from tests.offres.sources.replay import Replay, answer, json_answer

TOKEN = ("POST", httpx2.URL(TOKEN_URL).path)
SEARCH = ("GET", httpx2.URL(SEARCH_URL).path)


def source(
    replay: Replay, *, enabled: bool = True, secret: str | None = "secret"
) -> FranceTravailSource:
    return FranceTravailSource(
        replay.http(), enabled=enabled, client_id="client", client_secret=secret
    )


def test_waiting_for_access_until_enabled() -> None:
    replay = Replay({})

    assert source(replay, enabled=False).availability() is Availability.PENDING_ACCESS
    assert source(replay, secret=None).availability() is Availability.NOT_CONFIGURED
    assert source(replay).availability() is Availability.READY
    assert replay.requests == []


def test_search_asks_a_token_once_and_maps_the_offers() -> None:
    replay = Replay(
        {
            TOKEN: answer('{"access_token": "short-lived", "expires_in": 1499}'),
            SEARCH: json_answer("france_travail/search.json"),
        }
    )
    france_travail = source(replay)

    offers = france_travail.search(SearchQuery("Data analyst", "Paris"), 20)
    france_travail.search(SearchQuery("Data scientist"), 20)

    assert [request.method for request in replay.requests] == ["POST", "GET", "GET"]
    search = replay.requests[1]
    assert search.headers["Authorization"] == "Bearer short-lived"
    assert search.headers["Range"] == "offres=0-19"
    assert dict(search.url.params) == {"motsCles": "Data analyst"}
    first = offers[0]
    assert first.source is SourceCode.FRANCE_TRAVAIL
    assert (first.external_id, first.title) == ("201ABCD", "Data analyst (H/F)")
    assert (first.company, first.location) == ("EXEMPLE CONSEIL", "75 - PARIS 11")
    assert first.contract == "Contrat à durée indéterminée"
    assert first.salary_text == "Annuel de 42000.0 Euros à 48000.0 Euros sur 12.0 mois"
    assert first.application_url == "https://exemple-conseil.example/postuler/201ABCD"
    assert first.published_on == date(2026, 9, 20)
    assert first.description_complete is True
    second = offers[1]
    assert second.company is None
    assert (
        second.url
        == "https://candidat.francetravail.fr/offres/recherche/detail/201ABCE"
    )
    assert second.description_complete is False


def test_no_result_is_an_empty_answer() -> None:
    replay = Replay(
        {TOKEN: answer('{"access_token": "t"}'), SEARCH: answer(status=204)}
    )

    assert source(replay).search(SearchQuery("Data analyst"), 20) == []


def test_a_refused_token_fails_without_quoting_the_credentials() -> None:
    replay = Replay({TOKEN: answer('{"error": "invalid_client"}', status=401)})

    with pytest.raises(SourceFailedError) as error:
        source(replay).search(SearchQuery("Data analyst"), 20)

    assert error.value.reason == "France Travail a répondu par une erreur (HTTP 401)."
    assert "secret" not in error.value.reason


def test_the_token_is_asked_again_before_it_expires() -> None:
    now = [0.0]
    replay = Replay(
        {
            TOKEN: answer('{"access_token": "t", "expires_in": 1499}'),
            SEARCH: json_answer("france_travail/search.json"),
        }
    )
    france_travail = FranceTravailSource(
        replay.http(),
        enabled=True,
        client_id="client",
        client_secret="secret",
        clock=lambda: now[0],
    )

    france_travail.search(SearchQuery("Data analyst"), 20)
    now[0] = 1450.0  # less than a minute before the expiry (1499 s)
    france_travail.search(SearchQuery("Data analyst"), 20)

    assert [request.method for request in replay.requests] == [
        "POST",
        "GET",
        "POST",
        "GET",
    ]
