"""Use cases of the job alerts: read the alerts of an account that were never read, and turn their cards into offers.

Decision ``docs/decisions/E3-alertes.md``. At most 10 alerts give their offers per day, the most recent first, and an
alert older than 3 days gives nothing (Q8). A card always gives an offer, without the network (Q2); the posting of its
link is then read, outside any transaction, when it can be: never for a posting already known complete or a platform
that refused during this pass. Each alert is written in one transaction: its offers, what became of each link, its
reading and its event (Q5). The offers of the account are locked for that transaction: while a watch holds them,
nothing is written and the alerts wait for the next pass.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from rocky.messages.alerts.model import (
    ALERT_MAX_AGE,
    ALERTS_PER_DAY,
    NOT_TRIED_REASONS,
    PLATFORM_LABELS,
    AlertCard,
    AlertMessage,
    AlertsBusyError,
    AlertsReport,
    AlertStorage,
    CardResult,
    LinkOutcome,
    NotTried,
    PageReading,
    Platform,
    ReadingStatus,
)
from rocky.messages.alerts.rules import card_offer, cards, merged, reader_of
from rocky.messages.decisions.rules import paris_day
from rocky.offres.imports.model import ImportOutcome
from rocky.system.events import Actor, NewEvent
from rocky.system.scheduler import PARIS

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]

UNKNOWN_FORMAT_REASON = (
    "Rocky ne sait pas encore lire les alertes de cet expéditeur ({sender})."
)
NO_CARD_REASON = (
    "Aucune offre trouvée dans cette alerte : son format a peut-être changé."
)
TECHNICAL_REASON = "Erreur technique pendant la lecture de l'alerte (trace dans le journal de l'application)."
TOO_OLD_REASON = "Alerte de plus de 3 jours : aucune offre n'en est tirée."
DAY_LIMIT_REASON = "Au plus {limit} alertes par jour donnent leurs offres, les plus récentes d'abord : la suite demain."
PARTIAL_REASON = "La fiche a été lue, sans description complète."
NO_PROFILE_REASON = "Le compte n'a pas encore de profil : les offres des alertes ne peuvent pas être notées."

_OUTCOMES = {
    ImportOutcome.REFUSED: LinkOutcome.REFUSED,
    ImportOutcome.FAILED: LinkOutcome.FAILED,
    ImportOutcome.INVALID: LinkOutcome.INVALID,
}


class _OffersBusyError(Exception):
    """The offers of the account are locked by a watch: the alert is left for the next pass."""


@dataclass(frozen=True)
class _Reading:
    """What an alert gave before anything is written: its reader, its status and its cards, links already read."""

    platform: Platform | None
    status: ReadingStatus
    reason: str | None
    results: tuple[CardResult, ...] = ()


def read_alerts(
    storage: AlertStorage,
    page: PageReading | None,
    *,
    account_id: int,
    clock: Clock,
    per_day: int = ALERTS_PER_DAY,
    max_age: timedelta = ALERT_MAX_AGE,
) -> AlertsReport:
    """Read the alerts of the account never read, the most recent first, within the day's limit (Q8). ``page`` None:
    no posting is read (« sans liens »). Raises ``AlertsBusyError`` while another pass reads them."""
    with storage.alerts_lock(account_id) as locked:
        if not locked:
            raise AlertsBusyError(account_id)
        report = AlertsReport()
        now = clock()
        with storage.transaction() as store:
            alerts = store.alerts_to_read(account_id)
            has_profile = store.alert_offers(account_id) is not None
            left = per_day - store.alerts_read_since(account_id, _day_start(now))
        if alerts and not has_profile:
            report.postponed = len(alerts)
            report.reason = NO_PROFILE_REASON
            return report
        stopped: set[Platform] = set()
        for index, message in enumerate(alerts):
            if now - message.received_at > max_age:
                reading = _Reading(
                    reader_of(message), ReadingStatus.TOO_OLD, TOO_OLD_REASON
                )
            elif left <= 0:
                report.postponed += 1
                report.reason = DAY_LIMIT_REASON.format(limit=per_day)
                continue
            else:
                reading = _reading(storage, account_id, message, page, stopped, clock)
            try:
                # A failure of the database is not one of the alert: it is raised, nothing of the alert is written,
                # and the next pass reads it again.
                _write(storage, account_id, message, reading, report, clock)
            except _OffersBusyError:
                report.postponed = len(alerts) - index
                report.reason = None
                logger.info(
                    "offers of account %s are locked by a watch: %s alerts wait",
                    account_id,
                    report.postponed,
                )
                break
            if reading.status is ReadingStatus.READ:
                left -= 1
        return report


def _day_start(now: datetime) -> datetime:
    """Midnight of the day of ``now`` in Paris (the user's day, D12)."""
    return datetime.combine(paris_day(now), time(), tzinfo=PARIS)


def _reading(
    storage: AlertStorage,
    account_id: int,
    message: AlertMessage,
    page: PageReading | None,
    stopped: set[Platform],
    clock: Clock,
) -> _Reading:
    """What an alert gave, before anything is written: its cards, then (outside any transaction) their postings.

    A reader or a reading that breaks on an alert makes it « en échec »; the others go on. Neither the link (it may
    carry a tracking token) nor the message's content is logged."""
    platform = reader_of(message)
    if platform is None:
        return _Reading(
            None,
            ReadingStatus.UNKNOWN_FORMAT,
            UNKNOWN_FORMAT_REASON.format(sender=message.sender_address or "inconnu"),
        )
    try:
        found = cards(message, platform)
    except Exception:
        logger.exception("reader of alert %s failed unexpectedly", message.id)
        return _Reading(platform, ReadingStatus.FAILED, TECHNICAL_REASON)
    if not found:
        return _Reading(platform, ReadingStatus.NO_CARD, NO_CARD_REASON)
    with storage.transaction() as store:
        offers = store.alert_offers(account_id)
        known = (
            set()
            if offers is None
            else offers.complete_keys(
                account_id, [_identity(message, card, platform) for card in found]
            )
        )
    try:
        results = _postings(message, platform, found, page, known, stopped, clock)
    except Exception:
        logger.exception("reading of alert %s failed unexpectedly", message.id)
        return _Reading(platform, ReadingStatus.FAILED, TECHNICAL_REASON)
    return _Reading(platform, ReadingStatus.READ, None, results)


def _identity(
    message: AlertMessage, card: AlertCard, platform: Platform
) -> tuple[str, str]:
    offer = card_offer(message, card, platform, reason="")
    return offer.source, offer.external_id


def _postings(
    message: AlertMessage,
    platform: Platform,
    found: list[AlertCard],
    page: PageReading | None,
    known: set[tuple[str, str]],
    stopped: set[Platform],
    clock: Clock,
) -> tuple[CardResult, ...]:
    """The offer of each card, completed by its posting when it can be read (Q2), or with why it was not (Q5)."""
    now = clock()
    results: list[CardResult] = []
    for card in found:
        why = _not_tried(
            card,
            _identity(message, card, platform) in known,
            reading=page is not None,
            stopped=platform in stopped,
        )
        if why is not None or page is None or card.link is None:
            why = why or NotTried.NO_LINK
            reason = NOT_TRIED_REASONS[why]
            offer = card_offer(
                message, card, platform, reason=_incomplete(platform, reason)
            )
            results.append(CardResult(card, offer, LinkOutcome.NOT_TRIED, why, reason))
            continue
        imported = page(card.link, today=paris_day(now))
        if imported.preview is not None:
            posting = imported.preview.offer
            base = card_offer(
                message,
                card,
                platform,
                reason=posting.incomplete_reason
                or _incomplete(platform, PARTIAL_REASON),
            )
            results.append(CardResult(card, merged(base, posting), LinkOutcome.READ))
            continue
        if imported.outcome is ImportOutcome.REFUSED:
            # The stop rule of C1: a platform that refused is not asked again during this pass.
            stopped.add(platform)
        reason = imported.reason or TECHNICAL_REASON
        offer = card_offer(
            message, card, platform, reason=_incomplete(platform, reason)
        )
        results.append(
            CardResult(
                card,
                offer,
                _OUTCOMES.get(imported.outcome, LinkOutcome.FAILED),
                None,
                reason,
            )
        )
    return tuple(results)


def _not_tried(
    card: AlertCard, known: bool, *, reading: bool, stopped: bool
) -> NotTried | None:
    """Why the posting of a card is not read, or None when it is."""
    if known:
        return NotTried.KNOWN_COMPLETE
    if not reading:
        return NotTried.WITHOUT_LINKS
    if card.link is None:
        return NotTried.NO_LINK
    if stopped:
        return NotTried.HOST_STOPPED
    return None


def _incomplete(platform: Platform, reason: str) -> str:
    """Why the offer of a card has no description (shown in its sheet, Q5)."""
    return f"Tirée d'une alerte {PLATFORM_LABELS[platform]}. {reason}"


def _write(
    storage: AlertStorage,
    account_id: int,
    message: AlertMessage,
    reading: _Reading,
    report: AlertsReport,
    clock: Clock,
) -> None:
    """The reading of an alert, its offers and its event, in one transaction; nothing when another pass read it
    meanwhile. Raises ``_OffersBusyError`` (nothing written) while a watch holds the offers of the account."""
    now = clock()
    with storage.transaction() as store:
        offers = store.alert_offers(account_id) if reading.results else None
        if offers is None and reading.results:
            raise _OffersBusyError(account_id)
        if offers is not None and not offers.try_lock(account_id):
            raise _OffersBusyError(account_id)
        reading_id = store.add_reading(
            account_id,
            message.id,
            platform=reading.platform,
            status=reading.status,
            reason=reading.reason,
            cards=len(reading.results),
            now=now,
        )
        if reading_id is None:
            return
        created = 0
        if offers is not None:
            for result in reading.results:
                offer_id, new = offers.record(
                    account_id, result.offer, now=now, today=paris_day(now)
                )
                created += new
                store.add_alert_offer(
                    account_id, reading_id, result, offer_id=offer_id, created=new
                )
        read = sum(
            1 for result in reading.results if result.outcome is LinkOutcome.READ
        )
        store.append_event(
            NewEvent(
                type="messages.alert_read",
                actor=Actor.SYSTEM,
                subject_type="email_message",
                subject_id=str(message.id),
                # Counts only: never a link (it may carry a tracking token).
                payload={
                    "platform": None
                    if reading.platform is None
                    else reading.platform.value,
                    "status": reading.status.value,
                    "cards": len(reading.results),
                    "created": created,
                    "pages_read": read,
                    "pages_unread": len(reading.results) - read,
                },
                account_id=account_id,
            )
        )
    report.alerts += 1
    report.offers += len(reading.results)
    report.created += created
    report.pages_read += read
    report.pages_unread += len(reading.results) - read
    if reading.status is ReadingStatus.UNKNOWN_FORMAT:
        report.unknown_formats += 1
    if reading.status is ReadingStatus.FAILED:
        report.failed += 1
    if reading.status is ReadingStatus.TOO_OLD:
        report.too_old += 1
    if reading.platform is not None and reading.results:
        name = PLATFORM_LABELS[reading.platform]
        report.by_platform[name] = report.by_platform.get(name, 0) + len(
            reading.results
        )
