"""Web shell: the navigation, the page helper shared by every module, and the cross-cutting screens (step F1):
⚙️ Système and the drawer 🐾, built from what each module registers here (🧭 Cockpit, step G3: ``cockpit.py``).

The shell imports no business module (decision F1, Q13): a module registers its cards and its drawer at install time,
the shell orders them, chooses the one main action of the screen and renders them. In ``system``, only the assembly
imports the modules: the application (``web.py``), the command line (``admin.py``) and the tables (``tables.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.errors import UserFacingError

# A counter beside an entry of the navigation (decision E4, Q5: what moved in 📬 Messages); 0 shows nothing.
type BadgeProvider = Callable[[Request, Account], int]

HTMX_SCRIPT = "htmx-2.0.11.min.js"
# Where the layout shows a business refusal answered to an HTMX fragment (step H1).
ERROR_AREA = "#erreur"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavEntry:
    key: str
    icon: str
    label: str
    path: str
    # On a phone, primary entries stay in the bottom bar; the others go under "Plus".
    primary: bool
    purpose: str


NAVIGATION = (
    # Decision G3 (Q8, Q25): the cockpit replaces « Aujourd'hui »; its key stays « today ».
    NavEntry(
        "today",
        "🧭",
        "Cockpit",
        "/",
        True,
        "Piloter ta recherche : où tu en es, ce qui a bougé, la prochaine candidature à faire.",
    ),
    NavEntry(
        "offers",
        "🔎",
        "Offres",
        "/offres",
        True,
        "Découvrir les offres et décider.",
    ),
    NavEntry(
        "applications",
        "📝",
        "Candidatures",
        "/candidatures",
        True,
        "Préparer, envoyer et suivre tes candidatures, étape par étape.",
    ),
    NavEntry(
        "messages",
        "📬",
        "Messages",
        "/messages",
        True,
        "Les retours des recruteurs et les alertes emploi, avec leurs preuves.",
    ),
    NavEntry(
        "report",
        "📈",
        "Bilan",
        "/bilan",
        False,
        "Apprendre de ta recherche : ce qui marche, ce qui bloque.",
    ),
    NavEntry(
        "profile",
        "👤",
        "Profil & kit",
        "/profil",
        False,
        "Ton CV maître, tes pistes, tes compétences, en français et en anglais.",
    ),
    NavEntry(
        "system",
        "⚙️",
        "Système",
        "/systeme",
        False,
        "Sources, veilles, Gmail, planification et diagnostics.",
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
    """Render ``name`` with what the shell layout needs (navigation, account, active entry, counters)."""
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
            # Called by the layout only: a fragment never computes the counters.
            "badges": lambda: badges(request, account),
            **(context or {}),
        },
        status_code=status_code,
    )


def content_disposition(kind: str, filename: str) -> str:
    """``Content-Disposition`` for any name (``inline`` or ``attachment``): an ASCII fallback and the exact name
    (RFC 6266); a raw name outside latin-1 cannot be a header (step H1)."""
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def entry_of(path: str) -> NavEntry:
    """The navigation entry a path belongs to; 🧭 Cockpit for any other."""
    return next(
        (
            entry
            for entry in NAVIGATION
            if entry.path != "/"
            and (path == entry.path or path.startswith(f"{entry.path}/"))
        ),
        ENTRIES["today"],
    )


def show_user_error(request: Request, error: Exception) -> Response:
    """A business refusal that no route caught (step H1): logged, then shown, never a 500.

    An HTMX fragment puts it in the error area of the page (``ERROR_AREA``), whatever the target of the request; any
    other request gets a whole page: 409 without HTMX, 200 for a boosted navigation (HTMX swaps no 4xx answer).
    """
    assert isinstance(error, UserFacingError)  # noqa: S101  (handler registered for this type)
    logger.warning(
        "%s on %s %s: %s",
        type(error).__name__,
        request.method,
        request.url.path,
        error,
    )
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        response = templates.TemplateResponse(
            request, "user_error.html", {"lines": error.lines}
        )
        response.headers["HX-Retarget"] = ERROR_AREA
        response.headers["HX-Reswap"] = "innerHTML"
        return response
    status_code = 200 if is_htmx(request) else 409
    if getattr(request.state, "account", None) is None:
        # No layout without an account: the reasons alone.
        return PlainTextResponse(str(error), status_code=status_code)
    entry = entry_of(request.url.path)
    return page(
        request,
        "user_error_page.html",
        active=entry.key,
        status_code=status_code,
        context={"lines": error.lines, "entry": entry},
    )


def add_badge(app: FastAPI, key: str, provider: BadgeProvider) -> None:
    """Register the counter of the navigation entry ``key``; the layout shows it when it is not 0."""
    if key not in ENTRIES:
        raise KeyError(key)
    providers: dict[str, BadgeProvider] = getattr(app.state, "badges", {})
    app.state.badges = {**providers, key: provider}


def badges(request: Request, account: Account | None) -> dict[str, int]:
    if account is None:
        return {}
    providers: dict[str, BadgeProvider] = getattr(request.app.state, "badges", {})
    return {
        key: count
        for key, provider in providers.items()
        if (count := provider(request, account))
    }


# The cross-cutting screens (step F1)


@dataclass(frozen=True)
class Action:
    """A gesture offered by a card: a link, or a form posted to ``url`` when ``post``; ``panel``: a fragment loaded in
    place, below the hero of the cockpit (decision G3, Q15)."""

    label: str
    url: str
    post: bool = False
    panel: bool = False


@dataclass(frozen=True)
class Card:
    """A panel of ⚙️ Système, or a problem shown above the hero of 🧭 Cockpit.

    ``problem``: something is wrong (a failed watch, a mailbox to reconnect); the first problem takes the main action.
    ``details``: label and value pairs. ``polling``: the screen reads its cards again every 15 s (a watch running).
    """

    title: str
    lines: tuple[str, ...] = ()
    details: tuple[tuple[str, str], ...] = ()
    action: Action | None = None
    problem: bool = False
    polling: bool = False


@dataclass(frozen=True)
class Drawer:
    """What the drawer 🐾 shows on a screen (decision F1, Q12): what to do here (at most ``DRAWER_ACTIONS``), and the
    screen's shortcuts, each its keys (HTML, ``<kbd>``) and what they do."""

    actions: tuple[Action, ...] = ()
    shortcuts: tuple[tuple[Markup, Markup | str], ...] = ()


