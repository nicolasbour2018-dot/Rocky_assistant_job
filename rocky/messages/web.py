"""📬 Messages (steps E1, E2, E4): the Gmail mailboxes of the account, « Relever maintenant », the last messages with
their classification and its proof (« Messages triés », E2 Q14), grouped by application (E4 Q8); « Ce qui a bougé »
and its gestures (E4 Q5), « Juste », « Corriger » and « Créer la candidature » (E4 Q4, Q6, Q7).

A collection runs in the planner's thread, never in a request: the screen follows it by polling a fragment. Only
the return from Google (the exchange of its code) calls Google inside a request.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rocky.candidatures.model import InvalidChangeError
from rocky.messages import cockpit as messages_cockpit
from rocky.messages.alerts.model import (
    ALERTS_PER_DAY,
    LINK_OUTCOME_LABELS,
    PLATFORM_LABELS,
    READING_LABELS,
    LinkOutcome,
    PlatformAlerts,
    ReadingStatus,
)
from rocky.messages.classification.model import (
    CATEGORY_LABELS,
    EMPLOYER_CATEGORIES,
    LEVEL_LABELS,
    TIER_LABELS,
    VIEW_LABELS,
    Category,
    Level,
    View,
)
from rocky.messages.decisions.model import InvalidGestureError, Outcome
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
from rocky.messages.service import (
    NOT_CONFIGURED,
    MailboxView,
    MessagesService,
    messages_service,
)
from rocky.messages.usecases import (
    CollectBusyError,
    MailboxNotConnectedError,
    MailboxNotFoundError,
)
from rocky.offres.decisions import Author
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import InvalidLinkError
from rocky.profil.web import profile_of
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.clock import paris_time
from rocky.system.scheduler import Scheduler
from rocky.system.shell import (
    Action,
    Card,
    add_badge,
    add_system_cards,
    is_htmx,
    page,
    refusal,
    wants_fragment,
)

logger = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"
PAGE = "messages/page.html"
CONTENT = "messages/content.html"
MAILBOXES = "messages/mailboxes.html"
CORRECT_PANEL = "messages/correct_panel.html"
CREATE_PANEL = "messages/create_panel.html"
APPLICATION_MESSAGES = "messages/application_messages.html"
_PANEL_ID = re.compile(r"^panneau-(?:mouvement-)?\d{1,18}$")
STATE_COOKIE = "rocky_gmail_oauth"
COOKIE_PATH = "/messages/gmail"

# What a redirection to the page says (``?boite=…``): fixed texts, never a value from the address.
NOTICES = {
    "connectee": "Boîte connectée : son premier relevé est lancé.",
    "reconnectee": "Boîte reconnectée : le relevé reprend.",
    "deconnectee": "Boîte déconnectée : Rocky n'y a plus accès, ses messages restent.",
    "revocation": (
        "Boîte déconnectée, mais Google n'a pas pu être prévenu : retire l'accès de Rocky dans ton compte Google "
        "(Sécurité, « Applications tierces »)."
    ),
}
EXPIRED = (
    "La demande d'autorisation a expiré ou ne vient pas de cette page : "
    "recommence « Connecter une boîte Gmail »."
)
REFUSED = "Tu as refusé l'accès chez Google : aucune boîte n'a été connectée."
_ERROR_CODE = re.compile(r"^[a-z_]{1,40}$")

router = APIRouter(prefix="/messages")


def install(app: FastAPI) -> None:
    settings = app.state.settings

    def collected(account_id: int, message_ids: Sequence[int]) -> None:
        # Read again at each collection, never kept here: a test or E4 may replace it on app.state.
        app.state.messages_collected(account_id, message_ids)

    def new_http() -> PublicHttp:
        # Read again at each pass, never kept here: a test replaces the client of the import on app.state.
        http: PublicHttp = app.state.import_http()
        return http

    service = messages_service(
        app.state.engine,
        settings,
        clock=app.state.auth.clock,
        classify=True,
        # E3: the postings of the alerts' links, on the client of the import.
        new_http=new_http,
        on_collected=collected,
    )
    app.state.messages = service
    # E2: what follows a collection is the classification of the account's messages without a decision.
    app.state.messages_collected = service.classify_after_collection
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        mailbox_status_labels=MAILBOX_STATUS_LABELS,
        sync_status_labels=SYNC_STATUS_LABELS,
        query_labels=QUERY_LABELS,
        category_labels=CATEGORY_LABELS,
        employer_categories=EMPLOYER_CATEGORIES,
        level_labels=LEVEL_LABELS,
        tier_labels=TIER_LABELS,
        view_labels=VIEW_LABELS,
        platform_labels=PLATFORM_LABELS,
        reading_labels=READING_LABELS,
        link_outcome_labels=LINK_OUTCOME_LABELS,
        ReadingStatus=ReadingStatus,
        LinkOutcome=LinkOutcome,
        alerts_per_day=ALERTS_PER_DAY,
    )
    # ``stage_labels`` is set once, by 📝 Candidatures (decision G6, Q5).
    # E4 (Q5): the lines of « Ce qui a bougé » beside 📬 in the navigation.
    add_badge(app, "messages", _pending_count)
    # Decisions F1 (Q7) and G3 (Q16): lines of the cockpit's feed; the gestures stay here.
    messages_cockpit.install(app)
    # Decision F1, Q11: the mailboxes and the alerts in ⚙️ Système.
    add_system_cards(app, "boites", _mailbox_cards)
    add_system_cards(app, "alertes", _alert_cards)
    app.include_router(router)


# ⚙️ Système (decision F1, Q11): the mailboxes and what the alerts gave over the last days.
ALERT_DAYS = 7
CONNECT = Action(
    "Connecter une boîte Gmail", "/messages/gmail/connecter", post=True, leaves=True
)
RECONNECT = Action(
    "Reconnecter la boîte", "/messages/gmail/connecter", post=True, leaves=True
)
COLLECT_FROM_SYSTEM = Action(
    "Relever les messages", "/messages/relever?retour=systeme", post=True
)


def _mailbox_cards(request: Request, account: Account) -> list[Card]:
    service = _service(request)
    if not service.configured:
        return [
            Card(
                "📬 Boîtes Gmail", ("Gmail n'est pas encore disponible sur ce Rocky.",)
            )
        ]
    return [mailbox_card(service.mailbox_views(account.id))]


def mailbox_card(views: Sequence[MailboxView]) -> Card:
    """Each mailbox with its last collection; a mailbox to reconnect, or a failed collection, is a problem."""
    shown = [
        view for view in views if view.mailbox.status is not MailboxStatus.DISCONNECTED
    ]
    if not shown:
        return Card(
            "📬 Boîtes Gmail",
            (
                "Aucune boîte connectée : Rocky ne lit ni les réponses des recruteurs ni tes alertes.",
            ),
            action=CONNECT,
        )
    lost = any(view.mailbox.status is MailboxStatus.ACCESS_LOST for view in shown)
    failed = any(
        view.last is not None and view.last.status is SyncStatus.FAILED
        for view in shown
    )
    running = any(
        view.last is not None and view.last.status is SyncStatus.RUNNING
        for view in shown
    )
    return Card(
        "📬 Boîtes Gmail",
        ("Relevé automatique toutes les heures.",),
        tuple((view.mailbox.address, mailbox_line(view)) for view in shown),
        action=None if running else RECONNECT if lost else COLLECT_FROM_SYSTEM,
        problem=lost or failed,
        polling=running,
    )


def mailbox_line(view: MailboxView) -> str:
    parts = [MAILBOX_STATUS_LABELS[view.mailbox.status]]
    last = view.last
    if last is None:
        parts.append("jamais relevée")
    else:
        parts.append(
            f"dernier relevé le {paris_time(last.started_at)} : {SYNC_STATUS_LABELS[last.status]}"
        )
        if last.status is not SyncStatus.RUNNING:
            new = last.counts.new
            parts.append(
                f"{new} nouveau{'x' if new > 1 else ''} message{'s' if new > 1 else ''}"
            )
        if last.reason:
            parts.append(last.reason)
    return " · ".join(parts)


def _alert_cards(request: Request, account: Account) -> list[Card]:
    service = _service(request)
    if not service.configured:
        return []
    return [alerts_card(service.alerts_by_platform(account.id, ALERT_DAYS))]


def alerts_card(found: Sequence[PlatformAlerts]) -> Card:
    """What the alerts gave, by platform (plan §8, E3 → F1), refusals of the postings included."""
    title = f"🔔 Alertes emploi · {ALERT_DAYS} derniers jours"
    if not found:
        return Card(title, ("Aucune alerte reçue ces derniers jours.",))
    return Card(
        title,
        (f"Au plus {ALERTS_PER_DAY} alertes lues par jour.",),
        tuple(
            (
                "Formats non lus"
                if alerts.platform is None
                else PLATFORM_LABELS[alerts.platform],
                platform_line(alerts),
            )
            for alerts in found
        ),
    )


def platform_line(alerts: PlatformAlerts) -> str:
    def counted(count: int, word: str) -> str:
        return f"{count} {word}{'s' if count > 1 else ''}"

    if alerts.platform is None:
        return f"{counted(alerts.unread, 'alerte')} sans lecteur"
    parts = [f"{counted(alerts.read, 'alerte')} lue{'s' if alerts.read > 1 else ''}"]
    if alerts.unread:
        parts.append(f"{alerts.unread} non lue{'s' if alerts.unread > 1 else ''}")
    if alerts.offers:
        parts.append(
            f"{counted(alerts.offers, 'offre')}, dont {alerts.created} nouvelle{'s' if alerts.created > 1 else ''}"
        )
    if alerts.refused:
        parts.append(
            f"{counted(alerts.refused, 'fiche')} refusée{'s' if alerts.refused > 1 else ''}"
        )
    return " · ".join(parts)


def _pending_count(request: Request, account: Account) -> int:
    return _service(request).pending_count(account.id)


def _service(request: Request) -> MessagesService:
    service: MessagesService = request.app.state.messages
    return service


def _task_name(account_id: int) -> str:
    return f"messages-compte-{account_id}"


def _view(vue: str) -> View:
    return View(vue) if vue in set(View) else View.TO_LOOK_AT


def _context(
    request: Request,
    account_id: int,
    *,
    launched: bool = False,
    view: View = View.TO_LOOK_AT,
    **extra: Any,
) -> dict[str, Any]:
    """``launched``: a collection was just asked. The planner may already have taken it from its queue without having
    written its row yet: the screen polls all the same, or it would show the previous collection."""
    service = _service(request)
    state = service.state(account_id, view)
    scheduler: Scheduler = request.app.state.scheduler
    return {
        "configured": service.configured,
        "not_configured": NOT_CONFIGURED,
        "state": state,
        "running": launched
        or state.running
        or _task_name(account_id) in scheduler.pending(),
        "MailboxStatus": MailboxStatus,
        "SyncStatus": SyncStatus,
        "View": View,
        "Level": Level,
        "Author": Author,
        "Outcome": Outcome,
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
def show(
    request: Request, account: CurrentAccount, boite: str = "", vue: str = ""
) -> HTMLResponse:
    # After a connection, its first collection was just asked (``callback``).
    launched = boite in ("connectee", "reconnectee")
    return _page(
        request,
        account.id,
        notice=NOTICES.get(boite),
        launched=launched,
        view=_view(vue),
    )


@router.get("/contenu", response_class=HTMLResponse)
def content_fragment(
    request: Request, account: CurrentAccount, vue: str = ""
) -> Response:
    """The mailboxes and the last messages, polled while a collection runs."""
    if not wants_fragment(request):
        return RedirectResponse("/messages", status_code=303)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request, CONTENT, _context(request, account.id, view=_view(vue), fragment=True)
    )


@router.get("/boites", response_class=HTMLResponse)
def mailboxes_fragment(request: Request, account: CurrentAccount) -> Response:
    """The mailboxes, read again while a collection runs; at its end, the whole content is read once
    (decision G6, A5)."""
    if not wants_fragment(request):
        return RedirectResponse("/messages", status_code=303)
    context = _context(request, account.id, fragment=True)
    templates: Jinja2Templates = request.app.state.templates
    response = templates.TemplateResponse(request, MAILBOXES, context)
    if not context["running"]:
        response.headers["HX-Trigger"] = "messages-changed"
    return response


@router.post("/relever", response_class=HTMLResponse)
def collect_now(
    request: Request, account: CurrentAccount, retour: str = ""
) -> Response:
    """« Relever maintenant »: every connected mailbox of the account; asking twice collects once."""
    service = _service(request)
    scheduler: Scheduler = request.app.state.scheduler
    name = _task_name(account.id)
    if service.configured and name not in scheduler.pending():
        scheduler.submit(name, lambda: _collect_quietly(service, account.id))
    if not wants_fragment(request):
        # ⚙️ Système asks with a fixed value, never a URL; its boosted form wants the next page (decision G6, A3).
        back = "/systeme" if retour == "systeme" else "/messages"
        return RedirectResponse(back, status_code=303)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        CONTENT,
        _context(request, account.id, launched=service.configured, fragment=True),
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


# Decisions on the messages (E4). Every gesture answers with the content of the page (its notice or error on top); a
# request without HTMX is sent back to the page.

GESTURE_NOTICES = {
    "vu": "C'est noté.",
    "appliquer": "Étape de la candidature changée.",
    "ignorer": "Proposition ignorée : la candidature garde son étape.",
    "annuler": "Changement annulé : la candidature a retrouvé son étape.",
}


@router.post("/mouvements/{transition_id}/{gesture}", response_class=HTMLResponse)
def settle(
    request: Request, account: CurrentAccount, transition_id: int, gesture: str
) -> Response:
    """« Vu », « Appliquer », « Ignorer », « Annuler » on a line of « Ce qui a bougé » (Q5)."""
    service = _service(request)
    actions = {
        "vu": service.mark_seen,
        "appliquer": service.apply_proposal,
        "ignorer": service.dismiss,
        "annuler": service.cancel_transition,
    }
    action = actions.get(gesture)
    if action is None:
        return _content(request, account.id, status_code=404, error="Geste inconnu.")
    try:
        action(account.id, transition_id)
    except (InvalidGestureError, InvalidChangeError) as refused:
        return _content(request, account.id, status_code=400, error=str(refused))
    return _content(request, account.id, notice=GESTURE_NOTICES[gesture])


@router.get("/{message_id}/corriger", response_class=HTMLResponse)
def correct_panel(
    request: Request, account: CurrentAccount, message_id: int
) -> Response:
    """The panel « Corriger » of a message (Q6, Q7)."""
    return _panel(request, account.id, message_id, CORRECT_PANEL)


@router.get("/{message_id}/creer", response_class=HTMLResponse)
def create_panel(
    request: Request, account: CurrentAccount, message_id: int
) -> Response:
    """The panel « Créer la candidature » of a message (Q4)."""
    return _panel(request, account.id, message_id, CREATE_PANEL)


def _panel(request: Request, account_id: int, message_id: int, name: str) -> Response:
    if not wants_fragment(request):
        return RedirectResponse("/messages", status_code=303)
    try:
        view = _service(request).correction(account_id, message_id)
    except LookupError:
        return HTMLResponse(
            "<p class='alert alert-error'>Ce message n'existe pas.</p>", 404
        )
    target = request.headers.get("HX-Target", "")
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        name,
        {
            "view": view,
            "categories": list(Category),
            "panel": target if _PANEL_ID.match(target) else f"panneau-{message_id}",
        },
    )


@router.post("/{message_id}/corriger", response_class=HTMLResponse)
def correct(
    request: Request,
    account: CurrentAccount,
    message_id: int,
    categorie: Annotated[str, Form()] = "",
    candidature: Annotated[str, Form()] = "",
    toujours: Annotated[str, Form()] = "",
    domaine: Annotated[str, Form()] = "",
) -> Response:
    """« Enregistrer la correction » (Q3, Q6, Q7)."""
    if categorie not in set(Category):
        return _content(
            request, account.id, status_code=400, error="Catégorie inconnue."
        )
    application_id = (
        int(candidature) if candidature.isascii() and candidature.isdigit() else None
    )
    try:
        result = _service(request).correct(
            account.id,
            message_id,
            category=Category(categorie),
            application_id=application_id,
            remember_sender=bool(toujours),
            remember_domain=bool(domaine),
        )
    except InvalidGestureError as refused:
        return _content(request, account.id, status_code=400, error=str(refused))
    except LookupError:
        return _content(
            request, account.id, status_code=404, error="Ce message n'existe pas."
        )
    said = ["Correction enregistrée."]
    if result.kept:
        said.append(
            "La candidature a changé depuis ce message : son étape reste, change-la depuis son dossier si besoin."
        )
    if result.proposal_id is not None:
        said.append(
            "Le changement d'étape qui en découle est proposé dans « Ce qui a bougé »."
        )
    if result.rule_address:
        said.append(
            f"Règle ajoutée : {result.rule_address} → {CATEGORY_LABELS[Category(categorie)]}."
        )
    if result.domain:
        said.append(f"Domaine de l'employeur retenu : {result.domain}.")
    return _content(request, account.id, notice=" ".join(said))


@router.post("/{message_id}/juste", response_class=HTMLResponse)
def confirm(request: Request, account: CurrentAccount, message_id: int) -> Response:
    """« Juste »: the user confirms Rocky's decision (Q6)."""
    try:
        _service(request).confirm(account.id, message_id)
    except InvalidGestureError as refused:
        return _content(request, account.id, status_code=400, error=str(refused))
    except LookupError:
        return _content(
            request, account.id, status_code=404, error="Ce message n'existe pas."
        )
    return _content(request, account.id, notice="Merci : classement confirmé.")


