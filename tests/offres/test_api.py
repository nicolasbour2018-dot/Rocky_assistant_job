"""The functions ``offres`` gives the other modules through ``offres.api`` (D3: the analysis an application's CV is
targeted with)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Connection

from rocky.offres import api as offres_api
from rocky.offres.decisions import Decision, DecisionValue
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import cancel_last_decision, record_decision, record_offer
from rocky.offres.watch.model import RunCounts, RunStatus, Trigger
from tests.offres.fakes import NOW, TODAY, new_seeker, posting


def test_the_analysis_of_an_offer_names_the_accounts_skills(db: Connection) -> None:
    seeker = new_seeker(db)
    profile = seeker.profile(db)
    offer_id = record_offer(
        SqlStore(db),
        account_id=seeker.account_id,
        offer=posting("d3"),
        inputs=scoring_inputs(profile),
        origin=Origin.WATCH,
        track_ids=[seeker.tracks["Data"]],
        now=NOW,
        today=TODAY,
    ).offer_id

    analysis = offres_api.offer_analysis(
        db, seeker.account_id, offer_id, profile, TODAY
    )

    assert analysis is not None
    assert {match.skill for match in analysis.skills} <= {"Python", "SQL", "Tableau"}
    assert analysis.skills


def test_an_offer_of_another_account_has_no_analysis(db: Connection) -> None:
    owner, other = new_seeker(db), new_seeker(db)
    offer_id = record_offer(
        SqlStore(db),
        account_id=owner.account_id,
        offer=posting("d3-other"),
        inputs=scoring_inputs(owner.profile(db)),
        origin=Origin.WATCH,
        track_ids=[owner.tracks["Data"]],
        now=NOW,
        today=TODAY,
    ).offer_id

    assert (
        offres_api.offer_analysis(
            db, other.account_id, offer_id, other.profile(db), TODAY
        )
        is None
    )


def test_the_heading_of_an_offer_says_where_to_apply(db: Connection) -> None:
    seeker = new_seeker(db)
    profile = seeker.profile(db)
    offer_ids = [
        record_offer(
            SqlStore(db),
            account_id=seeker.account_id,
            offer=found,
            inputs=scoring_inputs(profile),
            origin=Origin.WATCH,
            track_ids=[seeker.tracks["Data"]],
            now=NOW,
            today=TODAY,
        ).offer_id
        for found in (
            posting("form", application_url="https://employeur.example/postuler"),
            posting("plain"),
        )
    ]

    headings = offres_api.offer_headings(db, seeker.account_id, offer_ids)

    with_form, plain = (headings[offer_id] for offer_id in offer_ids)
    assert with_form.apply_at == "https://employeur.example/postuler"
    assert plain.apply_at == "https://apec.example/offres/plain"


def test_the_deadlines_of_the_accounts_offers(db: Connection) -> None:
    owner, other = new_seeker(db), new_seeker(db)

    def recorded(seeker_id: int, track: int, external_id: str, text: str) -> int:
        return record_offer(
            SqlStore(db),
            account_id=seeker_id,
            offer=posting(external_id, description=text),
            inputs=scoring_inputs(owner.profile(db)),
            origin=Origin.WATCH,
            track_ids=[track],
            now=NOW,
            today=TODAY,
        ).offer_id

    with_deadline = recorded(
        owner.account_id,
        owner.tracks["Data"],
        "d6-limite",
        "Analyse de données. Candidatures jusqu'au 12 octobre 2026.",
    )
    without = recorded(owner.account_id, owner.tracks["Data"], "d6-sans", "Analyse.")
    elsewhere = recorded(
        other.account_id,
        other.tracks["Data"],
        "d6-autre",
        "Date limite de candidature : 15/10/2026.",
    )

    found = offres_api.offer_deadlines(
        db, owner.account_id, [with_deadline, without, elsewhere], TODAY
    )

    assert found == {with_deadline: date(2026, 10, 12)}


def test_what_the_cockpit_reads_of_the_offers(db: Connection) -> None:
    """Decision G3: the decisions in force dated (Q11), the first watch (Q12), the watches finished since a moment
    (Q16), the offers whose address is still the alert's in Gmail (H3 → G3)."""
    seeker = new_seeker(db)
    store = SqlStore(db)

    def recorded(external_id: str, url: str | None = None) -> int:
        return record_offer(
            store,
            account_id=seeker.account_id,
            offer=posting(external_id, url=url),
            inputs=scoring_inputs(seeker.profile(db)),
            origin=Origin.WATCH,
            track_ids=[seeker.tracks["Data"]],
            now=NOW,
            today=TODAY,
        ).offer_id

    first, second = recorded("g3-a"), recorded("g3-b")
    recorded(
        "g3-gmail", "https://mail.google.com/mail/u/n%40exemple.fr/?carte=1#all/abc"
    )
    later = NOW + timedelta(hours=1)
    for offer_id, moment in ((first, NOW), (second, later)):
        record_decision(
            store,
            account_id=seeker.account_id,
            offer_id=offer_id,
            decision=Decision(DecisionValue.LATER, ("reread",)),
            track_id=None,
            now=moment,
        )
    cancel_last_decision(store, account_id=seeker.account_id, now=later)
    assert offres_api.first_watch_at(db, seeker.account_id) is None
    failed = store.start_run(seeker.account_id, Trigger.SCHEDULED, NOW)
    store.finish_run(
        failed,
        status=RunStatus.FAILED,
        reason="Panne",
        counts=RunCounts(),
        sources=(),
        now=NOW,
    )
    done = store.start_run(seeker.account_id, Trigger.SCHEDULED, later)
    store.finish_run(
        done,
        status=RunStatus.COMPLETED,
        reason=None,
        counts=RunCounts(found=3),
        sources=(),
        now=later,
    )

    assert offres_api.decided_moments(db, seeker.account_id) == [NOW]
    assert offres_api.first_watch_at(db, seeker.account_id) == later
    assert [run.id for run in store.finished_runs(seeker.account_id, later)] == [done]
    assert store.gmail_addressed(seeker.account_id) == 1
