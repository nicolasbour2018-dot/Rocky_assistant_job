"""Readable account of a collection, source by source (shown by ``rocky-admin sources``)."""

from __future__ import annotations

from collections import Counter

from rocky.offres.sources.model import SOURCE_LABELS
from rocky.offres.sources.usecases import (
    OUTCOME_LABELS,
    CollectionReport,
    DetailReport,
    Outcome,
    SourceOutcome,
)

UNAVAILABLE_HINTS = {
    Outcome.NOT_CONFIGURED: "ses clés manquent dans la configuration (.env)",
    Outcome.PENDING_ACCESS: "activée quand l'accès à l'API sera accordé (D8)",
}


def report_lines(
    report: CollectionReport, detail: DetailReport | None = None
) -> list[str]:
    """One block per source: its state, what it gave, and why it gave nothing or less."""
    completed = (
        {(offer.source, offer.external_id): offer for offer in detail.offers}
        if detail
        else {}
    )
    lines: list[str] = []
    for outcome in report.outcomes:
        offers = [
            completed.get((offer.source, offer.external_id), offer)
            for offer in outcome.offers
        ]
        lines.append(
            _headline(
                outcome,
                len(offers),
                sum(not offer.description_complete for offer in offers),
            )
        )
        if outcome.reason:
            lines.append(f"  raison : {outcome.reason}")
        if outcome.status in UNAVAILABLE_HINTS:
            lines.append(f"  {UNAVAILABLE_HINTS[outcome.status]}")
        if outcome.status is Outcome.OK and not outcome.filters_location:
            lines.append(
                "  lieu non filtré par cette source : une requête par intitulé"
            )
        # One unknown place skips a query per job title: the reason is told once, with its count.
        reasons = Counter(skipped.reason for skipped in outcome.skipped)
        lines.extend(
            f"  requête{'s' if count > 1 else ''} sautée{'s' if count > 1 else ''}"
            f"{f' ({count})' if count > 1 else ''} : {reason}"
            for reason, count in reasons.items()
        )
        if detail and outcome.source in detail.stopped:
            lines.append(f"  détail arrêté : {detail.stopped[outcome.source]}")
    return lines


def _headline(outcome: SourceOutcome, count: int, incomplete: int) -> str:
    headline = f"{SOURCE_LABELS[outcome.source]} — {OUTCOME_LABELS[outcome.status]}"
    if outcome.status in {Outcome.OK, Outcome.REFUSED, Outcome.FAILED} and (
        count or outcome.status is Outcome.OK
    ):
        headline += f" · {count} offre{'s' if count > 1 else ''}"
        if incomplete:
            headline += f" dont {incomplete} incomplète{'s' if incomplete > 1 else ''}"
    return headline
