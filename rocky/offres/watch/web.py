"""The watch on screen: in 🧭 Cockpit (decision G3), a problem above the hero when it is late or failed, a line of
state always shown (Q13) and the hero « Lancer la veille » when nothing else is to do (Q27); the counter of 🧭, and
the panel of ⚙️ Système: the last run, source by source (decision F1, Q11).

The watch itself runs in the planner's thread, never in the request: its line is followed by polling.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from rocky.offres.sources.model import SOURCE_LABELS, SourceCode
from rocky.offres.sources.report import (
    UNAVAILABLE_HINTS,
    offers_found,
    skipped_queries,
)
from rocky.offres.sources.usecases import OUTCOME_LABELS, Outcome
from rocky.offres.watch.model import (
    RUN_STATUS_LABELS,
    TRIGGER_LABELS,
    RunStatus,
    SourceRun,
    Trigger,
    WatchBusyError,
    WatchRun,
)
from rocky.offres.watch.service import WatchService, WatchState, public_sources
from rocky.offres.watch.usecases import active_tracks
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.clock import paris_time
from rocky.system.cockpit import Hero, Parts, Status, add_cockpit
from rocky.system.scheduler import Scheduler
from rocky.system.shell import (
    Action,
    Card,
    add_badge,
    add_system_cards,
)

logger = logging.getLogger(__name__)

# The last run is shown when it brought nothing in.
SHOWN_FAILURES = frozenset({RunStatus.FAILED, RunStatus.INTERRUPTED})
LAUNCH = Action("Lancer la veille", "/veille/lancer", post=True)
ARRIVING = "Les nouvelles offres arrivent dans quelques minutes."
# ⚙️ Système launches the watch and stays there (a fixed value, never a URL).
LAUNCH_FROM_SYSTEM = Action(
    "Lancer la veille", "/veille/lancer?retour=systeme", post=True
)
RELAUNCH_FROM_SYSTEM = Action(
    "Lancer la veille", "/veille/lancer?retour=systeme", post=True
)
DEFINE_TRACK = Action("Définir une piste", "/profil/pistes")
# 🧭 Cockpit (decision G3, Q13, Q27): the watch launched from the cockpit comes back to it.
LAUNCH_WATCH = Action("Lancer la veille", "/veille/lancer", post=True)

router = APIRouter(prefix="/veille")


def install(app: FastAPI) -> None:
    settings = app.state.settings
    app.state.watch = WatchService(
        app.state.engine,
        sources=public_sources(settings.sources),
        limit=settings.sources.results_per_query,
        clock=app.state.auth.clock,
    )
    add_cockpit(
        app,
        "veille",
        Parts(heroes=_heroes, problems=today_cards, status=_status),
    )
    add_badge(app, "today", _late_or_failed)
    add_system_cards(app, "veille", system_cards)
    app.include_router(router)


def _task_name(account_id: int) -> str:
    return f"veille-compte-{account_id}"


def _watched(request: Request, account: Account) -> WatchState | None:
    """The state of the account's watch; None without an active track (the profile screen says so, not the watch)."""
    watch: WatchService = request.app.state.watch
    if not active_tracks(watch.profiles.profile(account.id)):
        return None
    return watch.state(account.id)


def _failed(state: WatchState) -> bool:
    return state.last is not None and state.last.status in SHOWN_FAILURES


def _late_or_failed(request: Request, account: Account) -> int:
    """The counter of 🏠 (decision F1, Q6): the watch asks for a gesture."""
    state = _watched(request, account)
    if state is None or state.running is not None:
        return 0
    return int(state.late or _failed(state))


def today_cards(request: Request, account: Account) -> list[Card]:
    """The problem of the watch in 🧭 Cockpit: late or failed (a running watch is a line of state, ``_status``). A watch
    never run is no problem: the start list proposes it (decision G3, Q12)."""
    state = _watched(request, account)
    if state is None or state.last is None:
        return []
    scheduler: Scheduler = request.app.state.scheduler
    card = watch_card(state, asked=_task_name(account.id) in scheduler.pending())
    return [] if card is None or not card.problem else [card]