@router.post("/{message_id}/creer", response_class=HTMLResponse)
def create(
    request: Request,
    account: CurrentAccount,
    message_id: int,
    employeur: Annotated[str, Form()] = "",
    intitule: Annotated[str, Form()] = "",
    lien: Annotated[str, Form()] = "",
) -> Response:
    """« Créer la candidature » (Q4): the offer and the application at « Envoyée », the message attached."""
    try:
        application_id = _service(request).create_application(
            account.id,
            message_id,
            company=employeur,
            title=intitule,
            link=lien,
            profile=profile_of(request, account),
        )
    except (InvalidGestureError, InvalidLinkError, InvalidChangeError) as refused:
        return _content(request, account.id, status_code=400, error=str(refused))
    except LookupError:
        return _content(
            request, account.id, status_code=404, error="Ce message n'existe pas."
        )
    return _content(
        request,
        account.id,
        notice=f"Candidature chez {' '.join(employeur.split())} créée, à l'étape « Envoyée ».",
        notice_link=(f"/candidatures/{application_id}", "Ouvrir le dossier"),
    )


@router.post("/{message_id}/creer-en-un-clic", response_class=HTMLResponse)
def create_in_one_click(
    request: Request, account: CurrentAccount, message_id: int
) -> Response:
    """« Créer la candidature » on the line of a message (Q13): employer and title read in it, the link is the
    message's. When one cannot be read, the form opens in the line's panel, prefilled."""
    service = _service(request)
    try:
        created = service.create_in_one_click(
            account.id, message_id, profile=profile_of(request, account)
        )
    except (InvalidGestureError, InvalidChangeError) as refused:
        return _content(request, account.id, status_code=400, error=str(refused))
    except LookupError:
        return _content(
            request, account.id, status_code=404, error="Ce message n'existe pas."
        )
    if created is None:
        if not is_htmx(request):
            return RedirectResponse("/messages", status_code=303)
        templates: Jinja2Templates = request.app.state.templates
        response = templates.TemplateResponse(
            request,
            CREATE_PANEL,
            {
                "view": service.correction(account.id, message_id),
                "unread": True,
            },
        )
        response.headers["HX-Retarget"] = f"#panneau-{message_id}"
        response.headers["HX-Reswap"] = "innerHTML"
        return response
    application_id, company, title = created
    return _content(
        request,
        account.id,
        notice=f"Candidature « {title} » chez {company} créée, à l'étape « Envoyée ».",
        notice_link=(f"/candidatures/{application_id}", "Ouvrir le dossier"),
    )


