"""The prototype data (built by docs/procedures/b4-prototype/build_offers.py) and the in-memory decision book."""

from __future__ import annotations

import re
from datetime import date

from rocky.offres.decisions import make_decision
from rocky.offres.prototype import DecisionBook, load_catalog


def test_the_catalog_covers_the_hard_cases() -> None:
    catalog = load_catalog()
    offers = catalog.offers

    assert len(offers) == 30
    assert len({offer.id for offer in offers}) == 30
    assert set(catalog.tracks) == {"ai_ml", "data_analyst"}
    assert all(offer.tracks for offer in offers)
    assert any(len(offer.tracks) == 2 for offer in offers)
    assert sum(catalog.below_threshold(offer) for offer in offers) >= 8
    assert sum(not offer.description_is_full for offer in offers) >= 5
    assert len({offer.source for offer in offers}) >= 4
    assert any(offer.salary and offer.salary.period == "day" for offer in offers)
    assert any(
        offer.published_on and offer.published_on < date(2026, 7, 24)
        for offer in offers
    )
    assert any(offer.eliminatory for offer in offers)
    assert {offer.confidence for offer in offers} == {"low", "medium", "high"}


def test_no_e_mail_address_or_phone_number_is_published() -> None:
    for offer in load_catalog().offers:
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w", offer.description), offer.id
        assert not re.search(
            r"(?:\+33\s?|\b0)[1-9](?:[\s.-]?\d{2}){4}", offer.description
        ), offer.id


def test_every_offer_explains_its_score() -> None:
    for offer in load_catalog().offers:
        keys = [component.key for component in offer.components]
        assert keys == ["title", "skills", "location", "contract", "salary"]
        assert 0 <= offer.score <= 100


def test_the_queue_leaves_out_offers_below_the_threshold_best_first() -> None:
    catalog = load_catalog()
    best = catalog.offers[0]

    queue = catalog.queue(decided={best.id})

    assert best not in queue
    assert all(offer.score >= catalog.threshold for offer in queue)
    assert [o.score for o in queue] == sorted((o.score for o in queue), reverse=True)


def test_the_book_undoes_several_decisions_in_reverse_order() -> None:
    book = DecisionBook()
    first = make_decision("interested", ["target_job"])
    second = make_decision("rejected", ["too_senior"])
    book.record(1, 10, first)
    book.record(1, 11, second)
    book.record(1, 10, second)  # changed its mind about offer 10

    assert book.undo(1) == 10
    assert book.decisions(1) == {10: first, 11: second}
    assert book.undo(1) == 11
    assert book.undo(1) == 10
    assert book.decisions(1) == {}
    assert book.undo(1) is None
    assert not book.can_undo(1)


def test_the_book_keeps_accounts_apart_and_resets_one() -> None:
    book = DecisionBook()
    decision = make_decision("later", ["reread"])
    book.record(1, 10, decision)
    book.record(2, 10, decision)

    book.reset(1)

    assert book.decisions(1) == {}
    assert book.decisions(2) == {10: decision}


def test_remote_work_is_shown_in_plain_words() -> None:
    labels = {offer.remote_label for offer in load_catalog().offers if offer.remote}

    assert labels <= {"possible", "partiel", "complet", "ponctuel", "aucun"}
