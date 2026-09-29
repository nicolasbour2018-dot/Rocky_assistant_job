"""Web shell: the navigation, the page helper shared by every module, the pages not built yet."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount

# A module's notice above every page (the late watch of C6): its HTML, or None when there is nothing to say.
type NoticeProvider = Callable[[Request, Account], Markup | None]

HTMX_SCRIPT = "htmx-2.0.11.min.js"


@dataclass(frozen=True)
class NavEntry:
    key: str
    icon: str
    label: str
    path: str
    # On a phone, primary entries stay in the bottom bar; the others go under "Plus".
    primary: bool
    purpose: str
    arrives_in: str


NAVIGATION = (
    NavEntry(
        "today",
        "🏠",
        "Aujourd'hui",
        "/",
        True,
        "Ce qui demande ton attention maintenant : offres à examiner, dossiers à finir, "
        "relances dues, réponses à vérifier.",
        "F1",
    ),
    NavEntry(
        "offers",
        "🔎",
        "Offres",
        "/offres",
        True,
        "Découvrir les offres et décider.",
        "C7",
    ),
    NavEntry(
        "applications",
        "📝",
        "Candidatures",
        "/candidatures",
        True,
        "Préparer, envoyer et suivre tes candidatures, étape par étape.",
        "D6",
    ),
    NavEntry(
        "messages",
        "📬",
        "Messages",
        "/messages",
        True,
        "Les retours des recruteurs et les alertes emploi, avec leurs preuves.",
        "E4",
    ),
    NavEntry(
        "report",
        "📈",
        "Bilan",
        "/bilan",
        False,
        "Apprendre de ta recherche : ce qui marche, ce qui bloque.",
        "F1",
    ),
    NavEntry(
        "profile",
        "👤",
        "Profil & kit",
        "/profil",
        False,
        "Ton CV maître, tes pistes, tes compétences, en français et en anglais.",
        "B5",
    ),
    NavEntry(
        "system",
        "⚙️",
        "Système",
        "/systeme",
        False,
        "Sources, veilles, Gmail, planification et diagnostics.",
        "F1",
    ),
)
ENTRIES = {entry.key: entry for entry in NAVIGATION}


def is_htmx(request: Request) -> bool:
    """A request made by HTMX (it expects a fragment, not a whole page)."""
    return request.headers.get("HX-Request") == "true"


def wants_fragment(request: Request) -> bool:
    """An explicit HTMX request; a boosted navigation (``HX-Boosted``, the layout's ``hx-boost``) wants a whole page."""
    return is_htmx(request) and request.headers.get("HX-Boosted") != "true"


def page(
    request: Request,
    name: str,
    *,
    active: str,
    status_code: int = 200,
    context: Mapping[str, object] | None = None,
) -> HTMLResponse:
    """Render ``name`` with what the shell layout needs (navigation, account, active entry, notices)."""
    templates: Jinja2Templates = request.app.state.templates
    account: Account | None = request.state.account
    return templates.TemplateResponse(
        request,
        name,
        {
            "navigation": NAVIGATION,
            "active": active,
            "account": account,
            "htmx_script": HTMX_SCRIPT,
            # Called by the layout only: a fragment never computes the notices.
            "notices": lambda: notices(request, account),
            **(context or {}),
        },
        status_code=status_code,
    )


def add_notice(app: FastAPI, provider: NoticeProvider) -> None:
    """Register a module's notice; the layout shows every notice that has something to say."""
    providers: list[NoticeProvider] = getattr(app.state, "notices", [])
    app.state.notices = [*providers, provider]


def notices(request: Request, account: Account | None) -> list[Markup]:
    if account is None:
        return []
    providers: list[NoticeProvider] = getattr(request.app.state, "notices", [])
    return [notice for provider in providers if (notice := provider(request, account))]


router = APIRouter()


def _empty_page(key: str) -> None:
    entry = ENTRIES[key]

    def show(request: Request, account: CurrentAccount) -> HTMLResponse:
        return page(request, "empty.html", active=entry.key, context={"entry": entry})

    router.add_api_route(
        entry.path,
        show,
        methods=["GET"],
        response_class=HTMLResponse,
        name=f"empty_{entry.key}",
    )


for _key in ("today", "applications", "messages", "report", "system"):
    _empty_page(_key)
