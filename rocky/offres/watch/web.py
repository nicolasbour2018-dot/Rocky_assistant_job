"""The watch on screen (step C6, Q2): a banner above every page when the watch is late, running or failed, with the
gesture that launches it. F1 moves it into « Aujourd'hui ».

The watch itself runs in the planner's thread, never in the request: the banner follows it by polling.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from rocky.offres.watch.model import RunStatus, Trigger, WatchBusyError
from rocky.offres.watch.service import WatchService, public_sources
from rocky.offres.watch.usecases import active_tracks
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.scheduler import PARIS, Scheduler
from rocky.system.shell import add_notice, is_htmx

logger = logging.getLogger(__name__)

BANNER = "offres/watch_banner.html"
EMPTY_BANNER = Markup('<div id="veille-bandeau" hidden></div>')
# The last run is shown when it brought nothing in.
SHOWN_FAILURES = frozenset({RunStatus.FAILED, RunStatus.INTERRUPTED})

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
    add_notice(app, banner)
    app.include_router(router)


def paris_time(moment: datetime) -> str:
    return moment.astimezone(PARIS).strftime("%d/%m à %H:%M")


def banner(request: Request, account: Account) -> Markup | None:
    """The banner of the watch, or None when it is on time and did not fail."""
    context = _banner_context(request, account, launched=False)
    return None if context is None else _render(request, context)


def _banner_context(
    request: Request, account: Account, *, launched: bool
) -> dict[str, Any] | None:
    watch: WatchService = request.app.state.watch
    state = watch.state(account.id)
    if launched or state.running is not None:
        return {"kind": "running", "state": state}
    failed = state.last is not None and state.last.status in SHOWN_FAILURES
    if not (state.late or failed):
        return None
    # Without an active track there is nothing to watch: the profile screen says so, not this banner.
    if not active_tracks(watch.profiles.profile(account.id)):
        return None
    return {"kind": "late" if state.late else "failed", "state": state}


def _render(request: Request, context: dict[str, Any]) -> Markup:
    templates: Jinja2Templates = request.app.state.templates
    return Markup(templates.get_template(BANNER).render(context))


@router.get("/bandeau", response_class=HTMLResponse)
def banner_fragment(request: Request, account: CurrentAccount) -> HTMLResponse:
    """The banner alone, polled while a watch runs."""
    context = _banner_context(request, account, launched=False)
    return HTMLResponse(EMPTY_BANNER if context is None else _render(request, context))


@router.post("/lancer", response_class=HTMLResponse)
def launch(request: Request, account: CurrentAccount) -> Response:
    """« Lancer maintenant »: a catch-up when the watch is late, else a watch asked by hand. Asking twice runs once."""
    watch: WatchService = request.app.state.watch
    scheduler: Scheduler = request.app.state.scheduler
    state = watch.state(account.id)
    name = f"veille-compte-{account.id}"
    if state.running is None and name not in scheduler.pending():
        trigger = Trigger.CATCH_UP if state.late else Trigger.MANUAL
        scheduler.submit(name, lambda: run_quietly(watch, account.id, trigger))
    if not is_htmx(request):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_render(request, {"kind": "running", "state": state}))


def run_quietly(watch: WatchService, account_id: int, trigger: Trigger) -> None:
    try:
        result = watch.run(account_id, trigger)
    except WatchBusyError:
        logger.info("watch of account %s already running", account_id)
        return
    logger.info(
        "watch run %s of account %s: %s", result.run_id, account_id, result.status
    )
