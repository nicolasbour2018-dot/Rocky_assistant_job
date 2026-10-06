"""What ``offres`` gives the other modules (the applications, D1; the messages, E3 and E4): on the caller's connection
and inside its transaction, they never read the tables of ``offres`` themselves. No route here: a background thread or
the command line reads the offers without loading the screens.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime

from sqlalchemy import Connection

from rocky.offres.analysis.model import PostingAnalysis
from rocky.offres.analysis.rules import analyze, deadline_of
from rocky.offres.analysis.usecases import Summary
from rocky.offres.decisions import (
    AUTOMATIC_REASONS,
    Decision,
    DecisionValue,
    effective_decisions,
    reason_label,
)
from rocky.offres.imports.model import ImportResult
from rocky.offres.imports.usecases import import_link, link_sources
from rocky.offres.model import OfferHeading, Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import MESSAGE_SOURCE, CollectedOffer
from rocky.offres.sources.registry import build_sources
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import (
    add_offer_from_message,
    cancel_decision,
    record_decision,
    record_offer,
    stored_summary,
)
from rocky.profil.model import Profile
from rocky.system.config import SourcesSettings

# The HTMX event that refreshes the offers list; ``candidatures`` sends it when « Préparer » records a decision.
OFFERS_CHANGED = "offers-changed"


def offer_headings(
    connection: Connection, account_id: int, offer_ids: Iterable[int]
) -> dict[int, OfferHeading]:
    """The account's offers among ``offer_ids``; an offer of another account is absent."""
    return SqlStore(connection).headings(account_id, offer_ids)


def offer_analysis(
    connection: Connection,
    account_id: int,
    offer_id: int,
    profile: Profile,
    today: date,
) -> PostingAnalysis | None:
    """The analysis of an offer of the account with its profile's skills (D3: the CV of an application is targeted
    with it); None for an unknown offer or one of another account."""
    stored = SqlStore(connection).offer_of(account_id, offer_id)
    if stored is None:
        return None
    return analyze(stored.offer, scoring_inputs(profile).skills, today=today)


def offer_deadlines(
    connection: Connection, account_id: int, offer_ids: Iterable[int], today: date
) -> dict[int, date]:
    """The deadline of the account's offers among ``offer_ids`` that have one (the applications, decision D6, Q8)."""
    return {
        stored.id: deadline
        for stored in SqlStore(connection).offers_of(account_id, offer_ids)
        if (deadline := deadline_of(stored.offer, today=today)) is not None
    }


def decision_in_force(
    connection: Connection, account_id: int, offer_id: int
) -> DecisionValue | None:
    """The value of the offer's decision in force, None when it has none (to examine)."""
    rows = SqlStore(connection).decision_rows(account_id, offer_id)
    row = effective_decisions(rows).get(offer_id)
    return None if row is None or row.decision is None else row.decision.value


def interested_reason(
    connection: Connection, account_id: int, offer_id: int
) -> tuple[tuple[str, ...], str | None] | None:
    """The reasons (French labels) and the note of the offer's « Intéressé » in force (decision D4, Q15: the letter
    starts from why the user wants this offer); None when the decision in force is another one, or none."""
    rows = SqlStore(connection).decision_rows(account_id, offer_id)
    row = effective_decisions(rows).get(offer_id)
    if row is None or row.decision is None:
        return None
    decision = row.decision
    if decision.value is not DecisionValue.INTERESTED:
        return None
    automatic = {reason.code for reason in AUTOMATIC_REASONS[decision.value]}
    labels = tuple(
        reason_label(decision.value, code)
        for code in decision.reasons
        if code not in automatic
    )
    return labels, decision.note


def offer_summary(
    connection: Connection, account_id: int, offer_id: int
) -> Summary | None:
    """The summary kept for the offer (C7), unless its description changed since; never asks the model."""
    store = SqlStore(connection)
    stored = store.offer_of(account_id, offer_id)
    return None if stored is None else stored_summary(store, stored)


def interested_offers(connection: Connection, account_id: int) -> list[int]:
    """The account's offers whose decision in force is « Intéressé », the latest decided first (D3, Q26)."""
    rows = effective_decisions(SqlStore(connection).decision_rows(account_id))
    kept = [
        row
        for row in rows.values()
        if row.decision is not None and row.decision.value is DecisionValue.INTERESTED
    ]
    return [row.offer_id for row in sorted(kept, key=lambda row: row.id, reverse=True)]


