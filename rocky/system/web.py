"""FastAPI application factory: settings, authentication, web shell, module routes and the planner."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from rocky.candidatures import web as candidatures_web
from rocky.offres import web as offres_web
from rocky.offres.watch.model import RESCORE_EVERY, WATCH_HOUR
from rocky.offres.watch.service import WatchService
from rocky.profil import web as profil_web
from rocky.system import shell
from rocky.system.auth.mail import Mailer, SmtpMailer
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import Argon2Hasher, Clock, PasswordHasher
from rocky.system.auth.web import AuthServices, install
from rocky.system.config import Settings, load_settings
from rocky.system.db import create_db_engine
from rocky.system.scheduler import DailyTask, PeriodicTask, Scheduler

# Expired sessions and tokens are purged at night (plan §8, B3 → C6).
PURGE_HOUR = time(4, 0)

# Each module keeps its templates next to its code; names are prefixed by the module ("offres/…").
TEMPLATE_DIRS = [
    Path(__file__).parent / "templates",
    candidatures_web.TEMPLATES,
    Path(offres_web.__file__).parent / "templates",
    Path(profil_web.__file__).parent / "templates",
]
STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    mailer: Mailer | None = None,
    hasher: PasswordHasher | None = None,
    clock: Clock = utc_now,
) -> FastAPI:
    """Create the application; invalid settings fail here, at startup.

    ``engine``, ``mailer``, ``hasher`` and ``clock`` are replaced by the tests.
    """
    settings = settings if settings is not None else load_settings()
    app = FastAPI(title="Rocky", lifespan=_lifespan)
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=TEMPLATE_DIRS)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.engine = engine = engine or create_db_engine(settings.database_url)
    # Starlette runs the middleware added last first: the onboarding gate, added before the session
    # middleware, sees the account that the session middleware found.
    app.middleware("http")(profil_web.onboarding_gate(profil_web.MAIN_PATHS))
    install(
        app,
        AuthServices(
            engine=engine,
            hasher=hasher or Argon2Hasher(),
            clock=clock,
            mailer=mailer or SmtpMailer(settings.smtp),
            public_url=settings.public_url,
            secure_cookies=settings.secure_cookies,
        ),
    )

    app.include_router(shell.router)
    offres_web.install(app)
    profil_web.install(app)
    candidatures_web.install(app)
    _plan(app, engine, clock)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _plan(app: FastAPI, engine: Engine, clock: Clock) -> None:
    """The single planner (D12) and its tasks; started by ``_lifespan`` when the settings allow it."""
    watch: WatchService = app.state.watch
    scheduler = Scheduler(
        daily=[
            DailyTask("veille", WATCH_HOUR, watch.run_scheduled),
            DailyTask("purge", PURGE_HOUR, lambda: purge_expired(engine, clock)),
        ],
        periodic=[PeriodicTask("recalcul", RESCORE_EVERY, watch.rescore_all)],
        clock=clock,
    )
    app.state.scheduler = scheduler
    # Q5: a profile change wakes the rescoring up (it rescores only when what the score reads changed).
    app.state.profile_changed = lambda account_id: scheduler.wake("recalcul")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    scheduler: Scheduler = app.state.scheduler
    if app.state.settings.scheduler_enabled:
        # First task: close the runs a stopped process left open.
        scheduler.submit("reprise", app.state.watch.recover)
        scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


def purge_expired(engine: Engine, clock: Clock) -> None:
    with engine.begin() as connection:
        purged_sessions, purged_tokens = SqlAuthStore(connection).purge_expired(clock())
    logger.info(
        "purged %s expired sessions and %s used or expired tokens",
        purged_sessions,
        purged_tokens,
    )