def _status(request: Request, account: Account) -> list[Status]:
    state = _watched(request, account)
    if state is None:
        return [
            Status("Aucune piste active : la veille n'a rien à chercher.", DEFINE_TRACK)
        ]
    scheduler: Scheduler = request.app.state.scheduler
    return [status_line(state, asked=_task_name(account.id) in scheduler.pending())]


def status_line(state: WatchState, *, asked: bool) -> Status:
    """The watch in a line (Q13): running, asked, or its last run and « Lancer la veille »."""
    if state.running is not None:
        return Status(
            f"Veille en cours depuis le {paris_time(state.running.started_at)}.",
            polling=True,
        )
    if asked:
        return Status(
            "Veille lancée : les offres arrivent dans quelques minutes.", polling=True
        )
    last = state.last_successful
    if last is None:
        return Status("Aucune veille n'a encore réussi.", LAUNCH_WATCH, problem=True)
    counts = last.counts
    s = "s" if counts.found > 1 else ""
    return Status(
        f"Dernière veille le {paris_time(last.started_at)} : {counts.found} offre{s}, "
        f"dont {counts.new} nouvelle{'s' if counts.new > 1 else ''}.",
        LAUNCH_WATCH,
        problem=state.late or _failed(state),
    )


def _heroes(request: Request, account: Account) -> list[Hero]:
    """The start list until the first watch (Q12) is ``candidatures``'; then, nothing else to do: the watch (Q27)."""
    state = _watched(request, account)
    if state is None:
        return [
            Hero(
                "veille",
                "Rien à chercher",
                "Aucune piste active",
                ("Une piste dit à Rocky quelles offres chercher, et où.",),
                primary=DEFINE_TRACK,
            )
        ]
    if state.running is not None:
        return [
            Hero(
                "veille",
                "Veille en cours",
                "Rocky cherche de nouvelles offres",
                (ARRIVING,),
                primary=Action("Parcourir les offres", "/offres?vue=liste"),
            )
        ]
    next_run = _next_watch(request)
    return [
        Hero(
            "veille",
            "Tout est à jour",
            "Aucune offre à examiner, aucun dossier en attente",
            (f"Prochaine veille le {next_run}." if next_run else "",),
            primary=LAUNCH_WATCH,
            others=(Action("Voir tes pistes", "/profil/pistes"),),
        )
    ]


def _next_watch(request: Request) -> str | None:
    """The next scheduled watch, when the planner runs (decision F1, Q8)."""
    if not request.app.state.settings.scheduler_enabled:
        return None
    scheduler: Scheduler = request.app.state.scheduler
    return paris_time(scheduler.next_run("veille"))


def watch_card(state: WatchState, *, asked: bool) -> Card | None:
    """``asked``: a watch was asked and the planner has not written its run yet."""
    if state.running is not None:
        since = paris_time(state.running.started_at)
        return Card(
            "🔄 Veille en cours",
            (f"Veille en cours depuis le {since}.", ARRIVING),
            polling=True,
        )
    if asked:
        return Card("🔄 Veille lancée", (ARRIVING,), polling=True)
    last = state.last
    if state.late:
        title = "⏰ Veille en retard"
        if state.last_successful is None:
            lines: tuple[str, ...] = ("Aucune veille n'a encore réussi.",)
        else:
            since = paris_time(state.last_successful.started_at)
            lines = (f"La dernière veille réussie date du {since}.",)
    elif last is not None and last.status is RunStatus.INTERRUPTED:
        title = "⚠️ Veille interrompue"
        lines = (
            f"La dernière veille ({paris_time(last.started_at)}) a été interrompue.",
        )
    elif last is not None and last.status is RunStatus.FAILED:
        title = "⚠️ Veille échouée"
        lines = (f"La dernière veille ({paris_time(last.started_at)}) a échoué.",)
    else:
        return None
    if last is not None and last.reason and last.status in SHOWN_FAILURES:
        lines = (*lines, last.reason)
    return Card(title, lines, action=LAUNCH, problem=True)


