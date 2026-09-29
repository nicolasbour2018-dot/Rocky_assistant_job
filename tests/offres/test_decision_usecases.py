"""Decisions, pasted descriptions and stored summaries on PostgreSQL (C7): appended, traced, in one transaction."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

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
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.scoring.model import Score
from rocky.offres.sql import SqlStore, job_decisions, job_offers
from rocky.offres.usecases import (
    cancel_last_decision,
    enrich_offer,
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
