"""FastAPI application factory. The web shell (layout, Jinja, HTMX) comes in step B4."""

from __future__ import annotations

from fastapi import FastAPI

from rocky.system.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application; invalid settings fail here, at startup."""
    app = FastAPI(title="Rocky")
    app.state.settings = settings if settings is not None else load_settings()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
