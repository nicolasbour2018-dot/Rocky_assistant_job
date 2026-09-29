"""Use cases of the stored offers: the unit "offer + tracks + scores", shared by the watch and the import by URL.

Each use case runs inside one transaction opened by the caller (``OfferStore`` never commits): an offer is never
written without its tracks and its scores (exit criterion of C6).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from rocky.offres.analysis.rules import analyze
from rocky.offres.imports.rules import enriched
from rocky.offres.model import (
    OfferStore,
    Origin,
    Recorded,
    ScoringInputs,
    StoredOffer,
)
from rocky.offres.rules import best_track, match_key
from rocky.offres.scoring.model import Score
from rocky.offres.scoring.rules import score
from rocky.offres.sources.model import CollectedOffer
from rocky.system.events import Actor, NewEvent


def record_offer(
    store: OfferStore,
    *,
    account_id: int,
    offer: CollectedOffer,
    inputs: ScoringInputs,
    origin: Origin,
    track_ids: Iterable[int] = (),
    run_id: int | None = None,
    now: datetime,
    today: date,
) -> Recorded:
    """Write ``offer`` with its tracks and its current scores; idempotent.

    A known offer (same source and identifier, or same address) is completed, never overwritten (Q7). The watch gives
    the tracks whose queries found the offer; an import is linked to the track where it scores best (Q10).
    """
    existing = store.find(account_id, offer)
    if existing is None:
        merged = offer
        offer_id = store.insert(
            account_id, offer, origin=origin, match_key=match_key(offer), now=now
        )
    else:
        merged = enriched(existing.offer, offer)
        offer_id = existing.id
        if merged != existing.offer:
            store.update(offer_id, merged, match_key=match_key(merged), now=now)
        else:
            store.mark_seen(offer_id, now)
    result = _score(merged, inputs, today)
    if origin is Origin.IMPORT:
        best = best_track(result)
        track_ids = () if best is None else (best,)
    store.link_tracks(offer_id, track_ids, found_by=origin, run_id=run_id, now=now)
    store.replace_scores(offer_id, result, inputs_hash=inputs.inputs_hash, now=now)
    return Recorded(
        offer_id=offer_id,
        created=existing is None,
        completed=existing is not None and merged != existing.offer,
        score=result,
    )


def add_imported_offer(
    store: OfferStore,
    *,
    account_id: int,
    offer: CollectedOffer,
    inputs: ScoringInputs,
    now: datetime,
    today: date,
) -> Recorded:
    """« Ajouter à mes offres » (Q10): the offer of an import preview joins the offers, with the user's event."""
    recorded = record_offer(
        store,
        account_id=account_id,
        offer=offer,
        inputs=inputs,
        origin=Origin.IMPORT,
        now=now,
        today=today,
    )
    store.append_event(
        NewEvent(
            type="offres.offer_added",
            actor=Actor.USER,
            subject_type="job_offer",
            subject_id=str(recorded.offer_id),
            payload={
                "source": offer.source,
                "created": recorded.created,
                "track_id": recorded.score.best.track_id,
                "score": recorded.score.best.display,
            },
            account_id=account_id,
        )
    )
    return recorded


def rescore_offer(
    store: OfferStore,
    stored: StoredOffer,
    *,
    inputs: ScoringInputs,
    now: datetime,
    today: date,
) -> Score:
    """New current scores of a stored offer, after a change of the profile or of the rules (Q5)."""
    result = _score(stored.offer, inputs, today)
    store.replace_scores(stored.id, result, inputs_hash=inputs.inputs_hash, now=now)
    return result


def _score(offer: CollectedOffer, inputs: ScoringInputs, today: date) -> Score:
    analysis = analyze(offer, inputs.skills, today=today)
    return score(analysis, offer, inputs.profile, today=today)
