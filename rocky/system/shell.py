"""Web shell: the navigation, the page helper shared by every module, and the cross-cutting screens (step F1):
🏠 Aujourd'hui, ⚙️ Système and the drawer 🐾, built from what each module registers here.

``system`` imports no business module (decision F1, Q13): a module registers its cards and its drawer at install time,
the shell orders them, chooses the one main action of the screen and renders them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount

# A counter beside an entry of the navigation (decision E4, Q5: what moved in 📬 Messages); 0 shows nothing.
type BadgeProvider = Callable[[Request, Account], int]

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
        "E1",
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
    """A gesture offered by a card: a link, or a form posted to ``url`` when ``post``."""

    label: str
    url: str
    post: bool = False


@dataclass(frozen=True)
class Card:
    """A block of 🏠 Aujourd'hui or a panel of ⚙️ Système.

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
    """What the drawer 🐾 shows on a screen (decision F1, Q12): what to do here, and the screen's shortcuts."""

    actions: tuple[Action, ...] = ()
    shortcuts: tuple[tuple[str, str], ...] = ()


# The cards a module gives for an account; none when it has nothing to say.
type CardsProvider = Callable[[Request, Account], Sequence[Card]]
type DrawerProvider = Callable[[Request, Account], Drawer]

# Decision F1, Q5: the order of the blocks of 🏠 Aujourd'hui, from the most pressing.
TODAY_ORDER = ("veille", "messages", "relances", "dossiers", "offres")
# Decision F1, Q11: the order of the panels of ⚙️ Système.
SYSTEM_ORDER = ("veille", "boites", "alertes", "planification")
POLL_EVERY = "15s"


def add_today_cards(app: FastAPI, key: str, provider: CardsProvider) -> None:
    """Register the block ``key`` of 🏠 Aujourd'hui (its place is fixed by ``TODAY_ORDER``)."""
    _add_cards(app, "today_cards", TODAY_ORDER, key, provider)


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


def main_action(cards: Sequence[Card]) -> int | None:
    """The card whose action is the main one of the screen (decision F1, Q5, Q11): the first problem with an action,
    else the first card with an action; None when no card has one."""
    with_action = [index for index, card in enumerate(cards) if card.action]
    problems = [index for index in with_action if cards[index].problem]
    return next(iter(problems or with_action), None)


router = APIRouter()

# The main action of an empty 🏠 Aujourd'hui (Q14: every state has one).
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


@router.get("/", response_class=HTMLResponse)
def today(request: Request, account: CurrentAccount) -> HTMLResponse:
    """🏠 Aujourd'hui (decision F1, Q5): what asks for attention now, the most pressing first."""
    return _cards_screen(
        request,
        account,
        key="today",
        name="today_cards",
        order=TODAY_ORDER,
        empty=BROWSE_OFFERS,
    )


@router.get("/tiroir", response_class=HTMLResponse)
def drawer(request: Request, account: CurrentAccount, ecran: str = "") -> HTMLResponse:
    """The drawer 🐾 of the screen ``ecran`` (a navigation key), loaded when it opens (decision F1, Q12)."""
    providers: dict[str, DrawerProvider] = getattr(request.app.state, "drawers", {})
    entry = ENTRIES.get(ecran)
    provider = providers.get(ecran) if entry is not None else None
    context = {
        "entry": entry,
        "drawer": provider(request, account) if provider is not None else Drawer(),
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


for _key in ("report", "system"):
    _empty_page(_key)
