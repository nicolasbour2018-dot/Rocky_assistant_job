"""What the routes of the applications share: the database, the clock, the fragments."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from rocky.candidatures.sql import SqlApplicationStore
from rocky.system.auth.model import Account


def engine_of(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def now_of(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.auth.clock
    return clock()


def render_fragment(
    request: Request, name: str, context: Mapping[str, object]
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, name, dict(context))


def owns(request: Request, account: Account, application_id: int) -> bool:
    with engine_of(request).begin() as connection:
        store = SqlApplicationStore(connection)
        return store.locked_application(account.id, application_id) is not None
