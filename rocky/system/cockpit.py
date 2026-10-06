"""🧭 Cockpit (step G3, decision ``docs/decisions/G3-cockpit.md``): the home of Rocky, where the job search is steered.

It replaces 🏠 Aujourd'hui (Q8). Like the screens of F1, it imports no business module: each module registers its
parts (``add_cockpit``) and the cockpit lays them out (layout A, Q7): the instruments, then the action (the hero and
the suggestions) beside the progress and the feed. The cockpit chooses the hero (Q4, Q27), the one main gesture of
the screen (Q6) and the sentence of the day (Q3); it never computes a business figure itself.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from rocky.system.assistant.model import Fact
from rocky.system.assistant.registry import add_summary
from rocky.system.auth.model import Account
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.web import CurrentAccount
from rocky.system.clock import paris_day, today_of
from rocky.system.periods import Delta, Period
from rocky.system.shell import (
    ENTRIES,
    POLL_EVERY,
    Action,
    Card,
    page,
    wants_fragment,
)

# The parts of the cockpit come from these modules (a key is a module, or the watch of ``offres``).
COCKPIT_KEYS = ("veille", "offres", "candidatures", "messages")
# Q4, Q27: the hero is the first of these present (``demarrage`` until the first watch, Q12; ``veille``: nothing else
# to do, the watch to launch).
HERO_ORDER = ("demarrage", "relance", "prete", "en_cours", "offre", "veille")
# Q13: the instruments, in their order on screen.
INSTRUMENT_ORDER = ("offres", "dossiers", "semaine", "retours")
# The HTMX event after a gesture made in the cockpit (a decision, the goal): the cockpit reads itself again.
COCKPIT_CHANGED = "cockpit-changed"
# Q16: the window and the length of the feed.
FEED_DAYS = 7
FEED_LINES = 20
# Q3: the sentence of the day when no fact stands out; the same all day long.
SENTENCES = (
    "Une candidature soignée vaut mieux que dix envoyées à la hâte.",
    "Un petit pas chaque jour : c'est ainsi qu'une recherche avance.",
    "Chaque offre triée affine ce que Rocky te propose.",
    "Relancer, c'est montrer que le poste t'intéresse vraiment.",
    "Ton profil est à jour ? Les scores n'en sont que plus justes.",
    "Prends le temps de lire l'annonce : la lettre n'en sera que meilleure.",
    "Une réponse négative aussi fait avancer : elle libère de la place.",
)


@dataclass(frozen=True)
class StartStep:
    """A step of the start list (Q12): done, or the gesture that does it."""

    label: str
    done: bool
    action: Action | None = None


@dataclass(frozen=True)
class Hero:
    """A candidate for the hero of the cockpit (Q4, Q27); ``rank`` is one of ``HERO_ORDER``.

    ``primary`` is the gesture the hero offers first; it is the main one of the screen unless a problem takes it (Q6).
    ``steps``: the start list (Q12), whose first step not done carries ``primary``.
    """

    rank: str
    kind: str
    title: str
    lines: tuple[str, ...] = ()
    chips: tuple[str, ...] = ()
    primary: Action | None = None
    others: tuple[Action, ...] = ()
    steps: tuple[StartStep, ...] = ()


@dataclass(frozen=True)
class WeekDay:
    letter: str
    active: bool
    today: bool


@dataclass(frozen=True)
class Ring:
    """The goal of the week (Q9): ``done`` sent of ``goal``, the days of the week (Q10), the goal's form."""

    done: int
    goal: int
    days: tuple[WeekDay, ...] = ()
    goal_url: str | None = None
    goals: tuple[int, ...] = ()


