"""The progress of a job search shown by the cockpit (decision G3, Q2, Q9–Q12, Q23): the goal of the week, the two
streaks and the milestones.

Pure functions on what is already stored (the changes of the applications, the decisions on the offers, the journal):
nothing is counted in a table, so nothing can drift. The sending of an application is the moment it first reached a
« sent » stage among the changes in force, as in 📈 Bilan (``report.SENT_STAGES``): a cancelled sending never counts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from rocky.candidatures.model import Change, ChangeKind, Stage
from rocky.candidatures.report import HUMAN_ANSWERS, SENT_STAGES
from rocky.candidatures.rules import standing
from rocky.system.clock import paris_day
from rocky.system.periods import week_start

# Q9: the goal of the week, chosen by the user (``profil``), and its bounds.
DEFAULT_GOAL = 3
WEEKDAY_LETTERS = ("L", "M", "M", "J", "V")


@dataclass(frozen=True)
class Moments:
    """When each application of the account was opened, sent, answered… (each its first time, in force)."""

    opened: tuple[datetime, ...] = ()
    sent: tuple[datetime, ...] = ()
    answered: tuple[datetime, ...] = ()
    interviews: tuple[datetime, ...] = ()
    job_offers: tuple[datetime, ...] = ()


def moments_of(found: Iterable[tuple[int, Sequence[Change]]]) -> Moments:
    """``found``: each application with its changes. A cancelled change never counts (``rules.standing``)."""
    opened: list[datetime] = []
    sent: list[datetime] = []
    answered: list[datetime] = []
    interviews: list[datetime] = []
    job_offers: list[datetime] = []
    for _, changes in found:
        kept = standing(changes)
        creation = next((c for c in kept if c.kind is ChangeKind.CREATED), None)
        if creation is None:
            continue
        opened.append(creation.changed_at)
        for target, stages in (
            (sent, SENT_STAGES),
            (answered, HUMAN_ANSWERS),
            (interviews, frozenset({Stage.INTERVIEW})),
            (job_offers, frozenset({Stage.OFFER})),
        ):
            first = next((c for c in kept if c.stage in stages), None)
            if first is not None:
                target.append(first.changed_at)
    return Moments(
        tuple(sorted(opened)),
        tuple(sorted(sent)),
        tuple(sorted(answered)),
        tuple(sorted(interviews)),
        tuple(sorted(job_offers)),
    )


def days_of(moments: Iterable[datetime]) -> list[date]:
    return [paris_day(moment) for moment in moments]


# The goal of the week (Q9) and the streaks (Q10, Q19)


@dataclass(frozen=True)
class Week:
    sent: int
    goal: int
    # When the goal was reached this week (the sending that reached it), None before.
    reached_at: datetime | None

    @property
    def remaining(self) -> int:
        return max(self.goal - self.sent, 0)


def week_of(sent: Sequence[datetime], goal: int, today: date) -> Week:
    start = week_start(today)
    this_week = sorted(m for m in sent if start <= paris_day(m) <= today)
    reached = this_week[goal - 1] if len(this_week) >= goal else None
    return Week(len(this_week), goal, reached)


def active_day_streak(active: Iterable[date], today: date) -> int:
    """Active days in a row (Q10 a, Q19): from Monday to Friday a day without a gesture breaks the streak; a weekend
    day never breaks it, and counts when something was done. Today counts once it is active, and never breaks it."""
    days = set(active)
    if not days:
        return 0
    first = min(days)
    streak = 0
    day = today if today in days else today - timedelta(days=1)
    while day >= first:
        if day in days:
            streak += 1
        elif day.weekday() < 5:
            break
        day -= timedelta(days=1)
    return streak


def goal_week_streak(sent: Sequence[datetime], goal: int, today: date) -> int:
    """Weeks in a row with the goal reached (Q10 b), with the goal of today (plan §8): the week in progress counts once
    reached and never breaks the streak."""
    counts: dict[date, int] = {}
    for moment in sent:
        start = week_start(paris_day(moment))
        counts[start] = counts.get(start, 0) + 1
    current = week_start(today)
    week = current if counts.get(current, 0) >= goal else current - timedelta(days=7)
    streak = 0
    while counts.get(week, 0) >= goal:
        streak += 1
        week -= timedelta(days=7)
    return streak


@dataclass(frozen=True)
class WeekDay:
    letter: str
    active: bool
    today: bool


def week_days(active: Iterable[date], today: date) -> tuple[WeekDay, ...]:
    """Monday to Friday of this week (Q10): each with its gesture or not."""
    days = set(active)
    start = week_start(today)
    return tuple(
        WeekDay(
            letter,
            (start + timedelta(days=index)) in days,
            start + timedelta(days=index) == today,
        )
        for index, letter in enumerate(WEEKDAY_LETTERS)
    )


# The milestones (Q11, Q12)


@dataclass(frozen=True)
class Reached:
    """A fact of the start: done or not, and when when it is known (an account older than its event has no date)."""

    done: bool
    at: datetime | None = None


@dataclass(frozen=True)
class Start:
    profile: Reached = Reached(False)
    track: Reached = Reached(False)
    cv: Reached = Reached(False)
    gmail: Reached = Reached(False)
    watch: Reached = Reached(False)


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    done: bool
    at: datetime | None
    # What is left for a milestone counted (« encore 3 envois »), None otherwise.
    remaining: str | None = None
    start: bool = False


START_LABELS = (
    ("profil", "Profil complété"),
    ("piste", "Première piste"),
    ("cv", "CV importé"),
    ("gmail", "Gmail connecté"),
    ("veille", "Première veille"),
)


def _counted(
    key: str, moments: Sequence[datetime], count: int, label: str, unit: str
) -> Milestone:
    done = len(moments) >= count
    left = count - len(moments)
    return Milestone(
        key,
        label,
        done,
        moments[count - 1] if done else None,
        None if done else f"encore {left} {unit}{'s' if left > 1 else ''}",
    )


def _first(key: str, moments: Sequence[datetime], label: str) -> Milestone:
    return Milestone(key, label, bool(moments), moments[0] if moments else None)


def milestones(
    start: Start, moments: Moments, decided: Sequence[datetime]
) -> tuple[Milestone, ...]:
    """Every milestone, in the order they are usually reached: the next one is the first not reached (Q11).

    ``decided``: when each offer got its decision in force, sorted.
    """
    facts = (start.profile, start.track, start.cv, start.gmail, start.watch)
    found = [
        Milestone(key, label, fact.done, fact.at, start=True)
        for (key, label), fact in zip(START_LABELS, facts, strict=True)
    ]
    sent, decided_ = moments.sent, tuple(sorted(decided))
    found += [
        _counted("tri-10", decided_, 10, "10 offres décidées", "offre"),
        _first("dossier", moments.opened, "Premier dossier ouvert"),
        _counted("envoi-1", sent, 1, "Première candidature envoyée", "envoi"),
        _counted("tri-50", decided_, 50, "50 offres décidées", "offre"),
        _counted("envoi-5", sent, 5, "5 candidatures envoyées", "envoi"),
        _first("reponse", moments.answered, "Première réponse d'un recruteur"),
        _counted("envoi-10", sent, 10, "10 candidatures envoyées", "envoi"),
        _first("entretien", moments.interviews, "Premier entretien"),
        _counted("tri-100", decided_, 100, "100 offres décidées", "offre"),
        _counted("envoi-25", sent, 25, "25 candidatures envoyées", "envoi"),
        _first("offre", moments.job_offers, "Première offre d'emploi"),
        _counted("envoi-50", sent, 50, "50 candidatures envoyées", "envoi"),
    ]
    return tuple(found)


def last_reached(found: Sequence[Milestone]) -> Milestone | None:
    dated = [(m.at, index, m) for index, m in enumerate(found) if m.done and m.at]
    return max(dated)[2] if dated else None


def next_milestone(found: Sequence[Milestone]) -> Milestone | None:
    return next((m for m in found if not m.done), None)


def started(start: Start) -> bool:
    """The start list leaves the cockpit after the first watch (Q12)."""
    return start.watch.done


def celebrations(
    found: Sequence[Milestone], week: Week, since: datetime | None
) -> tuple[str, ...]:
    """What the cockpit celebrates once (Q23): reached after the previous visit; nothing on the very first one."""
    if since is None:
        return ()
    shown = [
        f"Jalon franchi : {m.label.lower() if m.start else m.label}."
        for m in found
        if m.done and m.at is not None and m.at > since
    ]
    if week.reached_at is not None and week.reached_at > since:
        shown.insert(
            0, f"Objectif de la semaine atteint : {week.sent} sur {week.goal}."
        )
    return tuple(shown)
