"""FastAPI application factory: settings, authentication, web shell and module routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from rocky.offres import web as offres_web
from rocky.system import shell
from rocky.system.auth.mail import Mailer, SmtpMailer
from rocky.system.auth.usecases import Argon2Hasher, Clock, PasswordHasher
from rocky.system.auth.web import AuthServices, install
from rocky.system.config import Settings, load_settings
from rocky.system.db import create_db_engine

# Each module keeps its templates next to its code; names are prefixed by the module ("offres/…").
TEMPLATE_DIRS = [
    Path(__file__).parent / "templates",
    Path(offres_web.__file__).parent / "templates",
]
STATIC_DIR = Path(__file__).parent / "static"


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
    app = FastAPI(title="Rocky")
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=TEMPLATE_DIRS)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    install(
        app,
        AuthServices(
            engine=engine or create_db_engine(settings.database_url),
            hasher=hasher or Argon2Hasher(),
            clock=clock,
            mailer=mailer or SmtpMailer(settings.smtp),
            public_url=settings.public_url,
            secure_cookies=settings.secure_cookies,
        ),
    )

    app.include_router(shell.router)
    offres_web.install(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
