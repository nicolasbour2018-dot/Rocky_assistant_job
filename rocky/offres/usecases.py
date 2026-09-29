"""Use cases of the stored offers: the unit "offer + tracks + scores", shared by the watch and the import by URL;
the decisions of the offers screen (C7), the description pasted by the user and the stored summary.

Each use case runs inside one transaction opened by the caller (the stores never commit): an offer is never
written without its tracks and its scores (exit criterion of C6), a decision never without its event (C7).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Protocol

from rocky.offres.analysis.rules import analyze
from rocky.offres.analysis.usecases import Summary
from rocky.offres.decisions import (
    Author,
    Decision,
    effective_decisions,
    to_cancel,
)
from rocky.offres.imports.rules import enriched, with_pasted_description
from rocky.offres.model import (
    DecisionStore,
    OfferStore,
    Origin,
    Recorded,
    ScoringInputs,
    StoredOffer,
    StoredSummary,
)
from rocky.offres.rules import best_track, description_hash, match_key
from rocky.offres.scoring.model import Score
from rocky.offres.scoring.rules import score
from rocky.offres.screen import shown_track
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
        description_complete=merged.description_complete,
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


def enrich_offer(
    store: OfferStore,
    stored: StoredOffer,
    text: str,
    *,
    inputs: ScoringInputs,
    now: datetime,
    today: date,
) -> Score:
    """« Coller la description » (C7, Q5, Q13): the pasted text becomes the complete description of the offer, which is
    scored again at once, with the user's event. Tracks are kept. Raises ``InvalidPasteError`` (message shown)."""
    offer = with_pasted_description(stored.offer, text)
    before = store.current_score(stored.id)
    store.update(stored.id, offer, match_key=match_key(offer), now=now, seen=False)
    result = _score(offer, inputs, today)
    store.replace_scores(stored.id, result, inputs_hash=inputs.inputs_hash, now=now)
    store.append_event(
        NewEvent(
            type="offres.offer_enriched",
            actor=Actor.USER,
            subject_type="job_offer",
            subject_id=str(stored.id),
            payload={
                "how": "pasted",
                "was_complete": stored.offer.description_complete,
                "score_before": None if before is None else before.best.display,
                "score_after": result.best.display,
            },
            account_id=stored.account_id,
        )
    )
    return result


def record_decision(
    store: DecisionStore,
    *,
    account_id: int,
    offer_id: int,
    decision: Decision,
    track_id: int | None,
    now: datetime,
    author: Author = Author.USER,
) -> int:
    """A decision on an offer (C7), with a copy of its current score and the track whose score was shown (Q11), and
    its event. A new decision on a decided offer replaces the previous one, which stays in the history (Q8)."""
    score = store.current_score(offer_id)
    if score is None:
        # Never true: every stored offer has a score (C6).
        raise LookupError(f"offer {offer_id} has no score")
    track = shown_track(score, track_id)
    previous = effective_decisions(store.decision_rows(account_id, offer_id)).get(
        offer_id
    )
    decision_id = store.insert_decision(
        account_id,
        offer_id,
        decision,
        author=author,
        track=track,
        score=score,
        inputs_hash=store.current_inputs_hash(offer_id),
        now=now,
    )
    store.append_event(
        NewEvent(
            type="offres.decision_recorded",
            actor=Actor(author.value),
            subject_type="job_offer",
            subject_id=str(offer_id),
            payload={
                "decision_id": decision_id,
                "value": decision.value.value,
                "reasons": list(decision.reasons),
                "note": decision.note,
                "track_id": track.track_id,
                "score": track.display,
                "rules_version": score.rules_version,
                "previous": None
                if previous is None or previous.decision is None
                else previous.decision.value.value,
            },
            account_id=account_id,
        )
    )
    return decision_id


def cancel_last_decision(
    store: DecisionStore,
    *,
    account_id: int,
    now: datetime,
    author: Author = Author.USER,
) -> int | None:
    """« Annuler » (C7, Q8): cancels the latest decision of the account still in force, with its event; the offer gets
    its previous decision back, or is to examine again. Returns the offer, or None when nothing is left to cancel."""
    rows = store.decision_rows(account_id)
    cancelled = to_cancel(rows)
    if cancelled is None or cancelled.decision is None:
        return None
    cancellation = store.insert_cancellation(
        account_id, cancelled, author=author, now=now
    )
    restored = effective_decisions([*rows, cancellation]).get(cancelled.offer_id)
    store.append_event(
        NewEvent(
            type="offres.decision_cancelled",
            actor=Actor(author.value),
            subject_type="job_offer",
            subject_id=str(cancelled.offer_id),
            payload={
                "decision_id": cancelled.id,
                "value": cancelled.decision.value.value,
                "restored": None
                if restored is None or restored.decision is None
                else restored.decision.value.value,
            },
            account_id=account_id,
        )
    )
    return cancelled.offer_id


class SummaryStore(Protocol):
    def summary(self, offer_id: int) -> StoredSummary | None: ...

    def save_summary(
        self, offer_id: int, summary: StoredSummary, now: datetime
    ) -> None: ...


def stored_summary(store: SummaryStore, stored: StoredOffer) -> Summary | None:
    """The summary kept for the offer, unless its description changed since (Q6)."""
    kept = store.summary(stored.id)
    if kept is None or kept.description_hash != description_hash(stored.offer):
        return None
    return kept.summary


def keep_summary(
    store: SummaryStore, stored: StoredOffer, summary: Summary, *, now: datetime
) -> None:
    """Keep a summary the language model gave, for the description it summarised; a failed one is never kept."""
    store.save_summary(
        stored.id, StoredSummary(description_hash(stored.offer), summary), now
    )


def _score(offer: CollectedOffer, inputs: ScoringInputs, today: date) -> Score:
    analysis = analyze(offer, inputs.skills, today=today)
    return score(analysis, offer, inputs.profile, today=today)
