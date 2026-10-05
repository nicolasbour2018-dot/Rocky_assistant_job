from __future__ import annotations

from dataclasses import replace
from datetime import date

import httpx2
import pytest

from rocky.offres.sources.model import (
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sources.wttj import (
    NO_DESCRIPTION_REASON,
    SEARCH_URL,
    WelcomeToTheJungleSource,
)
from tests.offres.sources.replay import Replay, json_answer

SEARCH = ("GET", httpx2.URL(SEARCH_URL).path)
JOB = "ministere-des-armees-fr/jobs/expert-haut-niveau-analyste-de-donnees-data-analyst_paris"
DETAIL = ("GET", f"/api/v1/organizations/{JOB}")


def test_search_maps_the_recorded_jobs_without_description() -> None:
    replay = Replay({SEARCH: json_answer("wttj/search.json")})

    offers = WelcomeToTheJungleSource(replay.http()).search(
        SearchQuery("Data analyst"), 20
    )

    params = replay.params()
    assert params["job_title"] == "Data analyst"
    assert params["page"] == "1"
    assert len(offers) == 10
    first = offers[0]
    assert first.source is SourceCode.WTTJ
    assert first.external_id == "bb42af09-1dc9-4cfe-b686-e8a0489ac1e2"
    assert first.title == "EXPERT HAUT NIVEAU ANALYSTE DE DONNEES DATA ANALYST"
    assert first.url == (
        "https://www.welcometothejungle.com/fr/companies/ministere-des-armees-fr/jobs/"
        "expert-haut-niveau-analyste-de-donnees-data-analyst_paris"
    )
    assert (first.location, first.country) == ("Paris", "FR")
    assert (first.contract, first.remote) == ("full_time", "punctual")
    assert first.published_on == date(2026, 8, 7)
    assert first.description == ""
    assert first.incomplete_reason == NO_DESCRIPTION_REASON
    salaried = next(offer for offer in offers if offer.salary_min is not None)
    assert (salaried.salary_min, salaried.salary_period) == (167000.0, "yearly")


def test_search_takes_at_most_the_limit() -> None:
    replay = Replay({SEARCH: json_answer("wttj/search.json")})

    offers = WelcomeToTheJungleSource(replay.http()).search(
        SearchQuery("Data analyst"), 3
    )

    assert len(offers) == 3


def test_the_detail_gives_the_description_and_the_application_address() -> None:
    replay = Replay(
        {
            SEARCH: json_answer("wttj/search.json"),
            DETAIL: json_answer("wttj/detail.json"),
        }
    )
    source = WelcomeToTheJungleSource(replay.http())
    offer = source.search(SearchQuery("Data analyst"), 1)[0]

    completed = source.complete(offer)

    assert replay.params() == {"o": "bb42af09-1dc9-4cfe-b686-e8a0489ac1e2"}
    assert completed.description_complete is True
    assert completed.incomplete_reason is None
    assert completed.description.startswith(
        "Description du poste\nVos missions en quelques mots"
    )
    assert "\n- Transformer des données complexes" in completed.description
    assert "Profil recherché\n" in completed.description
    assert completed.application_url is not None
    assert completed.application_url.startswith(
        "https://choisirleservicepublic.gouv.fr/"
    )


def test_an_offer_address_that_is_not_a_wttj_job_fails_readably() -> None:
    replay = Replay({SEARCH: json_answer("wttj/search.json")})
    source = WelcomeToTheJungleSource(replay.http())
    offer = source.search(SearchQuery("Data analyst"), 1)[0]

    with pytest.raises(SourceFailedError, match="n'est pas reconnue"):
        source.complete(replace(offer, url="https://www.welcometothejungle.com/fr"))