@dataclass(frozen=True)
class Instrument:
    """An instrument (Q13): the figure now, its delta against last week at the same point (Q20), the screen it opens."""

    key: str
    title: str
    figure: str
    detail: str = ""
    delta: Delta | None = None
    # « arrivées », « ouverts »…: what the delta counts.
    delta_unit: str = ""
    link: Action | None = None
    ring: Ring | None = None
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class Series:
    """The chart of an instrument (Q22): one or two flows, one value per period, and the goal line of the week."""

    names: tuple[str, ...]
    labels: tuple[str, ...]
    values: tuple[tuple[int, ...], ...]
    goal: int | None = None

    @property
    def top(self) -> int:
        return max([1, self.goal or 0, *(v for flow in self.values for v in flow)])


@dataclass(frozen=True)
class FeedLine:
    """A line of the feed (Q16). ``standing``: a state rather than a fact (a follow-up due), shown first, never new;
    ``mine``: what the user did (the voice « toi »)."""

    at: datetime
    text: str
    link: Action | None = None
    mine: bool = False
    standing: bool = False


@dataclass(frozen=True)
class Sentence:
    """A sentence of the day citing one fact (Q3, Q23); the heaviest is said."""

    weight: int
    text: str


@dataclass(frozen=True)
class Suggestion:
    """An offer suggested under the hero (Q17), in the group of its track."""

    group: str
    score: int
    title: str
    subtitle: str
    url: str
    # The colour of the score as the offers screen gives it (« high », « mid »).
    level: str = ""


@dataclass(frozen=True)
class Milestone:
    label: str
    done: bool
    when: str = ""
    remaining: str | None = None


@dataclass(frozen=True)
class Progress:
    """The streaks and the milestones (Q10, Q11)."""

    day_streak: int
    week_streak: int
    last: Milestone | None
    next: Milestone | None
    milestones: tuple[Milestone, ...]


@dataclass(frozen=True)
class Status:
    """A line of the state of Rocky above the instruments (Q13): the watch, the mailboxes. ``polling``: the line is
    read again every 15 s (a watch running)."""

    text: str
    action: Action | None = None
    problem: bool = False
    polling: bool = False


type Provider[T] = Callable[[Request, Account], T]
type SeriesProvider = Callable[[Request, Account, str, Period], Series | None]
type FeedProvider = Callable[[Request, Account, datetime], Sequence[FeedLine]]
type SinceProvider = Callable[[Request, Account, datetime], Sequence[str]]


@dataclass(frozen=True)
class Parts:
    """What a module gives the cockpit; each part is optional."""

    heroes: Provider[Sequence[Hero]] | None = None
    instruments: Provider[Sequence[Instrument]] | None = None
    series: SeriesProvider | None = None
    feed: FeedProvider | None = None
    sentences: Provider[Sequence[Sentence]] | None = None
    suggestions: Provider[Sequence[Suggestion]] | None = None
    problems: Provider[Sequence[Card]] | None = None
    status: Provider[Sequence[Status]] | None = None
    progress: Provider[Progress | None] | None = None
    # What happened since the previous visit (« 12 offres », « 1 réponse »), and what to celebrate once (Q23).
    news: SinceProvider | None = None
    celebrations: SinceProvider | None = None


def add_cockpit(app: FastAPI, key: str, parts: Parts) -> None:
    """Register the parts of the module ``key`` (one of ``COCKPIT_KEYS``)."""
    if key not in COCKPIT_KEYS:
        raise KeyError(key)
    registered: dict[str, Parts] = getattr(app.state, "cockpit_parts", {})
    app.state.cockpit_parts = {**registered, key: parts}


def _parts(request: Request) -> list[Parts]:
    registered: dict[str, Parts] = getattr(request.app.state, "cockpit_parts", {})
    return [registered[key] for key in COCKPIT_KEYS if key in registered]


# Choices of the cockpit: pure


def pick_hero(candidates: Sequence[Hero]) -> Hero | None:
    """The first candidate in the order of ``HERO_ORDER`` (Q27); among the same rank, the first given."""
    ranked = [hero for hero in candidates if hero.rank in HERO_ORDER]
    return min(ranked, key=lambda hero: HERO_ORDER.index(hero.rank), default=None)


