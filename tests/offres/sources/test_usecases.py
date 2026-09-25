from __future__ import annotations

import logging

import pytest

from rocky.offres.sources.model import (
    Availability,
    CollectedOffer,
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.offres.sources.usecases import (
    Outcome,
    SkippedQuery,
    collect,
    complete_descriptions,
)
from tests.offres.sources.fakes import FakeDetailSource, FakeSource, offer

PARIS = SearchQuery("Data analyst", "Paris")
LYON = SearchQuery("Data analyst", "Lyon")


def found(*ids: str, source: SourceCode = SourceCode.APEC) -> list[CollectedOffer]:
    return [offer(source, external_id) for external_id in ids]


def test_a_failing_source_does_not_stop_the_others() -> None:
    def failing(query: SearchQuery) -> list[CollectedOffer]:
        raise SourceFailedError("Adzuna a répondu par une erreur (HTTP 503).")

    sources = [
        FakeSource(SourceCode.APEC, lambda query: found("a1", "a2")),
        FakeSource(SourceCode.ADZUNA, failing),
        FakeSource(
            SourceCode.LINKEDIN, lambda query: found("l1", source=SourceCode.LINKEDIN)
        ),
    ]

    report = collect(sources, [PARIS], limit=20)

    assert [(outcome.source, outcome.status) for outcome in report.outcomes] == [
        (SourceCode.APEC, Outcome.OK),
        (SourceCode.ADZUNA, Outcome.FAILED),
        (SourceCode.LINKEDIN, Outcome.OK),
    ]
    assert report.outcomes[1].reason == "Adzuna a répondu par une erreur (HTTP 503)."
    assert [found_offer.external_id for found_offer in report.offers] == [
        "a1",
        "a2",
        "l1",
    ]


def test_an_unexpected_error_is_isolated_logged_and_shown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def crashing(query: SearchQuery) -> list[CollectedOffer]:
        raise KeyError("office")

    sources = [
        FakeSource(SourceCode.WTTJ, crashing),
        FakeSource(SourceCode.APEC, lambda query: found("a1")),
    ]

    with caplog.at_level(logging.ERROR):
        report = collect(sources, [PARIS], limit=20)

    wttj, apec = report.outcomes
    assert wttj.status is Outcome.FAILED
    assert wttj.reason == (
        "Erreur technique dans le connecteur Welcome to the Jungle "
        "(trace dans le journal de l'application)."
    )
    assert apec.status is Outcome.OK
    # Not swallowed: the trace is in the log.
    assert "source wttj failed unexpectedly" in caplog.text
    assert "KeyError: 'office'" in caplog.text


def test_a_refusal_stops_the_source_and_keeps_what_it_gave() -> None:
    def refusing_on_lyon(query: SearchQuery) -> list[CollectedOffer]:
        if query.location == "Lyon":
            raise SourceRefusedError(
                "Refusé par Apec : la plateforme bloque (HTTP 403)."
            )
        return found("a1")

    apec = FakeSource(SourceCode.APEC, refusing_on_lyon)

    outcome = collect([apec], [PARIS, LYON, SearchQuery("BI", "Paris")], 20).outcomes[0]

    assert outcome.status is Outcome.REFUSED
    assert [kept.external_id for kept in outcome.offers] == ["a1"]
    assert apec.queries == [PARIS, LYON]


def test_a_skipped_query_is_reported_and_the_other_queries_go_on() -> None:
    def unknown_lyon(query: SearchQuery) -> list[CollectedOffer]:
        if query.location == "Lyon":
            raise QuerySkippedError("Lieu non reconnu par Apec : « Lyon ».")
        return found("a1")

    outcome = collect(
        [FakeSource(SourceCode.APEC, unknown_lyon)], [LYON, PARIS], 20
    ).outcomes[0]

    assert outcome.status is Outcome.OK
    assert outcome.skipped == (
        SkippedQuery(LYON, "Lieu non reconnu par Apec : « Lyon »."),
    )
    assert len(outcome.offers) == 1


@pytest.mark.parametrize(
    ("availability", "status"),
    [
        (Availability.PENDING_ACCESS, Outcome.PENDING_ACCESS),
        (Availability.NOT_CONFIGURED, Outcome.NOT_CONFIGURED),
    ],
)
def test_an_unavailable_source_is_never_called(
    availability: Availability, status: Outcome
) -> None:
    source = FakeSource(
        SourceCode.FRANCE_TRAVAIL, lambda query: found("f1"), available=availability
    )

    outcome = collect([source], [PARIS], 20).outcomes[0]

    assert outcome.status is status
    assert source.queries == []


def test_a_source_ignoring_locations_is_asked_once_per_title() -> None:
    source = FakeSource(
        SourceCode.WTTJ, lambda query: found("w1", "w2"), filters_location=False
    )

    outcome = collect([source], [PARIS, LYON], 20).outcomes[0]

    assert source.queries == [SearchQuery("Data analyst")]
    assert outcome.filters_location is False


def test_an_offer_found_by_several_queries_is_collected_once() -> None:
    source = FakeSource(SourceCode.APEC, lambda query: found("a1", "a2"))

    outcome = collect([source], [PARIS, LYON], 20).outcomes[0]

    assert [kept.external_id for kept in outcome.offers] == ["a1", "a2"]


def test_details_complete_incomplete_offers_of_sources_that_have_one() -> None:
    wttj = FakeDetailSource(SourceCode.WTTJ, lambda query: [])
    offers = [
        offer(SourceCode.WTTJ, "w1", complete=False),
        offer(SourceCode.WTTJ, "w2"),
        offer(SourceCode.LINKEDIN, "l1", complete=False),
    ]

    report = complete_descriptions(
        [wttj, FakeSource(SourceCode.LINKEDIN, lambda query: [])], offers
    )

    assert wttj.completed == ["w1"]
    assert [kept.description_complete for kept in report.offers] == [True, True, False]
    assert report.refused == {}


def test_a_refused_detail_stops_asking_that_source() -> None:
    def refused(found_offer: CollectedOffer) -> CollectedOffer:
        raise SourceRefusedError("Refusé par Apec : la plateforme bloque (HTTP 403).")

    apec = FakeDetailSource(SourceCode.APEC, lambda query: [], detail=refused)
    offers = [offer(SourceCode.APEC, f"a{index}", complete=False) for index in range(3)]

    report = complete_descriptions([apec], offers)

    assert apec.completed == ["a0"]
    reason = "Refusé par Apec : la plateforme bloque (HTTP 403). La description complète se lit sur l'annonce."
    assert [kept.incomplete_reason for kept in report.offers] == [reason] * 3
    assert report.refused == {SourceCode.APEC: reason}


def test_a_failed_detail_keeps_the_offer_and_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing(found_offer: CollectedOffer) -> CollectedOffer:
        if found_offer.external_id == "w0":
            raise SourceFailedError(
                "Welcome to the Jungle ne répond pas (délai dépassé)."
            )
        raise TypeError("unexpected")

    wttj = FakeDetailSource(SourceCode.WTTJ, lambda query: [], detail=failing)
    offers = [offer(SourceCode.WTTJ, f"w{index}", complete=False) for index in range(2)]

    with caplog.at_level(logging.ERROR):
        report = complete_descriptions([wttj], offers)

    assert wttj.completed == ["w0", "w1"]
    assert report.offers[0].incomplete_reason == (
        "Détail illisible : Welcome to the Jungle ne répond pas (délai dépassé)."
    )
    assert report.offers[1].incomplete_reason is not None
    assert report.offers[1].incomplete_reason.startswith("Erreur technique")
    assert "TypeError: unexpected" in caplog.text