def system_cards(request: Request, account: Account) -> list[Card]:
    """The panel « Veille » of ⚙️ Système: the last run and what each source gave in the last finished one."""
    state = _watched(request, account)
    if state is None:
        return [
            Card(
                "🔎 Veille",
                ("Aucune piste active : la veille n'a rien à chercher.",),
                action=DEFINE_TRACK,
            )
        ]
    watch: WatchService = request.app.state.watch
    scheduler: Scheduler = request.app.state.scheduler
    finished = state.last if state.running is None else state.last_successful
    sources = [] if finished is None else watch.source_runs(finished.id)
    return [
        system_card(
            state,
            sources,
            finished,
            asked=_task_name(account.id) in scheduler.pending(),
        )
    ]


def system_card(
    state: WatchState,
    sources: list[SourceRun],
    finished: WatchRun | None,
    *,
    asked: bool,
) -> Card:
    lines: list[str] = []
    if state.running is not None:
        lines.append(
            f"Veille en cours depuis le {paris_time(state.running.started_at)}."
        )
    elif asked:
        lines.append("Veille lancée : elle commence dans un instant.")
    if finished is None:
        lines.append("Aucune veille n'a encore tourné.")
    else:
        status = RUN_STATUS_LABELS[finished.status]
        lines.append(
            f"Dernière veille : {paris_time(finished.started_at)} · "
            f"{TRIGGER_LABELS[finished.trigger]} · {status}"
        )
        counts = finished.counts
        if finished.status in (RunStatus.COMPLETED, RunStatus.PARTIAL):
            s = "s" if counts.found > 1 else ""
            lines.append(
                f"{counts.found} offre{s} trouvée{s}, dont {counts.new} nouvelle"
                f"{'s' if counts.new > 1 else ''}."
            )
        if finished.reason:
            lines.append(finished.reason)
    if state.running is not None or asked:
        return Card("🔎 Veille", tuple(lines), _sources(sources), polling=True)
    failed = state.late or _failed(state)
    return Card(
        "🔎 Veille",
        tuple(lines),
        _sources(sources),
        action=RELAUNCH_FROM_SYSTEM if failed else LAUNCH_FROM_SYSTEM,
        problem=failed,
    )


def _sources(sources: list[SourceRun]) -> tuple[tuple[str, str], ...]:
    """One line per source, as ``rocky-admin sources`` says it (plan §8, C1 → F1): its state, what it gave, why."""
    return tuple((_source_label(run.source), source_line(run)) for run in sources)


def _source_label(source: str) -> str:
    try:
        return SOURCE_LABELS[SourceCode(source)]
    except ValueError:
        return source


def source_line(run: SourceRun) -> str:
    parts = [OUTCOME_LABELS[run.outcome]]
    if run.outcome in (Outcome.OK, Outcome.REFUSED, Outcome.FAILED) and (
        run.offers or run.outcome is Outcome.OK
    ):
        parts.append(offers_found(run.offers, run.incomplete))
    if run.reason:
        parts.append(run.reason)
    if run.outcome in UNAVAILABLE_HINTS:
        parts.append(UNAVAILABLE_HINTS[run.outcome])
    parts.extend(skipped_queries(reason for _, _, reason in run.skipped))
    if run.detail_stopped:
        parts.append(f"détail arrêté : {run.detail_stopped}")
    return " · ".join(parts)


@router.post("/lancer")
def launch(request: Request, account: CurrentAccount, retour: str = "") -> Response:
    """« Lancer maintenant »: a catch-up when the watch is late, else a watch asked by hand. Asking twice runs once.
    Back to 🏠 Aujourd'hui, which follows the watch, or to ⚙️ Système when asked from there."""
    watch: WatchService = request.app.state.watch
    scheduler: Scheduler = request.app.state.scheduler
    state = watch.state(account.id)
    name = _task_name(account.id)
    if state.running is None and name not in scheduler.pending():
        trigger = Trigger.CATCH_UP if state.late else Trigger.MANUAL
        scheduler.submit(name, lambda: run_quietly(watch, account.id, trigger))
    return RedirectResponse("/systeme" if retour == "systeme" else "/", status_code=303)


def run_quietly(watch: WatchService, account_id: int, trigger: Trigger) -> None:
    try:
        result = watch.run(account_id, trigger)
    except WatchBusyError:
        logger.info("watch of account %s already running", account_id)
        return
    logger.info(
        "watch run %s of account %s: %s", result.run_id, account_id, result.status
    )