Main = Literal["problem", "hero", "none"]


def main_gesture(problems: Sequence[Card], hero: Hero | None) -> Main:
    """Who carries the one main button of the cockpit (Q6): a problem with a gesture, else the hero."""
    if any(card.action is not None for card in problems):
        return "problem"
    if hero is not None and hero.primary is not None:
        return "hero"
    return "none"


@dataclass(frozen=True)
class FeedEntry:
    line: FeedLine
    new: bool


@dataclass(frozen=True)
class FeedDay:
    label: str
    entries: tuple[FeedEntry, ...]


def day_label(day: date, today: date) -> str:
    if day == today:
        return "Aujourd'hui"
    if day == today - timedelta(days=1):
        return "Hier"
    names = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
    return f"{names[day.weekday()]} {day:%d/%m}"


def merge_feed(
    lines: Sequence[FeedLine], *, since: datetime | None, now: datetime
) -> tuple[tuple[FeedEntry, ...], tuple[FeedDay, ...]]:
    """The feed (Q16): the standing lines first, then the last ``FEED_DAYS`` days, the latest first, ``FEED_LINES`` in
    all; a fact after the previous visit is new (Q14)."""
    standing = tuple(FeedEntry(line, False) for line in lines if line.standing)
    start = now - timedelta(days=FEED_DAYS)
    facts = sorted(
        (line for line in lines if not line.standing and start <= line.at <= now),
        key=lambda line: line.at,
        reverse=True,
    )[: max(FEED_LINES - len(standing), 0)]
    today = paris_day(now)
    days = tuple(
        FeedDay(
            day_label(day, today),
            tuple(
                FeedEntry(line, since is not None and line.at > since) for line in found
            ),
        )
        for day, found in groupby(facts, key=lambda line: paris_day(line.at))
    )
    return standing, days


def pick_sentence(sentences: Sequence[Sentence], today: date) -> str:
    """The heaviest sentence (the first given among equals), else the sentence of the day (Q3)."""
    if sentences:
        return max(sentences, key=lambda s: s.weight).text
    return SENTENCES[today.toordinal() % len(SENTENCES)]


def group_suggestions(
    found: Sequence[Suggestion],
) -> list[tuple[str, list[Suggestion]]]:
    """The suggestions by group (a track, Q17), the groups in the order they come."""
    groups: dict[str, list[Suggestion]] = {}
    for suggestion in found:
        groups.setdefault(suggestion.group, []).append(suggestion)
    return list(groups.items())


def greeting(full_name: str | None) -> str:
    """« Bonjour » and the first word of the name (Q18)."""
    first = (full_name or "").split()
    return f"Bonjour {first[0]}" if first else "Bonjour"


# The screen

router = APIRouter()

# The name of the account's profile (``profil``, given by the composition).
type NameOf = Callable[[Request, Account], str | None]


def install(app: FastAPI, name_of: NameOf) -> None:
    app.state.cockpit_name = name_of
    # Decision G4 (Q11): what the cockpit shows is part of every question to the assistant.
    add_summary(app, "cockpit", cockpit_facts)
    app.include_router(router)


