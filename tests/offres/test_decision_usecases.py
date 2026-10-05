"""Decisions, pasted descriptions, pages read in a visible browser (E5) and stored summaries on PostgreSQL (C7):
appended, traced, in one transaction."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Connection, null, select, update
from sqlalchemy.exc import IntegrityError

from rocky.offres.analysis.usecases import Summary
from rocky.offres.decisions import (
    Author,
    Decision,
    DecisionValue,
    effective_decisions,
)
from rocky.offres.imports.model import InvalidPasteError
from rocky.offres.imports.rules import (
    NO_CONTENT_REASON,
    NOT_READABLE_REASON,
    OTHER_PAGE_REASON,
)
from rocky.offres.model import Origin, StoredOffer
from rocky.offres.rules import scoring_inputs
from rocky.offres.scoring.model import Score
from rocky.offres.sql import SqlStore, job_decisions, job_offers
from rocky.offres.usecases import (
    PageReading,
    ReadingOutcome,
    cancel_decision,
    cancel_last_decision,
    enrich_offer,
    enrich_offer_from_page,
    keep_summary,
    record_decision,
    record_offer,
    stored_summary,
)
from rocky.system.events import events
from tests.offres.fakes import NOW, TODAY, Seeker, new_seeker, posting

LATER = Decision(DecisionValue.LATER, ("reread",))
REJECTED = Decision(DecisionValue.REJECTED, ("too_senior", "sector"))


def recorded(db: Connection, seeker: Seeker, external_id: str, **facts: object) -> int:
    return record_offer(
        SqlStore(db),
        account_id=seeker.account_id,
        offer=posting(external_id, **facts),  # type: ignore[arg-type]
        inputs=scoring_inputs(seeker.profile(db)),
        origin=Origin.WATCH,
        track_ids=[seeker.tracks["Data"]],
        now=NOW,
        today=TODAY,
    ).offer_id


def decide(
    db: Connection, seeker: Seeker, offer_id: int, decision: Decision = REJECTED
) -> int:
    return record_decision(
        SqlStore(db),
        account_id=seeker.account_id,
        offer_id=offer_id,
        decision=decision,
        track_id=None,
        now=NOW,
    )


def journal(db: Connection, seeker: Seeker) -> list[str]:
    return list(
        db.execute(
            select(events.c.type)
            .where(events.c.account_id == seeker.account_id)
            .order_by(events.c.id)
        ).scalars()
    )


def test_a_decision_keeps_a_copy_of_the_score_and_its_event(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1")
    score = SqlStore(db).current_score(offer_id)
    assert score is not None

    decision_id = decide(db, seeker, offer_id)

    row = db.execute(
        select(job_decisions).where(job_decisions.c.id == decision_id)
    ).one()
    assert Score.from_json(row.score) == score
    assert row.rules_version == score.rules_version
    assert (row.track_id, row.displayed_score) == (
        score.best.track_id,
        score.best.display,
    )
    assert journal(db, seeker)[-1] == "offres.decision_recorded"


def test_a_decision_and_its_event_are_written_together(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1")
    before = journal(db, seeker)

    with pytest.raises(RuntimeError), db.begin_nested():
        decide(db, seeker, offer_id)
        raise RuntimeError("failure after the decision")

    assert SqlStore(db).decision_rows(seeker.account_id) == []
    assert journal(db, seeker) == before


def test_a_change_is_a_new_row_and_the_event_tells_the_previous_value(
    db: Connection,
) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1")
    decide(db, seeker, offer_id, LATER)

    decide(db, seeker, offer_id, REJECTED)

    rows = SqlStore(db).decision_rows(seeker.account_id)
    assert len(rows) == 2
    assert effective_decisions(rows)[offer_id].decision == REJECTED
    payload = db.execute(
        select(events.c.payload)
        .where(events.c.account_id == seeker.account_id)
        .order_by(events.c.id.desc())
        .limit(1)
    ).scalar_one()
    assert payload["previous"] == "later"


def test_nothing_to_cancel_writes_nothing(db: Connection) -> None:
    seeker = new_seeker(db)
    before = journal(db, seeker)

    assert (
        cancel_last_decision(SqlStore(db), account_id=seeker.account_id, now=NOW)
        is None
    )
    assert journal(db, seeker) == before


def test_cancelling_a_given_decision_restores_the_previous_one_once(
    db: Connection,
) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1")
    decide(db, seeker, offer_id, LATER)
    decision_id = decide(db, seeker, offer_id, REJECTED)
    other = recorded(db, seeker, "a2")
    decide(
        db, seeker, other, LATER
    )  # the latest decision of the account is another one

    assert cancel_decision(
        SqlStore(db), account_id=seeker.account_id, decision_id=decision_id, now=NOW
    )
    assert not cancel_decision(
        SqlStore(db), account_id=seeker.account_id, decision_id=decision_id, now=NOW
    )

    rows = SqlStore(db).decision_rows(seeker.account_id)
    assert effective_decisions(rows)[offer_id].decision == LATER
    assert effective_decisions(rows)[other].decision == LATER
    assert journal(db, seeker)[-1] == "offres.decision_cancelled"


def test_a_decision_of_another_account_cannot_be_cancelled(db: Connection) -> None:
    seeker, other = new_seeker(db), new_seeker(db)
    decision_id = decide(db, seeker, recorded(db, seeker, "a1"))

    with pytest.raises(LookupError):
        cancel_decision(
            SqlStore(db), account_id=other.account_id, decision_id=decision_id, now=NOW
        )


def test_decisions_are_appended_never_changed(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1")
    decision_id = decide(db, seeker, offer_id)
    cancel_last_decision(SqlStore(db), account_id=seeker.account_id, now=NOW)

    rows = SqlStore(db).decision_rows(seeker.account_id)
    assert [row.kind for row in rows] == ["decision", "cancellation"]
    assert rows[1].cancels == decision_id
    # A decision cannot be cancelled twice, and a decision row needs its value and score.
    with pytest.raises(IntegrityError), db.begin_nested():
        SqlStore(db).insert_cancellation(
            seeker.account_id, rows[0], author=Author.USER, now=NOW
        )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            update(job_decisions)
            .where(job_decisions.c.id == decision_id)
            .values(score=null())
        )


def test_a_pasted_description_completes_and_scores_the_offer_again(
    db: Connection,
) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1", title="Chef de projet", complete=False)
    store = SqlStore(db)
    stored = store.get(offer_id)
    assert stored is not None
    before = store.current_score(offer_id)
    assert before is not None
    later = NOW + timedelta(days=1)

    after = enrich_offer(
        store,
        stored,
        "Chef de projet data analyst.\nPython, SQL et Tableau exigés.",
        inputs=scoring_inputs(seeker.profile(db)),
        now=later,
        today=TODAY,
    )

    row = db.execute(select(job_offers).where(job_offers.c.id == offer_id)).one()
    assert row.description_complete and row.incomplete_reason is None
    assert row.last_seen_at == NOW  # a paste is not a sighting by a source
    assert after.best.display > before.best.display
    assert store.current_score(offer_id) == after
    assert store.track_ids(offer_id) == {seeker.tracks["Data"]}
    assert journal(db, seeker)[-1] == "offres.offer_enriched"
    assert store.unscored_or_orphan_offers(seeker.account_id) == []


def test_an_empty_paste_changes_nothing(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1", complete=False)
    store = SqlStore(db)
    stored = store.get(offer_id)
    assert stored is not None

    with pytest.raises(InvalidPasteError):
        enrich_offer(
            store,
            stored,
            "  ",
            inputs=scoring_inputs(seeker.profile(db)),
            now=NOW,
            today=TODAY,
        )

    assert store.get(offer_id) == stored


# A page shown in a visible browser (decision E5).

APEC_PAGE = (
    Path(__file__).parent / "imports" / "data" / "apec" / "rendered.html"
).read_text()
APEC_URL = (
    "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/179509139W"
)
# Facts, but no description to read: its visible text only (Q3).
FACTS_PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@type": "JobPosting", "title": "Data analyst", "hiringOrganization": {"name": "Acme"}}'
    "</script></head><body><nav>Menu</nav><p>Connectez-vous pour voir l'annonce.</p></body></html>"
)


def read_page(
    db: Connection, seeker: Seeker, offer_id: int, url: str, page_html: str
) -> tuple[PageReading, StoredOffer]:
    store = SqlStore(db)
    stored = store.get(offer_id)
    assert stored is not None
    reading = enrich_offer_from_page(
        store,
        stored,
        url,
        page_html,
        inputs=scoring_inputs(seeker.profile(db)),
        now=NOW + timedelta(days=1),
        today=TODAY,
    )
    after = store.get(offer_id)
    assert after is not None
    return reading, after


def enrichments(db: Connection, offer_id: int) -> list[dict[str, object]]:
    return [
        dict(payload)
        for payload in db.execute(
            select(events.c.payload)
            .where(
                events.c.type == "offres.offer_enriched",
                events.c.subject_id == str(offer_id),
            )
            .order_by(events.c.id)
        ).scalars()
    ]


def test_an_apec_offer_is_completed_by_its_page_shown(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "179509139W", complete=False)
    before = SqlStore(db).current_score(offer_id)

    reading, after = read_page(db, seeker, offer_id, APEC_URL, APEC_PAGE)

    assert reading.outcome == ReadingOutcome.COMPLETED
    assert reading.reason is None
    assert reading.score is not None
    row = db.execute(select(job_offers).where(job_offers.c.id == offer_id)).one()
    assert row.description_complete and "Profil recherché" in row.description
    assert row.external_id == "179509139W"  # identity kept
    assert row.last_seen_at == NOW  # a reading is not a sighting by a source
    assert SqlStore(db).current_score(offer_id) == reading.score
    assert before is not None
    assert after.offer.description_complete
    (payload,) = enrichments(db, offer_id)
    assert payload == {
        "how": "browser",
        "method": "targeted_html",
        "description_read": True,
        "was_complete": False,
        "score_before": before.best.display,
        "score_after": reading.score.best.display,
    }
    assert "apec.fr" not in str(payload)  # never an address
    assert SqlStore(db).unscored_or_orphan_offers(seeker.account_id) == []


def test_a_page_of_another_site_writes_nothing(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "179509139W", complete=False)
    stored = SqlStore(db).get(offer_id)

    reading, after = read_page(
        db, seeker, offer_id, "https://login.example.com/sso", APEC_PAGE
    )

    assert (reading.outcome, reading.reason) == (
        ReadingOutcome.OTHER_PAGE,
        OTHER_PAGE_REASON,
    )
    assert after == stored
    assert enrichments(db, offer_id) == []


def test_a_page_without_a_readable_posting_fills_facts_only(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1", company=None, complete=False)

    reading, after = read_page(db, seeker, offer_id, APEC_URL, FACTS_PAGE)

    assert (reading.outcome, reading.reason) == (
        ReadingOutcome.FACTS_ONLY,
        NOT_READABLE_REASON,
    )
    assert after.offer.company == "Acme"
    assert not after.offer.description_complete
    (payload,) = enrichments(db, offer_id)
    assert (payload["method"], payload["description_read"]) == ("visible_text", False)


def test_a_page_read_again_brings_nothing_and_writes_nothing(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "179509139W", complete=False)
    read_page(db, seeker, offer_id, APEC_URL, APEC_PAGE)

    reading, _ = read_page(db, seeker, offer_id, APEC_URL, APEC_PAGE)

    assert (reading.outcome, reading.score) == (ReadingOutcome.NOTHING_NEW, None)
    assert len(enrichments(db, offer_id)) == 1


def test_an_empty_page_says_why(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1", complete=False)

    reading, _ = read_page(db, seeker, offer_id, APEC_URL, "<html><body></body></html>")

    assert (reading.outcome, reading.reason) == (
        ReadingOutcome.UNREADABLE,
        NO_CONTENT_REASON,
    )
    assert enrichments(db, offer_id) == []


def test_a_reading_and_its_event_are_written_together(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "179509139W", complete=False)
    stored = SqlStore(db).get(offer_id)

    with pytest.raises(RuntimeError), db.begin_nested():
        read_page(db, seeker, offer_id, APEC_URL, APEC_PAGE)
        raise RuntimeError("failure after the reading")

    assert SqlStore(db).get(offer_id) == stored
    assert enrichments(db, offer_id) == []


def test_a_summary_is_kept_until_the_description_changes(db: Connection) -> None:
    seeker = new_seeker(db)
    offer_id = recorded(db, seeker, "a1")
    store = SqlStore(db)
    stored = store.get(offer_id)
    assert stored is not None
    summary = Summary("Missions.", "Contexte.", "Profil.")

    assert stored_summary(store, stored) is None
    keep_summary(store, stored, summary, now=NOW)
    keep_summary(store, stored, summary, now=NOW)  # kept again: one row

    assert stored_summary(store, stored) == summary
    changed = replace(stored, offer=replace(stored.offer, description="Autre texte."))
    assert stored_summary(store, changed) is None
