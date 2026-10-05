"""The watch on screen: the first block of 🏠 Aujourd'hui when the watch is late, running or failed, with the gesture
that launches it (step C6, Q2; moved from a banner of every page by decision F1, Q6), and the counter of 🏠.

The watch itself runs in the planner's thread, never in the request: the block is followed by polling the screen.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rocky.offres.watch.model import RunStatus, Trigger, WatchBusyError
from rocky.offres.watch.service import WatchService, WatchState, public_sources
from rocky.offres.watch.usecases import active_tracks
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.scheduler import PARIS, Scheduler
from rocky.system.shell import Action, Card, add_badge, add_today_cards

logger = logging.getLogger(__name__)

# The last run is shown when it brought nothing in.
SHOWN_FAILURES = frozenset({RunStatus.FAILED, RunStatus.INTERRUPTED})
LAUNCH = Action("Lancer maintenant", "/veille/lancer", post=True)
ARRIVING = "Les nouvelles offres arrivent dans quelques minutes."

router = APIRouter(prefix="/veille")


def install(app: FastAPI) -> None:
    settings = app.state.settings
    app.state.watch = WatchService(
        app.state.engine,
        sources=public_sources(settings.sources),
        limit=settings.sources.results_per_query,
        clock=app.state.auth.clock,
    )
    templates: Jinja2Templates = app.state.templates
    templates.env.filters["paris_time"] = paris_time
    add_today_cards(app, "veille", today_cards)
    add_badge(app, "today", _late_or_failed)
    app.include_router(router)


def paris_time(moment: datetime) -> str:
    return moment.astimezone(PARIS).strftime("%d/%m à %H:%M")


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
    """The block « Veille » of 🏠 Aujourd'hui: running (followed by polling), late or failed; nothing when on time."""
    state = _watched(request, account)
    if state is None:
        return []
    scheduler: Scheduler = request.app.state.scheduler
    card = watch_card(state, asked=_task_name(account.id) in scheduler.pending())
    return [] if card is None else [card]


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


@router.post("/lancer")
def launch(request: Request, account: CurrentAccount) -> Response:
    """« Lancer maintenant »: a catch-up when the watch is late, else a watch asked by hand. Asking twice runs once.
    Back to 🏠 Aujourd'hui, which follows the watch."""
    watch: WatchService = request.app.state.watch
    scheduler: Scheduler = request.app.state.scheduler
    state = watch.state(account.id)
    name = _task_name(account.id)
    if state.running is None and name not in scheduler.pending():
        trigger = Trigger.CATCH_UP if state.late else Trigger.MANUAL
        scheduler.submit(name, lambda: run_quietly(watch, account.id, trigger))
    return RedirectResponse("/", status_code=303)


def run_quietly(watch: WatchService, account_id: int, trigger: Trigger) -> None:
    try:
        result = watch.run(account_id, trigger)
    except WatchBusyError:
        logger.info("watch of account %s already running", account_id)
        return
    logger.info(
        "watch run %s of account %s: %s", result.run_id, account_id, result.status
    )