def _cockpit_context(
    request: Request, account: Account, since: datetime | None
) -> dict[str, object]:
    parts = _parts(request)
    now: datetime = request.app.state.auth.clock()
    today = today_of(request)
    problems = [c for p in parts if p.problems for c in p.problems(request, account)]
    hero = pick_hero([h for p in parts if p.heroes for h in p.heroes(request, account)])
    by_key = {
        i.key: i
        for p in parts
        if p.instruments
        for i in p.instruments(request, account)
    }
    status = [s for p in parts if p.status for s in p.status(request, account)]
    standing, days = merge_feed(
        [
            line
            for p in parts
            if p.feed
            for line in p.feed(request, account, now - timedelta(days=FEED_DAYS))
        ],
        since=since,
        now=now,
    )
    progress = next(
        (
            found
            for p in parts
            if p.progress and (found := p.progress(request, account))
        ),
        None,
    )
    name_of: NameOf = request.app.state.cockpit_name
    return {
        "entry": ENTRIES["today"],
        "greeting": greeting(name_of(request, account)),
        "sentence": pick_sentence(
            [s for p in parts if p.sentences for s in p.sentences(request, account)],
            today,
        ),
        "since": since,
        "news": (
            [n for p in parts if p.news for n in p.news(request, account, since)]
            if since is not None
            else []
        ),
        "celebrations": (
            [
                c
                for p in parts
                if p.celebrations
                for c in p.celebrations(request, account, since)
            ]
            if since is not None
            else []
        ),
        "problems": problems,
        "hero": hero,
        "main": main_gesture(problems, hero),
        "instruments": [by_key[key] for key in INSTRUMENT_ORDER if key in by_key],
        "suggestions": group_suggestions(
            [s for p in parts if p.suggestions for s in p.suggestions(request, account)]
        ),
        "progress": progress,
        "standing": standing,
        "days": days,
        "status": status,
        "polling": any(s.polling for s in status),
        "poll_every": POLL_EVERY,
    }


def _since(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.get("/", response_class=HTMLResponse)
def cockpit(
    request: Request, account: CurrentAccount, depuis: str = ""
) -> HTMLResponse:
    """🧭 Cockpit. A whole page records the visit and marks what happened since the previous one (Q14); a fragment
    (after a gesture of the cockpit) keeps the same previous visit, given back by ``depuis``."""
    templates: Jinja2Templates = request.app.state.templates
    if wants_fragment(request):
        context = _cockpit_context(request, account, _since(depuis))
        return templates.TemplateResponse(request, "cockpit/cockpit.html", context)
    engine = request.app.state.engine
    with engine.begin() as connection:
        since = SqlAuthStore(connection).swap_cockpit_visit(
            account.id, request.app.state.auth.clock()
        )
    context = _cockpit_context(request, account, since)
    return page(request, "cockpit/page.html", active="today", context=context)


@router.get("/cockpit/instrument/{key}", response_class=HTMLResponse)
def instrument(
    request: Request, account: CurrentAccount, key: str, periode: str = ""
) -> Response:
    """An instrument turned to its chart (Q21), on weeks or months; without ``periode``, turned back."""
    found = next(
        (
            i
            for p in _parts(request)
            if p.instruments
            for i in p.instruments(request, account)
            if i.key == key
        ),
        None,
    )
    if found is None:
        return Response(status_code=404)
    series: Series | None = None
    period: Period | None = None
    if periode:
        if periode not in Period:
            return Response(status_code=404)
        period = Period(periode)
        series = next(
            (
                s
                for p in _parts(request)
                if p.series and (s := p.series(request, account, key, period))
            ),
            None,
        )
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "cockpit/instrument.html",
        {"instrument": found, "series": series, "period": period, "Period": Period},
    )


@router.get("/cockpit/etat", response_class=HTMLResponse)
def status(request: Request, account: CurrentAccount) -> Response:
    """The state lines, read again while a watch runs; once it stops, the whole cockpit is read again."""
    lines = [s for p in _parts(request) if p.status for s in p.status(request, account)]
    polling = any(s.polling for s in lines)
    templates: Jinja2Templates = request.app.state.templates
    response = templates.TemplateResponse(
        request,
        "cockpit/status.html",
        {"status": lines, "polling": polling, "poll_every": POLL_EVERY},
    )
    if not polling:
        response.headers["HX-Trigger"] = COCKPIT_CHANGED
    return response


def changed() -> Response:
    """The answer of a gesture made from the cockpit: nothing to swap, the cockpit reads itself again."""
    return Response(
        status_code=200, headers={"HX-Trigger": COCKPIT_CHANGED, "HX-Reswap": "none"}
    )