@router.post("/regles/{rule_id}/retirer", response_class=HTMLResponse)
def remove_rule(request: Request, account: CurrentAccount, rule_id: int) -> Response:
    """Retirer a rule of the account (Q7)."""
    try:
        _service(request).remove_rule(account.id, rule_id)
    except InvalidGestureError as refused:
        return _content(request, account.id, status_code=400, error=str(refused))
    return _content(request, account.id, notice="Règle retirée.")


@router.get("/candidature/{application_id}", response_class=HTMLResponse)
def application_messages(
    request: Request, account: CurrentAccount, application_id: int
) -> Response:
    """The block « Messages » of a dossier (Q8), loaded by its page."""
    if not wants_fragment(request):
        return RedirectResponse(f"/candidatures/{application_id}", status_code=303)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        APPLICATION_MESSAGES,
        {
            "messages": _service(request).application_messages(
                account.id, application_id
            )
        },
    )


def _content(
    request: Request, account_id: int, *, status_code: int = 200, **extra: Any
) -> Response:
    if not is_htmx(request):
        if status_code == 200:
            return RedirectResponse("/messages", status_code=303)
        return _page(request, account_id, status_code=status_code, **extra)
    if status_code >= 400:
        # The open panel stays as it is; the refusal shows in the error area (decision G6, A4).
        return refusal(request, extra["error"], status_code=status_code)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        CONTENT,
        _context(
            request, account_id, fragment=True, view=_current_view(request), **extra
        ),
        status_code=status_code,
    )


def _current_view(request: Request) -> View:
    """The view the page shows (HTMX names its address): a gesture keeps it."""
    query = urlsplit(request.headers.get("HX-Current-URL", "")).query
    return _view(parse_qs(query).get("vue", [""])[0])