# The cards a module gives for an account; none when it has nothing to say.
type CardsProvider = Callable[[Request, Account], Sequence[Card]]
type DrawerProvider = Callable[[Request, Account], Drawer]

# Decision F1, Q11: the order of the panels of ⚙️ Système (G4, Q19: the cost of the calls to the models last).
SYSTEM_ORDER = ("veille", "boites", "alertes", "planification", "couts")
POLL_EVERY = "15s"
DRAWER_ACTIONS = 3


def add_system_cards(app: FastAPI, key: str, provider: CardsProvider) -> None:
    """Register the panel ``key`` of ⚙️ Système (its place is fixed by ``SYSTEM_ORDER``)."""
    _add_cards(app, "system_cards", SYSTEM_ORDER, key, provider)


def _add_cards(
    app: FastAPI,
    name: str,
    order: tuple[str, ...],
    key: str,
    provider: CardsProvider,
) -> None:
    if key not in order:
        raise KeyError(key)
    providers: dict[str, CardsProvider] = getattr(app.state, name, {})
    setattr(app.state, name, {**providers, key: provider})


def add_drawer(app: FastAPI, key: str, provider: DrawerProvider) -> None:
    """Register what the drawer shows on the screen of the navigation entry ``key``."""
    if key not in ENTRIES:
        raise KeyError(key)
    providers: dict[str, DrawerProvider] = getattr(app.state, "drawers", {})
    app.state.drawers = {**providers, key: provider}


def cards_of(
    request: Request, account: Account, name: str, order: tuple[str, ...]
) -> list[Card]:
    providers: dict[str, CardsProvider] = getattr(request.app.state, name, {})
    return [
        card
        for key in order
        if key in providers
        for card in providers[key](request, account)
    ]


# The screens made of cards: their drawer gives the cards' gestures, the main one first.
CARD_SCREENS = {"system": ("system_cards", SYSTEM_ORDER)}


def card_actions(cards: Sequence[Card]) -> tuple[Action, ...]:
    """The gestures of ``cards``, the main one first, each once."""
    main = main_action(cards)
    ordered = ([cards[main]] if main is not None else []) + list(cards)
    actions: list[Action] = []
    for card in ordered:
        if card.action is not None and card.action not in actions:
            actions.append(card.action)
    return tuple(actions)


def main_action(cards: Sequence[Card]) -> int | None:
    """The card whose action is the main one of the screen (decision F1, Q5, Q11): the first problem with an action,
    else the first card with an action; None when no card has one."""
    with_action = [index for index, card in enumerate(cards) if card.action]
    problems = [index for index in with_action if cards[index].problem]
    return next(iter(problems or with_action), None)


router = APIRouter()

# The main action of a screen whose cards offer none (Q14: every state has one).
BROWSE_OFFERS = Action("Parcourir les offres", "/offres?vue=liste")


def _cards_screen(
    request: Request,
    account: Account,
    *,
    key: str,
    name: str,
    order: tuple[str, ...],
    empty: Action | None,
) -> HTMLResponse:
    cards = cards_of(request, account, name, order)
    context = {
        "entry": ENTRIES[key],
        "cards": cards,
        "main": main_action(cards),
        "empty": empty,
        "polling": any(card.polling for card in cards),
        "poll_every": POLL_EVERY,
    }
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(request, "cards.html", context)
    return page(request, "cards_page.html", active=key, context=context)


@router.get("/systeme", response_class=HTMLResponse)
def system(request: Request, account: CurrentAccount) -> HTMLResponse:
    """⚙️ Système (decision F1, Q11): the watch source by source, the mailboxes, the alerts, the planner; the first
    problem takes the main action."""
    return _cards_screen(
        request,
        account,
        key="system",
        name="system_cards",
        order=SYSTEM_ORDER,
        # A watch running and nothing else to do: what it finds is in the offers.
        empty=BROWSE_OFFERS,
    )


@router.get("/tiroir", response_class=HTMLResponse)
def drawer(request: Request, account: CurrentAccount, ecran: str = "") -> HTMLResponse:
    """The drawer 🐾 of the screen ``ecran`` (a navigation key), loaded when it opens (decision F1, Q12)."""
    providers: dict[str, DrawerProvider] = getattr(request.app.state, "drawers", {})
    entry = ENTRIES.get(ecran)
    provider = providers.get(ecran) if entry is not None else None
    if provider is not None:
        found = provider(request, account)
    elif ecran in CARD_SCREENS:
        found = Drawer(
            actions=card_actions(cards_of(request, account, *CARD_SCREENS[ecran]))
        )
    else:
        found = Drawer()
    context = {
        "entry": entry,
        "drawer": Drawer(found.actions[:DRAWER_ACTIONS], found.shortcuts),
    }
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(request, "drawer.html", context)
    return page(
        request,
        "drawer_page.html",
        active=entry.key if entry is not None else "today",
        context=context,
    )
