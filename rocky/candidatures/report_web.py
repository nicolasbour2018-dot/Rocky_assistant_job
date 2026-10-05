"""📈 Bilan (decision F1, Q9, Q10): the page, on the applications of the account and the acknowledgements given by
the module ``messages`` through ``app.state.acknowledged_applications`` (set by ``install``)."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse

from rocky.candidatures.report import Acknowledged, report_of
from rocky.candidatures.rules import Tab
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.web_common import engine_of
from rocky.system.auth.web import CurrentAccount
from rocky.system.shell import ENTRIES, Action, page

PAGE = "candidatures/report.html"
# Q10: the main action, the applications waiting for an answer (the tab « Suivi » of 📝 Candidatures).
FOLLOW_UP = Action(
    "Voir les candidatures en attente de réponse",
    f"/candidatures?vue={Tab.FOLLOW_UP.value}",
)
# Nothing sent yet: the applications to prepare or send.
APPLICATIONS = Action("Voir les candidatures", "/candidatures")

router = APIRouter()


def install(app: FastAPI, acknowledged: Acknowledged) -> None:
    app.state.acknowledged_applications = acknowledged
    app.include_router(router)


@router.get("/bilan", response_class=HTMLResponse)
def report_page(request: Request, account: CurrentAccount) -> HTMLResponse:
    with engine_of(request).connect() as connection:
        found = SqlApplicationStore(connection).applications_of(account.id)
    acknowledged: Acknowledged = request.app.state.acknowledged_applications
    report = report_of(
        ((application.id, changes) for application, changes in found),
        acknowledged(account.id),
    )
    return page(
        request,
        PAGE,
        active="report",
        context={
            "entry": ENTRIES["report"],
            "report": report,
            "action": FOLLOW_UP if report.sent else APPLICATIONS,
        },
    )
