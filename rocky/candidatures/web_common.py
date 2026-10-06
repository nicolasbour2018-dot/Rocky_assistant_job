"""What the routes of the applications share: the database, the clock, the fragments, the port to ``offres``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Connection, Engine

from rocky.candidatures.sql import SqlApplicationStore
from rocky.offres import web as offres_web
from rocky.offres.decisions import Decision, DecisionValue
from rocky.system.auth.model import Account


class OffresDecisions:
    """``OfferDecisions`` on the public functions of ``offres``, in the caller's transaction."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def decision_in_force(self, account_id: int, offer_id: int) -> DecisionValue | None:
        return offres_web.decision_in_force(self._conn, account_id, offer_id)

    def record_interested(
        self, account_id: int, offer_id: int, decision: Decision, now: datetime
    ) -> int:
        return offres_web.record_application_decision(
            self._conn,
            account_id=account_id,
            offer_id=offer_id,
            decision=decision,
            now=now,
        )

    def cancel(self, account_id: int, decision_id: int, now: datetime) -> bool:
        return offres_web.cancel_application_decision(
            self._conn, account_id=account_id, decision_id=decision_id, now=now
        )


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
