"""What 📝 Candidatures gives 🧭 Cockpit (decision G3): the heroes of the applications and the start list (Q4, Q12,
Q27), the instruments « Dossiers en cours », « Cette semaine » and « Retours » with their flows (Q9, Q13, Q20), the
progress (Q10, Q11), the lines of the feed (Q16), the sentences (Q3) and the celebrations (Q23); and the drawer 🐾 of
📝 Candidatures (decision F1, Q12).

Everything is read once per request (``_reading``). What ``candidatures`` cannot read itself comes through
``offres.api`` and ``profil.api`` (decision H4), the journal (``system.events``) and, for Gmail, a port given by the
composition (``messages`` imports ``candidatures``, decision F1, Q13).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request

from rocky.candidatures.dossier_web import dossier_url
from rocky.candidatures.model import (
    BEFORE_SENDING,
    FOLLOW_UP_STAGES,
    Change,
    Stage,
)
from rocky.candidatures.progress import (
    Milestone,
    Moments,
    Reached,
    Start,
    Week,
    active_day_streak,
    celebrations,
    days_of,
    goal_week_streak,
    last_reached,
    milestones,
    moments_of,
    next_milestone,
    started,
    week_days,
    week_of,
)
from rocky.candidatures.report import SENT_STAGES
from rocky.candidatures.rules import Step, Tab, standing
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.web import Row, rows_of
from rocky.candidatures.web_common import engine_of
from rocky.offres import api as offres_api
from rocky.offres.decisions import Author
from rocky.profil import api as profil_api
from rocky.profil.model import DEFAULT_WEEKLY_GOAL, WEEKLY_GOALS
from rocky.system import cockpit
from rocky.system.auth.model import Account
from rocky.system.clock import paris_day, today_of
from rocky.system.cockpit import (
    FeedLine,
    Hero,
    Instrument,
    Parts,
    Progress,
    Ring,
    Sentence,
    Series,
    StartStep,
    add_cockpit,
)
from rocky.system.events import first_occurrences, user_days
from rocky.system.periods import (
    Period,
    bucket_label,
    buckets,
    counts_by_bucket,
    week_delta,
)
from rocky.system.shell import Action

# When the account's first mailbox was connected (``messages``, given by the composition), None without one.
type GmailSince = Callable[[int], datetime | None]

# Q16: a deadline this close is signalled in the feed.
DEADLINE_DAYS = 3
# How far back the streak of active days is looked for.
ACTIVITY_DAYS = 400
GOAL_URL = "/profil/objectif"
READY_STAGES = frozenset({Stage.READY, Stage.PREFILLED})


def install(app: FastAPI, gmail_since: GmailSince) -> None:
    app.state.cockpit_gmail = gmail_since
    add_cockpit(
        app,
        "candidatures",
        Parts(
            heroes=_heroes,
            instruments=_instruments,
            series=_series,
            feed=_feed,
            sentences=_sentences,
            progress=_progress,
            news=_news,
            celebrations=_celebrations,
        ),
    )


@dataclass(frozen=True)
class Reading:
    rows: list[Row]
    found: list[tuple[int, list[Change]]]
    labels: dict[int, str]
    moments: Moments
    decided: list[datetime]
    active: set[date]
    start: Start
    goal: int
    today: date

    @property
    def week(self) -> Week:
        return week_of(self.moments.sent, self.goal, self.today)

    @property
    def milestones(self) -> tuple[Milestone, ...]:
        return milestones(self.start, self.moments, self.decided)


def _rows(request: Request, account: Account) -> list[Row]:
    """The rows of the screen 📝 Candidatures, read once per request (plan §8, D6 → F1)."""
    cached: list[Row] | None = getattr(request.state, "application_rows", None)
    if cached is None:
        with engine_of(request).connect() as connection:
            cached = rows_of(connection, account.id, today_of(request))
        request.state.application_rows = cached
    return cached


def _reading(request: Request, account: Account) -> Reading:
    cached: Reading | None = getattr(request.state, "cockpit_applications", None)
    if cached is not None:
        return cached
    today = today_of(request)
    gmail: GmailSince = request.app.state.cockpit_gmail
    rows = _rows(request, account)
    with engine_of(request).connect() as connection:
        applications = SqlApplicationStore(connection).applications_of(account.id)
        headings = offres_api.offer_headings(
            connection, account.id, [a.offer_id for a, _ in applications]
        )
        decided = offres_api.decided_moments(connection, account.id)
        first_watch = offres_api.first_watch_at(connection, account.id)
        profile = profil_api.stored_profile(connection, account.id)
        firsts = first_occurrences(
            connection, account.id, ("profil.track_created", "profil.profile_imported")
        )
        gestures = user_days(
            connection,
            account.id,
            ("offres", "candidatures"),
            request.app.state.auth.clock() - timedelta(days=ACTIVITY_DAYS),
        )
    found = [(a.id, changes) for a, changes in applications]
    labels = {
        a.id: label_of(headings[a.offer_id].title, headings[a.offer_id].company)
        for a, _ in applications
        if a.offer_id in headings
    }
    changes_days = {
        paris_day(c.changed_at)
        for _, changes in found
        for c in changes
        if c.author is Author.USER
    }
    gmail_at = gmail(account.id)
    start = Start(
        profile=Reached(
            profile is not None and profile.onboarding.completed_at is not None,
            profile.onboarding.completed_at if profile else None,
        ),
        track=Reached(
            bool(profile and profile.tracks), firsts.get("profil.track_created")
        ),
        cv=Reached(
            bool(profile and profile.experiences)
            or "profil.profile_imported" in firsts,
            firsts.get("profil.profile_imported"),
        ),
        gmail=Reached(gmail_at is not None, gmail_at),
        watch=Reached(first_watch is not None, first_watch),
    )
    cached = Reading(
        rows,
        found,
        labels,
        moments_of(found),
        decided,
        gestures | changes_days | set(days_of(decided)),
        start,
        profile.weekly_goal if profile else DEFAULT_WEEKLY_GOAL,
        today,
    )
    request.state.cockpit_applications = cached
    return cached


def label_of(title: str, company: str | None) -> str:
    return f"{title} chez {company}" if company else title


def _label(row: Row) -> str:
    return label_of(row.offer.title, row.offer.company)


# The heroes (Q4, Q12, Q27)

START_ACTIONS = (
    Action("Compléter ton profil", "/profil/demarrage"),
    Action("Définir une piste", "/profil/pistes"),
    Action("Importer ton CV", "/profil/kit"),
    Action("Connecter une boîte Gmail", "/messages"),
    Action("Lancer la veille", "/veille/lancer", post=True),
)


def start_hero(start: Start) -> Hero:
    """The start list (Q12): the five first milestones, each with its gesture; the first not done is the main one."""
    facts = (start.profile, start.track, start.cv, start.gmail, start.watch)
    labels = (
        "Profil complété",
        "Première piste",
        "CV importé",
        "Gmail connecté",
        "Première veille",
    )
    steps = tuple(
        StartStep(label, fact.done, None if fact.done else action)
        for label, fact, action in zip(labels, facts, START_ACTIONS, strict=True)
    )
    left = sum(1 for step in steps if not step.done)
    return Hero(
        "demarrage",
        "Pour démarrer",
        f"Encore {left} étape{'s' if left > 1 else ''} et Rocky cherche pour toi",
        primary=next((step.action for step in steps if step.action), None),
        steps=steps,
    )


def _by_due(row: Row) -> tuple[date, int]:
    return (row.next_action.due if row.next_action else date.max, row.id)


def _by_deadline(row: Row) -> tuple[date, date, int]:
    return (row.deadline or date.max, *_by_due(row))


def application_heroes(rows: Sequence[Row], today: date) -> list[Hero]:
    heroes: list[Hero] = []
    due = sorted(
        (r for r in rows if r.stage in FOLLOW_UP_STAGES and Tab.TO_DO in r.tabs),
        key=_by_due,
    )
    if due and due[0].next_action is not None:
        row, action = due[0], due[0].next_action
        late = action.due < today
        heroes.append(
            Hero(
                "relance",
                f"En retard depuis le {action.due:%d/%m}"
                if late
                else "À faire aujourd'hui",
                _label(row),
                (f"Prochaine action : {action.label}.",),
                primary=Action(action.label, dossier_url(row.id, Step.FOLLOW)),
                others=(Action("Voir la candidature", dossier_url(row.id)),),
            )
        )
    ready = sorted((r for r in rows if r.stage in READY_STAGES), key=_by_deadline)
    if ready:
        row = ready[0]
        heroes.append(
            Hero(
                "prete",
                "Un dossier est prêt à partir",
                _label(row),
                ("CV et lettre sont prêts : il ne reste qu'à l'envoyer.",),
                _deadline_chips(row),
                primary=Action(
                    "Envoyer la candidature", dossier_url(row.id, Step.SEND)
                ),
                others=(Action("Revoir le dossier", dossier_url(row.id)),),
            )
        )
    preparing = sorted(
        (r for r in rows if r.stage is Stage.PREPARING), key=_by_deadline
    )
    if preparing:
        row = preparing[0]
        heroes.append(
            Hero(
                "en_cours",
                "Un dossier à finir",
                _label(row),
                (
                    f"Prochaine action : {row.next_action.label}."
                    if row.next_action
                    else "Le dossier est commencé.",
                ),
                _deadline_chips(row),
                primary=Action("Continuer le dossier", dossier_url(row.id)),
            )
        )
    return heroes


def _deadline_chips(row: Row) -> tuple[str, ...]:
    return (f"Date limite le {row.deadline:%d/%m}",) if row.deadline else ()


def _heroes(request: Request, account: Account) -> list[Hero]:
    reading = _reading(request, account)
    heroes = application_heroes(reading.rows, reading.today)
    if not started(reading.start):
        heroes.append(start_hero(reading.start))
    return heroes


# The instruments (Q9, Q13, Q20)


def _streaks(reading: Reading) -> tuple[int, int]:
    return (
        active_day_streak(reading.active, reading.today),
        goal_week_streak(reading.moments.sent, reading.goal, reading.today),
    )


def application_instruments(reading: Reading) -> list[Instrument]:
    rows, today, moments = reading.rows, reading.today, reading.moments
    before = [r for r in rows if r.stage in BEFORE_SENDING]
    ready = sum(1 for r in before if r.stage in READY_STAGES)
    week = reading.week
    sent, answered = len(moments.sent), len(moments.answered)
    return [
        Instrument(
            "dossiers",
            "Dossiers en cours",
            str(len(before)),
            f"dont {ready} prêt{'s' if ready > 1 else ''} à envoyer"
            if before
            else "Un dossier s'ouvre depuis une offre.",
            week_delta(days_of(moments.opened), today),
            "ouverts",
            Action("Voir les dossiers", "/candidatures"),
        ),
        Instrument(
            "semaine",
            "Cette semaine",
            f"{week.sent}/{week.goal}",
            delta=week_delta(days_of(moments.sent), today),
            delta_unit="envoyées",
            ring=Ring(
                week.sent,
                week.goal,
                tuple(
                    cockpit.WeekDay(d.letter, d.active, d.today)
                    for d in week_days(reading.active, today)
                ),
                GOAL_URL,
                tuple(WEEKLY_GOALS),
            ),
        ),
        Instrument(
            "retours",
            "Retours",
            f"{answered}",
            f"réponse{'s' if answered > 1 else ''} sur {sent} envoyée{'s' if sent > 1 else ''}, "
            f"dont {len(moments.interviews)} entretien{'s' if len(moments.interviews) > 1 else ''}"
            if sent
            else "Les réponses arriveront après tes envois.",
            week_delta(days_of(moments.answered), today),
            f"réponse{'s' if answered > 1 else ''}",
            Action("Voir le bilan", "/bilan"),
        ),
    ]


def _instruments(request: Request, account: Account) -> list[Instrument]:
    return application_instruments(_reading(request, account))


def application_series(reading: Reading, key: str, period: Period) -> Series | None:
    starts = buckets(reading.today, period)
    labels = tuple(bucket_label(start, period) for start in starts)
    moments = reading.moments

    def flow(found: Sequence[datetime]) -> tuple[int, ...]:
        return counts_by_bucket(days_of(found), starts, period)

    if key == "dossiers":
        return Series(("Dossiers ouverts",), labels, (flow(moments.opened),))
    if key == "semaine":
        return Series(
            ("Candidatures envoyées",),
            labels,
            (flow(moments.sent),),
            reading.goal if period is Period.WEEK else None,
        )
    if key == "retours":
        return Series(
            ("Réponses de recruteurs", "Entretiens"),
            labels,
            (flow(moments.answered), flow(moments.interviews)),
        )
    return None


def _series(
    request: Request, account: Account, key: str, period: Period
) -> Series | None:
    if key not in ("dossiers", "semaine", "retours"):
        return None
    return application_series(_reading(request, account), key, period)


# The progress (Q10, Q11) and the celebrations (Q23)


def _cockpit_milestone(found: Milestone | None) -> cockpit.Milestone | None:
    if found is None:
        return None
    when = f"{paris_day(found.at):%d/%m}" if found.at else ""
    return cockpit.Milestone(found.label, found.done, when, found.remaining)


def progress_of(reading: Reading) -> Progress:
    found = reading.milestones
    days, weeks = _streaks(reading)
    shown = [m for m in (_cockpit_milestone(m) for m in found) if m is not None]
    return Progress(
        days,
        weeks,
        _cockpit_milestone(last_reached(found)),
        _cockpit_milestone(next_milestone(found)),
        tuple(shown),
    )


def _progress(request: Request, account: Account) -> Progress | None:
    reading = _reading(request, account)
    return progress_of(reading) if started(reading.start) else None


def _celebrations(request: Request, account: Account, since: datetime) -> list[str]:
    reading = _reading(request, account)
    return list(celebrations(reading.milestones, reading.week, since))


# The feed (Q16), the sentences (Q3), the news since the previous visit (Q14)


def sending_lines(
    found: Sequence[tuple[int, Sequence[Change]]],
    labels: dict[int, str],
    since: datetime,
) -> list[FeedLine]:
    """Each application sent since ``since``, at the time of its sending, in the voice of the user."""
    lines = []
    for application_id, changes in found:
        sent = next((c for c in standing(changes) if c.stage in SENT_STAGES), None)
        if sent is not None and sent.changed_at >= since:
            lines.append(
                FeedLine(
                    sent.changed_at,
                    f"Candidature envoyée : {labels.get(application_id, 'une candidature')}.",
                    mine=True,
                )
            )
    return lines


def state_lines(rows: Sequence[Row], today: date, at: datetime) -> list[FeedLine]:
    """The follow-ups due and the deadlines of the applications not sent within ``DEADLINE_DAYS`` days: states."""
    lines = [
        FeedLine(
            at,
            f"{row.next_action.label} : {_label(row)}"
            + (
                f" (depuis le {row.next_action.due:%d/%m})"
                if row.next_action.due < today
                else ""
            )
            + ".",
            Action("Ouvrir", dossier_url(row.id, Step.FOLLOW)),
            standing=True,
        )
        for row in sorted(rows, key=_by_due)
        if row.stage in FOLLOW_UP_STAGES and Tab.TO_DO in row.tabs and row.next_action
    ]
    lines += [
        FeedLine(
            at,
            f"Date limite le {row.deadline:%d/%m} : {_label(row)}.",
            Action("Ouvrir", dossier_url(row.id)),
            standing=True,
        )
        for row in rows
        if row.stage in BEFORE_SENDING
        and row.deadline is not None
        and today <= row.deadline <= today + timedelta(days=DEADLINE_DAYS)
    ]
    return lines


def _feed(request: Request, account: Account, since: datetime) -> list[FeedLine]:
    reading = _reading(request, account)
    lines = sending_lines(reading.found, reading.labels, since)
    lines += [
        FeedLine(m.at, f"Jalon franchi : {m.label}.", mine=True)
        for m in reading.milestones
        if m.done and m.at is not None and m.at >= since and not m.start
    ]
    week = reading.week
    if week.reached_at is not None and week.reached_at >= since:
        lines.append(
            FeedLine(
                week.reached_at,
                f"Objectif de la semaine atteint : {week.goal} sur {week.goal}.",
                mine=True,
            )
        )
    return lines + state_lines(reading.rows, reading.today, since)


def application_sentences(reading: Reading) -> list[Sentence]:
    rows, today, week = reading.rows, reading.today, reading.week
    sentences: list[Sentence] = []
    due = [r for r in rows if r.stage in FOLLOW_UP_STAGES and Tab.TO_DO in r.tabs]
    if due:
        sentences.append(
            Sentence(70, f"{_label(min(due, key=_by_due))} attend ta relance.")
        )
    ready = [r for r in rows if r.stage in READY_STAGES]
    if ready:
        row = min(ready, key=_by_deadline)
        sentences.append(
            Sentence(
                60, f"Ton dossier {_label(row)} est prêt : il ne reste qu'à l'envoyer."
            )
        )
    if week.remaining == 1:
        sentences.append(
            Sentence(50, "Plus qu'une candidature pour ton objectif de la semaine.")
        )
    elif week.remaining == 0:
        sentences.append(
            Sentence(
                40,
                f"Objectif de la semaine atteint : {week.sent} sur {week.goal}. Bravo.",
            )
        )
    days = active_day_streak(reading.active, today)
    if days >= 3:
        sentences.append(
            Sentence(20, f"{days} jours actifs d'affilée : continue sur ta lancée.")
        )
    return sentences


def _sentences(request: Request, account: Account) -> list[Sentence]:
    return application_sentences(_reading(request, account))


def _news(request: Request, account: Account, since: datetime) -> list[str]:
    count = sum(1 for m in _reading(request, account).moments.answered if m > since)
    return [f"{count} réponse{'s' if count > 1 else ''}"] if count else []
