"""The functions ``offres`` gives the other modules (D3: the analysis an application's CV is targeted with)."""

from __future__ import annotations

from sqlalchemy import Connection

from rocky.offres import web as offres_web
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import record_offer
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

    analysis = offres_web.offer_analysis(
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
        offres_web.offer_analysis(
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

    headings = offres_web.offer_headings(db, seeker.account_id, offer_ids)

    with_form, plain = (headings[offer_id] for offer_id in offer_ids)
    assert with_form.apply_at == "https://employeur.example/postuler"
    assert plain.apply_at == "https://apec.example/offres/plain"
