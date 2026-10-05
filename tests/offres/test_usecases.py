"""The unit "offer + tracks + scores" on PostgreSQL: written together, idempotent, completed without overwriting."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import Connection, insert, select
from sqlalchemy.exc import IntegrityError

from rocky.offres.model import Origin, Recorded
from rocky.offres.rules import scoring_inputs
from rocky.offres.sources.model import CollectedOffer
from rocky.offres.sql import SqlStore, job_offers, offer_scores, offer_tracks
from rocky.offres.usecases import add_imported_offer, record_offer, rescore_offer
from rocky.profil.rules import ProfileInputError, make_track
from rocky.system.events import events
from tests.offres.fakes import NOW, TODAY, Seeker, new_seeker, posting


def record(
    db: Connection,
    seeker: Seeker,
    offer: CollectedOffer,
    *,
    tracks: tuple[str, ...] = ("Data",),
    origin: Origin = Origin.WATCH,
) -> Recorded:
    return record_offer(
        SqlStore(db),
        account_id=seeker.account_id,
        offer=offer,
        inputs=scoring_inputs(seeker.profile(db)),
        origin=origin,
        track_ids=[seeker.tracks[name] for name in tracks],
        now=NOW,
        today=TODAY,
    )


def links(db: Connection, offer_id: int) -> dict[int, str]:
    rows = db.execute(
        select(offer_tracks.c.track_id, offer_tracks.c.found_by).where(
            offer_tracks.c.offer_id == offer_id
        )
    ).all()
    return {row.track_id: row.found_by for row in rows}


def test_an_offer_is_written_with_its_tracks_and_a_score_per_active_track(
    db: Connection,
) -> None:
    seeker = new_seeker(db)

    recorded = record(db, seeker, posting("a1"))

    store = SqlStore(db)
    assert recorded.created
    offer_id = recorded.offer_id
    assert links(db, offer_id) == {seeker.tracks["Data"]: "watch"}
    score = store.current_score(offer_id)
    assert score is not None
    assert [track.track_name for track in score.tracks] == ["Data", "IA"]
    assert score == recorded.score
    assert store.unscored_or_orphan_offers(seeker.account_id) == []


def test_an_offer_under_the_threshold_is_kept_with_its_reason(db: Connection) -> None:
    seeker = new_seeker(db)

    recorded = record(
        db,
        seeker,
        posting("a1", title="Commercial terrain", description="Vente en magasin."),
    )

    score = SqlStore(db).current_score(recorded.offer_id)
    assert score is not None and score.below_threshold
    assert score.threshold_reason is not None
    assert score.threshold_reason.startswith("Score sous le seuil")


def test_recording_the_same_offer_twice_writes_it_once(db: Connection) -> None:
    seeker = new_seeker(db)
    first = record(db, seeker, posting("a1"))

    second = record(db, seeker, posting("a1"), tracks=("Data", "IA"))

    assert second.offer_id == first.offer_id
    assert not second.created and not second.completed
    count = db.execute(
        select(job_offers.c.id).where(job_offers.c.account_id == seeker.account_id)
    ).all()
    assert len(count) == 1
    assert set(links(db, first.offer_id)) == set(seeker.tracks.values())
    scores = db.execute(
        select(offer_scores.c.id).where(offer_scores.c.offer_id == first.offer_id)
    ).all()
    assert len(scores) == 2


def test_a_known_offer_is_completed_never_overwritten(db: Connection) -> None:
    seeker = new_seeker(db)
    first = record(db, seeker, posting("a1", complete=False, salary_text="45 k€"))

    again = record(
        db, seeker, posting("a1", complete=True, salary_text="60 k€", sector="Banque")
    )

    assert again.completed
    stored = SqlStore(db).get(first.offer_id)
    assert stored is not None
    assert stored.offer.description_complete
    assert stored.offer.incomplete_reason is None
    assert stored.offer.salary_text == "45 k€"
    assert stored.offer.sector == "Banque"


def test_an_import_and_the_watch_meet_on_the_address(db: Connection) -> None:
    seeker = new_seeker(db)
    watched = record(
        db, seeker, posting("12345", source="wttj", url="https://x.fr/o/1")
    )

    imported = record(
        db,
        seeker,
        posting("https://x.fr/o/1", source="x.fr", url="https://x.fr/o/1"),
        origin=Origin.IMPORT,
    )

    assert imported.offer_id == watched.offer_id
    assert not imported.created


def test_an_import_is_linked_to_its_best_track_with_the_users_event(
    db: Connection,
) -> None:
    seeker = new_seeker(db)
    profile = seeker.profile(db)

    recorded = add_imported_offer(
        SqlStore(db),
        account_id=seeker.account_id,
        offer=posting("i1", title="Data scientist"),
        inputs=scoring_inputs(profile),
        now=NOW,
        today=TODAY,
    )

    assert links(db, recorded.offer_id) == {seeker.tracks["IA"]: "import"}
    stored = SqlStore(db).get(recorded.offer_id)
    assert stored is not None and stored.origin is Origin.IMPORT
    event = db.execute(
        select(events).where(
            events.c.type == "offres.offer_added",
            events.c.subject_id == str(recorded.offer_id),
        )
    ).one()
    assert event.actor == "user"
    assert event.payload["track_id"] == seeker.tracks["IA"]


def test_an_import_without_active_track_keeps_one_score_and_no_link(
    db: Connection,
) -> None:
    seeker = new_seeker(db)
    editor = seeker.editor(db)
    for track_id in seeker.tracks.values():
        editor.pause_track(track_id)

    recorded = record(db, seeker, posting("i1"), origin=Origin.IMPORT)

    assert links(db, recorded.offer_id) == {}
    score = SqlStore(db).current_score(recorded.offer_id)
    assert score is not None and [t.track_id for t in score.tracks] == [None]
    assert SqlStore(db).unscored_or_orphan_offers(seeker.account_id) == []


def test_a_changed_track_makes_the_scores_stale_until_rescored(db: Connection) -> None:
    seeker = new_seeker(db)
    recorded = record(db, seeker, posting("a1"))
    store = SqlStore(db)
    seeker.editor(db).update_track(
        seeker.tracks["IA"],
        make_track(name="IA", titles=["Data analyst"], locations=["Paris"]),
    )
    inputs = scoring_inputs(seeker.profile(db))

    (stale,) = store.stale_offers(seeker.account_id, inputs.inputs_hash)
    assert stale.id == recorded.offer_id
    before = store.current_score(stale.id)
    assert before is not None

    after = rescore_offer(store, stale, inputs=inputs, now=NOW, today=TODAY)

    assert after.tracks[1].value > before.tracks[1].value
    assert store.current_score(stale.id) == after
    assert store.stale_offers(seeker.account_id, inputs.inputs_hash) == []


def test_the_database_keeps_one_score_per_offer_and_track(db: Connection) -> None:
    seeker = new_seeker(db)
    recorded = record(db, seeker, posting("a1"))
    row = db.execute(
        select(offer_scores).where(offer_scores.c.offer_id == recorded.offer_id)
    ).first()
    assert row is not None
    values = {
        key: value
        for key, value in row._mapping.items()
        if key not in {"id", "track_id", "position"}
    }

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            insert(offer_scores).values(**values, track_id=row.track_id, position=9)
        )
    # Two scores "without track" are the same row too (NULLS NOT DISTINCT).
    db.execute(insert(offer_scores).values(**values, track_id=None, position=8))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert(offer_scores).values(**values, track_id=None, position=9))


def test_a_track_with_offers_cannot_be_deleted_only_archived(db: Connection) -> None:
    seeker = new_seeker(db)
    record(db, seeker, posting("a1"))
    editor = seeker.editor(db)

    with pytest.raises(ProfileInputError, match="archive-la plutôt"):
        editor.delete_track(seeker.tracks["Data"])

    # The transaction goes on: the track still exists, and can be archived.
    assert editor.archive_track(seeker.tracks["Data"])
    # A track without offers is still deleted; its scores go with it.
    assert editor.delete_track(seeker.tracks["IA"])


def test_the_offer_facts_round_trip(db: Connection) -> None:
    seeker = new_seeker(db)
    offer = replace(
        posting("a1", salary_min=45000.0, salary_max=55000.0, contract="CDI"),
        published_on=TODAY,
        deadline=TODAY,
        application_url="https://apec.example/postuler",
    )

    recorded = record(db, seeker, offer)

    stored = SqlStore(db).get(recorded.offer_id)
    assert stored is not None and stored.offer == offer