def decided_moments(connection: Connection, account_id: int) -> list[datetime]:
    """When each offer of the account got its decision in force, the first first (the cockpit, decision G3, Q11)."""
    rows = effective_decisions(SqlStore(connection).decision_rows(account_id))
    return sorted(row.decided_at for row in rows.values())


def first_watch_at(connection: Connection, account_id: int) -> datetime | None:
    """When the account's first watch that brought offers in started (the start list of the cockpit, G3 Q12)."""
    run = SqlStore(connection).first_successful_run(account_id)
    return None if run is None else run.started_at


def record_application_decision(
    connection: Connection,
    *,
    account_id: int,
    offer_id: int,
    decision: Decision,
    now: datetime,
) -> int:
    """Record the « Intéressé » of « Préparer la candidature » (D1, Q8), with the best track's score shown."""
    return record_decision(
        SqlStore(connection),
        account_id=account_id,
        offer_id=offer_id,
        decision=decision,
        track_id=None,
        now=now,
    )


def record_message_offer(
    connection: Connection,
    *,
    account_id: int,
    message_id: int,
    company: str,
    title: str,
    link: str,
    profile: Profile,
    now: datetime,
    today: date,
) -> int:
    """The minimal offer of an application made outside Rocky, created from a message (decision E4, Q4, Q12): the
    employer and title the user confirmed, the posting's ``link`` (or the message's own link). Returns its id."""
    offer = CollectedOffer(
        source=MESSAGE_SOURCE,
        external_id=f"message-{message_id}",
        url=link,
        title=title,
        company=company or None,
        description="",
        description_complete=False,
        incomplete_reason="Créée depuis un message : colle la description de l'annonce pour la compléter.",
    )
    return add_offer_from_message(
        SqlStore(connection),
        account_id=account_id,
        offer=offer,
        inputs=scoring_inputs(profile),
        message_id=message_id,
        now=now,
        today=today,
    ).offer_id


def record_alert_offer(
    connection: Connection,
    *,
    account_id: int,
    offer: CollectedOffer,
    profile: Profile,
    now: datetime,
    today: date,
) -> tuple[int, bool]:
    """The offer of a card of a job alert (decision E3, Q3), with its best track and its scores: its id and whether it
    is new. A known offer is completed, never overwritten (C6, Q7). No event per offer, as for the watch: the reading
    of the alert is the fact (``messages.alert_read``)."""
    recorded = record_offer(
        SqlStore(connection),
        account_id=account_id,
        offer=offer,
        inputs=scoring_inputs(profile),
        origin=Origin.ALERT,
        now=now,
        today=today,
    )
    return recorded.offer_id, recorded.created


def complete_offer_keys(
    connection: Connection, account_id: int, keys: Iterable[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Among ``(source, external_id)`` keys, those of the account's offers already known with a complete description
    (decision E3: their posting is not read again)."""
    return SqlStore(connection).complete_keys(account_id, keys)


def try_lock_offers(connection: Connection, account_id: int) -> bool:
    """The lock of the account's offers for the transaction in progress; False while a watch holds it (decision E3)."""
    return SqlStore(connection).try_lock(account_id)


def cancel_application_decision(
    connection: Connection, *, account_id: int, decision_id: int, now: datetime
) -> bool:
    """Cancel the decision written with an application whose creation is cancelled (D1, Q9)."""
    return cancel_decision(
        SqlStore(connection), account_id=account_id, decision_id=decision_id, now=now
    )


type PostingReading = Callable[..., ImportResult]


def posting_pages(
    new_http: Callable[[], PublicHttp], settings: SourcesSettings
) -> Callable[[], AbstractContextManager[PostingReading]]:
    """Read posting links outside any request, as the import does (decision E3: the links of the job alerts, read by
    the planner): one public HTTP client per pass, closed after it. The reading is ``read(link, today=…)``."""

    @contextmanager
    def pages() -> Iterator[PostingReading]:
        http = new_http()
        try:
            sources = link_sources(build_sources(settings, http))

            def read(link: str, *, today: date) -> ImportResult:
                return import_link(link, http, sources, today=today)

            yield read
        finally:
            http.close()

    return pages
