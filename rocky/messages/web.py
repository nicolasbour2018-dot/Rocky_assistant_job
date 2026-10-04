"""📬 Messages (step E1, Q8): the Gmail mailboxes of the account, « Relever maintenant », the raw list of the last
messages collected. Nothing is decided here (E2, E4).

A collection runs in the planner's thread, never in a request: the screen follows it by polling a fragment. Only
the return from Google (the exchange of its code) calls Google inside a request.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rocky.messages.model import (
    MAILBOX_STATUS_LABELS,
    QUERY_LABELS,
    SYNC_STATUS_LABELS,
    GmailError,
    MailboxStatus,
    SyncStatus,
    Trigger,
)
from rocky.messages.oauth import (
    CALLBACK_PATH,
    STATE_MAX_AGE,
    authorization_url,
    new_authorization,
    open_pending,
    redirect_uri,
    seal_pending,
)
from rocky.messages.service import MessagesService, nothing_decided
from rocky.messages.usecases import (
    CollectBusyError,
    MailboxNotConnectedError,
    MailboxNotFoundError,
)
from rocky.system.auth.web import CurrentAccount
from rocky.system.scheduler import Scheduler
from rocky.system.shell import is_htmx, page, wants_fragment

logger = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"
PAGE = "messages/page.html"
CONTENT = "messages/content.html"
STATE_COOKIE = "rocky_gmail_oauth"
COOKIE_PATH = "/messages/gmail"

# What a redirection to the page says (``?boite=…``): fixed texts, never a value from the address.
NOTICES = {
    "connectee": "Boîte connectée : sa première collecte est lancée.",
    "reconnectee": "Boîte reconnectée : la collecte reprend.",
    "deconnectee": "Boîte déconnectée : Rocky n'y a plus accès, ses messages restent.",
    "revocation": (
        "Boîte déconnectée, mais Google n'a pas pu être prévenu : retire l'accès de Rocky dans ton compte Google "
        "(Sécurité, « Applications tierces »)."
    ),
}
NOT_CONFIGURED = (
    "Gmail n'est pas configuré : il manque le client Google ou la clé de Rocky "
    "(docs/procedures/e1-gmail/)."
)
EXPIRED = (
    "La demande d'autorisation a expiré ou ne vient pas de cette page : "
    "recommence « Connecter une boîte Gmail »."
)
REFUSED = "Tu as refusé l'accès chez Google : aucune boîte n'a été connectée."
_ERROR_CODE = re.compile(r"^[a-z_]{1,40}$")

router = APIRouter(prefix="/messages")


def install(app: FastAPI) -> None:
    settings = app.state.settings
    # E2 and E4 replace this hook on app.state: it is read again at each collection, never kept here.
    app.state.messages_collected = nothing_decided

    def collected(account_id: int, message_ids: Sequence[int]) -> None:
        app.state.messages_collected(account_id, message_ids)

    app.state.messages = MessagesService(
        app.state.engine,
        settings=settings.gmail,
        clock=app.state.auth.clock,
        on_collected=collected,
    )
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        mailbox_status_labels=MAILBOX_STATUS_LABELS,
        sync_status_labels=SYNC_STATUS_LABELS,
        query_labels=QUERY_LABELS,
    )
    app.include_router(router)


def _service(request: Request) -> MessagesService:
    service: MessagesService = request.app.state.messages
    return service


def _task_name(account_id: int) -> str:
    return f"messages-compte-{account_id}"


def _context(
    request: Request, account_id: int, *, launched: bool = False, **extra: Any
) -> dict[str, Any]:
    """``launched``: a collection was just asked. The planner may already have taken it from its queue without having
    written its row yet: the screen polls all the same, or it would show the previous collection."""
    service = _service(request)
    state = service.state(account_id)
    scheduler: Scheduler = request.app.state.scheduler
    return {
        "configured": service.configured,
        "state": state,
        "running": launched
        or state.running
        or _task_name(account_id) in scheduler.pending(),
        "MailboxStatus": MailboxStatus,
        "SyncStatus": SyncStatus,
        **extra,
    }


def _page(
    request: Request, account_id: int, *, status_code: int = 200, **extra: Any
) -> HTMLResponse:
    return page(
        request,
        PAGE,
        active="messages",
        status_code=status_code,
        context=_context(request, account_id, **extra),
    )


@router.get("", response_class=HTMLResponse)
def show(request: Request, account: CurrentAccount, boite: str = "") -> HTMLResponse:
    # After a connection, its first collection was just asked (``callback``).
    launched = boite in ("connectee", "reconnectee")
    return _page(request, account.id, notice=NOTICES.get(boite), launched=launched)


@router.get("/contenu", response_class=HTMLResponse)
def content_fragment(request: Request, account: CurrentAccount) -> Response:
    """The mailboxes and the last messages, polled while a collection runs."""
    if not wants_fragment(request):
        return RedirectResponse("/messages", status_code=303)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, CONTENT, _context(request, account.id))


@router.post("/relever", response_class=HTMLResponse)
def collect_now(request: Request, account: CurrentAccount) -> Response:
    """« Relever maintenant »: every connected mailbox of the account; asking twice collects once."""
    service = _service(request)
    scheduler: Scheduler = request.app.state.scheduler
    name = _task_name(account.id)
    if service.configured and name not in scheduler.pending():
        scheduler.submit(name, lambda: _collect_quietly(service, account.id))
    if not is_htmx(request):
        return RedirectResponse("/messages", status_code=303)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request, CONTENT, _context(request, account.id, launched=service.configured)
    )


def _collect_quietly(service: MessagesService, account_id: int) -> None:
    for result in service.collect_account(account_id, Trigger.MANUAL):
        logger.info("collection %s: %s", result.sync_id, result.status)


@router.post("/gmail/connecter")
def connect(request: Request, account: CurrentAccount) -> Response:
    """Off to Google's consent page; the state of the request waits in a sealed cookie (15 minutes)."""
    service = _service(request)
    if not service.configured:
        return _page(request, account.id, status_code=400, error=NOT_CONFIGURED)
    pending = new_authorization(account.id)
    settings = request.app.state.settings
    response = RedirectResponse(
        authorization_url(
            service.settings,
            redirect_to=redirect_uri(settings.public_url),
            pending=pending,
        ),
        status_code=303,
    )
    response.set_cookie(
        STATE_COOKIE,
        seal_pending(service.cipher, pending),
        max_age=STATE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return response


@router.get(CALLBACK_PATH.removeprefix("/messages"), response_class=HTMLResponse)
def callback(
    request: Request,
    account: CurrentAccount,
    code: str = "",
    state: str = "",
    error: str = "",
) -> Response:
    """The return from Google: the state must be the one this browser sent, for this account."""
    service = _service(request)
    if not service.configured:
        return _failed(request, account.id, NOT_CONFIGURED)
    pending = open_pending(service.cipher, request.cookies.get(STATE_COOKIE, ""))
    if (
        pending is None
        or pending.account_id != account.id
        or not secrets.compare_digest(pending.state, state)
    ):
        return _failed(request, account.id, EXPIRED)
    if error:
        reason = REFUSED if error == "access_denied" else _google_refusal(error)
        return _failed(request, account.id, reason)
    settings = request.app.state.settings
    try:
        grant = service.oauth.exchange(
            code,
            verifier=pending.verifier,
            redirect_to=redirect_uri(settings.public_url),
        )
    except GmailError as refused:
        return _failed(request, account.id, refused.reason)
    mailbox_id, reconnected = service.connect(account.id, grant)
    scheduler: Scheduler = request.app.state.scheduler
    scheduler.submit(
        f"messages-boite-{mailbox_id}",
        lambda: _collect_mailbox_quietly(service, mailbox_id),
    )
    response = RedirectResponse(
        f"/messages?boite={'reconnectee' if reconnected else 'connectee'}",
        status_code=303,
    )
    response.delete_cookie(STATE_COOKIE, path=COOKIE_PATH)
    return response


def _google_refusal(error: str) -> str:
    code = error if _ERROR_CODE.match(error) else "inconnue"
    return f"Google a refusé l'autorisation (raison : {code})."


def _failed(request: Request, account_id: int, reason: str) -> HTMLResponse:
    response = _page(request, account_id, status_code=400, error=reason)
    response.delete_cookie(STATE_COOKIE, path=COOKIE_PATH)
    return response


def _collect_mailbox_quietly(service: MessagesService, mailbox_id: int) -> None:
    try:
        service.collect_mailbox(mailbox_id, Trigger.MANUAL)
    except (CollectBusyError, MailboxNotConnectedError) as skipped:
        logger.info(
            "first collection of mailbox %s skipped: %s",
            mailbox_id,
            type(skipped).__name__,
        )


@router.post("/boites/{mailbox_id}/deconnecter")
def disconnect(request: Request, account: CurrentAccount, mailbox_id: int) -> Response:
    service = _service(request)
    if not service.configured:
        return _page(request, account.id, status_code=400, error=NOT_CONFIGURED)
    try:
        warning = service.disconnect(account.id, mailbox_id)
    except MailboxNotFoundError:
        return _page(
            request, account.id, status_code=404, error="Cette boîte n'existe pas."
        )
    notice = "revocation" if warning else "deconnectee"
    return RedirectResponse(f"/messages?boite={notice}", status_code=303)