@router.get("/cockpit/recharger")
def reload(account: CurrentAccount) -> Response:
    """« Revenir » from a panel of the hero."""
    return changed()


def cockpit_facts(request: Request, account: Account) -> list[Fact]:
    """What the cockpit shows, as facts for the assistant (decision G4, Q11): the problems, the priority of the moment
    (the hero), the instruments, the state of Rocky, the streaks and the feed of the last 7 days."""
    parts = _parts(request)
    now: datetime = request.app.state.auth.clock()
    facts: list[Fact] = []
    problems = [c for p in parts if p.problems for c in p.problems(request, account)]
    for index, card in enumerate(problems, start=1):
        facts.append(
            Fact(
                f"cockpit.probleme_{index}",
                "Problème",
                _joined(card.title, *card.lines),
                "/",
            )
        )
    hero = pick_hero([h for p in parts if p.heroes for h in p.heroes(request, account)])
    if hero is not None:
        steps = [
            f"{step.label} ({'fait' if step.done else 'à faire'})"
            for step in hero.steps
        ]
        facts.append(
            Fact(
                "cockpit.priorite",
                "Priorité du moment",
                _joined(hero.title, *hero.lines, *steps),
                hero.primary.url if hero.primary is not None else "/",
            )
        )
    for instrument in (
        i for p in parts if p.instruments for i in p.instruments(request, account)
    ):
        facts.append(_instrument_fact(instrument))
    for index, line in enumerate(
        (s for p in parts if p.status for s in p.status(request, account)), start=1
    ):
        facts.append(
            Fact(f"cockpit.etat_{index}", "État de Rocky", line.text, "/systeme")
        )
    progress = next(
        (
            found
            for p in parts
            if p.progress and (found := p.progress(request, account))
        ),
        None,
    )
    if progress is not None:
        text = (
            f"{progress.day_streak} jour(s) actif(s) d'affilée ; "
            f"{progress.week_streak} semaine(s) d'affilée à l'objectif"
        )
        if progress.last is not None:
            text += f" ; dernier jalon : {progress.last.label}"
        if progress.next is not None:
            text += f" ; prochain jalon : {progress.next.label}"
            if progress.next.remaining:
                text += f" ({progress.next.remaining})"
        facts.append(Fact("cockpit.progression", "Progression", text, "/"))
    feed = sorted(
        (
            line
            for p in parts
            if p.feed
            for line in p.feed(request, account, now - timedelta(days=FEED_DAYS))
        ),
        key=lambda line: line.at,
        reverse=True,
    )[:FEED_LINES]
    if feed:
        facts.append(
            Fact(
                "cockpit.fil",
                f"Ce qui s'est passé ces {FEED_DAYS} derniers jours",
                " ; ".join(
                    f"{paris_day(line.at):%d/%m}{' (toi)' if line.mine else ''} : {line.text}"
                    for line in feed
                ),
                "/",
                cut_first=True,
            )
        )
    return facts


def _instrument_fact(instrument: Instrument) -> Fact:
    texts = [f"{instrument.figure}", instrument.detail, *instrument.lines]
    if instrument.ring is not None:
        texts.append(
            f"{instrument.ring.done} envoyée(s) sur un objectif de {instrument.ring.goal}"
        )
    if instrument.delta is not None:
        unit = f" {instrument.delta_unit}" if instrument.delta_unit else ""
        texts.append(
            f"cette semaine {instrument.delta.now}{unit}, la semaine dernière au même jour "
            f"{instrument.delta.before}"
        )
    return Fact(
        f"cockpit.{instrument.key}",
        instrument.title,
        _joined(*texts),
        instrument.link.url if instrument.link is not None else "/",
    )


def _joined(*texts: str) -> str:
    return " ; ".join(text for text in texts if text)
