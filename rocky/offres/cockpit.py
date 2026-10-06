"""What 🔎 Offres gives 🧭 Cockpit (decision G3): the best offer to examine as the hero (Q4, Q15), the best offers of
each track (Q17), the instrument « Offres à examiner » and its flows (Q13, Q20), the lines of the feed (Q16) and the
sentences that cite an offer (Q3).

The offers are read once per request (``_reading``), like the rows of the applications in ``candidatures``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request

from rocky.offres.decisions import DecisionKind, DecisionRow, effective_decisions
from rocky.offres.screen import HIGH_SCORE, ListedOffer, band, queue
from rocky.offres.sql import SqlStore
from rocky.offres.watch.model import RunStatus
from rocky.offres.watch.usecases import active_tracks
from rocky.profil import api as profil_api
from rocky.system.auth.model import Account
from rocky.system.clock import paris_day, today_of
from rocky.system.cockpit import (
    FeedLine,
    Hero,
    Instrument,
    Parts,
    Sentence,
    Series,
    Suggestion,
    add_cockpit,
)
from rocky.system.periods import (
    Period,
    bucket_label,
    buckets,
    counts_by_bucket,
    week_delta,
)
from rocky.system.shell import Action

# Q17 (Nicolas, on the mockup): the best offers of each active track, under the hero.
PER_TRACK = 2
# Q16: an offer to examine whose deadline is this close is signalled in the feed.
DEADLINE_DAYS = 3
TRIAGE_URL = "/offres?vue=tri"
# The cockpit's « contexte » for the decisions of its hero (``web.COCKPIT``).
COCKPIT = "cockpit"


def install(app: FastAPI) -> None:
    add_cockpit(
        app,
        "offres",
        Parts(
            heroes=_heroes,
            instruments=_instruments,
            series=_series,
            feed=_feed,
            sentences=_sentences,
            suggestions=_suggestions,
            news=_news,
        ),
    )


@dataclass(frozen=True)
class Reading:
    offers: list[ListedOffer]
    rows: list[DecisionRow]
    decisions: dict[int, DecisionRow]
    track_names: dict[int, str]
    active: frozenset[int]
    gmail_addressed: int


def _reading(request: Request, account: Account) -> Reading:
    cached: Reading | None = getattr(request.state, "cockpit_offers", None)
    if cached is None:
        with request.app.state.engine.connect() as connection:
            store = SqlStore(connection)
            offers = store.listed_offers(account.id)
            rows = store.decision_rows(account.id)
            profile = profil_api.stored_profile(connection, account.id)
            addressed = store.gmail_addressed(account.id)
        cached = Reading(
            offers,
            rows,
            effective_decisions(rows),
            {t.id: t.name for t in (profile.tracks if profile else ())},
            frozenset(t.id for t in active_tracks(profile)),
            addressed,
        )
        request.state.cockpit_offers = cached
    return cached


def waiting(reading: Reading, today: date) -> list[ListedOffer]:
    """The queue of the triage without the offers whose deadline is past: signalled, never proposed (G2, Q7)."""
    return [
        offer
        for offer in queue(reading.offers, reading.decisions)
        if offer.deadline is None or offer.deadline >= today
    ]


def _place(offer: ListedOffer) -> str:
    return ", ".join(part for part in (offer.company, offer.location) if part)


def _track(reading: Reading, offer: ListedOffer) -> str | None:
    track_id = offer.best.track_id
    return None if track_id is None else reading.track_names.get(track_id)


def offer_hero(offer: ListedOffer, track: str | None, why: tuple[str, ...]) -> Hero:
    """The best offer to examine (Q4): prepared in three clicks (Q15, criterion 1), decided in place."""
    chips = [f"Score {offer.best.display}"]
    if track:
        chips.append(track)
    if offer.deadline is not None:
        chips.append(f"Date limite le {offer.deadline:%d/%m}")
    return Hero(
        "offre",
        "La meilleure offre à examiner",
        offer.title,
        tuple(line for line in (_place(offer), *why) if line),
        tuple(chips),
        primary=Action(
            "Préparer la candidature",
            f"/candidatures/offre/{offer.id}/preparer?contexte={COCKPIT}",
            panel=True,
        ),
        others=(
            Action(
                "Pas pour moi",
                f"/offres/{offer.id}/motifs?decision=rejected&contexte={COCKPIT}",
                panel=True,
            ),
            Action(
                "Plus tard",
                f"/offres/{offer.id}/motifs?decision=later&contexte={COCKPIT}",
                panel=True,
            ),
            Action("Voir l'offre", f"/offres/{offer.id}/fiche"),
        ),
    )


def why_lines(skills: Sequence[str], gaps: Sequence[str]) -> tuple[str, ...]:
    """Why this offer, in a line or two: the skills of the profile it names, and what may be missing."""
    lines = []
    if skills:
        shown = ", ".join(skills[:4])
        more = len(skills) - 4
        lines.append(
            f"Compétences de ton profil citées : {shown}"
            + (f" et {more} autre{'s' if more > 1 else ''}" if more > 0 else "")
            + "."
        )
    if gaps:
        lines.append(f"À vérifier : {gaps[0]}.")
    return tuple(lines)


def _heroes(request: Request, account: Account) -> list[Hero]:
    reading = _reading(request, account)
    found = waiting(reading, today_of(request))
    if not found:
        return []
    best = found[0]
    with request.app.state.engine.connect() as connection:
        score = SqlStore(connection).current_score(best.id)
    why: tuple[str, ...] = ()
    if score is not None:
        top = score.best
        skills = [
            str(feature["skill"])
            for feature in top.features.get("skills", ())
            if isinstance(feature, dict) and feature.get("skill")
        ]
        why = why_lines(skills, top.gaps)
    return [offer_hero(best, _track(reading, best), why)]


def suggestions_of(
    offers: Sequence[ListedOffer],
    track_names: dict[int, str],
    active: frozenset[int],
    hero_id: int | None,
) -> list[Suggestion]:
    """The ``PER_TRACK`` best offers of each active track (Q17), the hero aside; the groups by their best score."""
    groups: dict[int, list[ListedOffer]] = {}
    for offer in offers:
        track_id = offer.best.track_id
        if offer.id == hero_id or track_id is None or track_id not in active:
            continue
        found = groups.setdefault(track_id, [])
        if len(found) < PER_TRACK:
            found.append(offer)
    return [
        Suggestion(
            track_names.get(track_id, "Piste"),
            offer.best.display,
            offer.title,
            _place(offer),
            f"/offres/{offer.id}/fiche",
            band(offer.best.display),
        )
        for track_id, found in groups.items()
        for offer in found
    ]


def _suggestions(request: Request, account: Account) -> list[Suggestion]:
    reading = _reading(request, account)
    found = waiting(reading, today_of(request))
    hero_id = found[0].id if found else None
    return suggestions_of(found, reading.track_names, reading.active, hero_id)


# The instrument (Q13, Q20)


def arrival_days(offers: Sequence[ListedOffer]) -> list[date]:
    """The days the offers above the threshold came in."""
    return [
        paris_day(offer.first_seen_at)
        for offer in offers
        if offer.first_seen_at is not None and not offer.below_threshold
    ]


def decided_days(rows: Sequence[DecisionRow]) -> list[date]:
    """The days of the decisions in force (a cancelled decision is no longer counted)."""
    return [paris_day(row.decided_at) for row in effective_decisions(rows).values()]


def offers_instrument(reading: Reading, today: date) -> Instrument:
    found = queue(reading.offers, reading.decisions)
    high = sum(1 for offer in found if offer.best.display >= HIGH_SCORE)
    return Instrument(
        "offres",
        "Offres à examiner",
        str(len(found)),
        f"dont {high} à {HIGH_SCORE} ou plus"
        if found
        else "Rien à trier pour l'instant.",
        week_delta(arrival_days(reading.offers), today),
        "arrivées au-dessus du seuil",
        Action("Trier les offres", TRIAGE_URL),
    )


def _instruments(request: Request, account: Account) -> list[Instrument]:
    return [offers_instrument(_reading(request, account), today_of(request))]


def offers_series(reading: Reading, today: date, period: Period) -> Series:
    starts = buckets(today, period)
    return Series(
        ("Arrivées au-dessus du seuil", "Décidées"),
        tuple(bucket_label(start, period) for start in starts),
        (
            counts_by_bucket(arrival_days(reading.offers), starts, period),
            counts_by_bucket(decided_days(reading.rows), starts, period),
        ),
    )


def _series(
    request: Request, account: Account, key: str, period: Period
) -> Series | None:
    if key != "offres":
        return None
    return offers_series(_reading(request, account), today_of(request), period)


# The feed (Q16) and the sentences (Q3)


def triage_lines(rows: Sequence[DecisionRow]) -> list[FeedLine]:
    """« 8 offres triées »: the decisions of a day, grouped (Q16), at the time of the last one."""
    by_day: dict[date, list[datetime]] = {}
    for row in rows:
        if row.kind is DecisionKind.DECISION:
            by_day.setdefault(paris_day(row.decided_at), []).append(row.decided_at)
    return [
        FeedLine(
            max(moments),
            f"{len(moments)} offre{'s' if len(moments) > 1 else ''} triée{'s' if len(moments) > 1 else ''}.",
            mine=True,
        )
        for moments in by_day.values()
    ]


def deadline_lines(
    offers: Sequence[ListedOffer], today: date, at: datetime
) -> list[FeedLine]:
    """The offers to examine whose deadline is within ``DEADLINE_DAYS`` days: a state, shown first."""
    soon = [
        offer
        for offer in offers
        if offer.deadline is not None
        and today <= offer.deadline <= today + timedelta(days=DEADLINE_DAYS)
    ]
    return [
        FeedLine(
            at,
            f"Date limite le {offer.deadline:%d/%m} : {offer.title}"
            + (f" ({offer.company})" if offer.company else "")
            + ".",
            Action("Voir l'offre", f"/offres/{offer.id}/fiche"),
            standing=True,
        )
        for offer in soon
        if offer.deadline is not None
    ]


def _feed(request: Request, account: Account, since: datetime) -> list[FeedLine]:
    reading = _reading(request, account)
    with request.app.state.engine.connect() as connection:
        runs = SqlStore(connection).finished_runs(account.id, since)
    lines: list[FeedLine] = []
    for run in runs:
        if run.finished_at is None:
            continue
        if run.status in (RunStatus.COMPLETED, RunStatus.PARTIAL):
            found = run.counts
            text = (
                f"Veille terminée : {found.found} offre{'s' if found.found > 1 else ''}, "
                f"dont {found.new} nouvelle{'s' if found.new > 1 else ''}."
            )
            # The way to the triage on the latest watch only.
            link = (
                Action("Trier", TRIAGE_URL) if found.new and run is runs[-1] else None
            )
        else:
            text = f"Veille {'interrompue' if run.status is RunStatus.INTERRUPTED else 'échouée'}."
            link = None
        lines.append(FeedLine(run.finished_at, text, link))
    lines += [line for line in triage_lines(reading.rows) if line.at >= since]
    lines += deadline_lines(
        queue(reading.offers, reading.decisions), today_of(request), since
    )
    if reading.gmail_addressed:
        count = reading.gmail_addressed
        s = "s" if count > 1 else ""
        lines.append(
            FeedLine(
                since,
                f"{count} offre{s} d'alerte sans adresse à compléter.",
                Action(
                    "Voir les offres incomplètes", "/offres?vue=liste&incompletes=1"
                ),
                standing=True,
            )
        )
    return lines


def offer_sentences(found: Sequence[ListedOffer]) -> list[Sentence]:
    if not found:
        return []
    high = sum(1 for offer in found if offer.best.display >= HIGH_SCORE)
    sentences = [
        Sentence(25, f"La meilleure offre du jour est à {found[0].best.display}.")
    ]
    if high > 1:
        sentences.append(
            Sentence(30, f"{high} offres à {HIGH_SCORE} ou plus t'attendent.")
        )
    return sentences


def _sentences(request: Request, account: Account) -> list[Sentence]:
    return offer_sentences(waiting(_reading(request, account), today_of(request)))


def _news(request: Request, account: Account, since: datetime) -> list[str]:
    reading = _reading(request, account)
    count = Counter(
        offer.first_seen_at > since
        for offer in reading.offers
        if offer.first_seen_at is not None and not offer.below_threshold
    )[True]
    if not count:
        return []
    return [
        f"{count} nouvelle{'s' if count > 1 else ''} offre{'s' if count > 1 else ''}"
    ]
