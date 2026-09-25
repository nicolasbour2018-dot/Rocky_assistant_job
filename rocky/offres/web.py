"""Offers screen (step B4 prototype, kept as the start of C7): triage mode, compact list, side sheet, "Pourquoi ?".

The server renders every state as HTML; HTMX swaps the fragments. Requests without HTMX get whole pages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rocky.offres.decisions import (
    DECISION_KEYS,
    DECISION_LABELS,
    REASON_QUESTIONS,
    REASONS,
    DecisionValue,
    InvalidDecisionError,
    make_decision,
    reason_label,
)
from rocky.offres.imports import web as imports_web
from rocky.offres.prototype import (
    VERDICT_SIGNS,
    Catalog,
    DecisionBook,
    Offer,
    load_catalog,
)
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.shell import is_htmx, page

TRIAGE = "tri"
LIST = "liste"
SHEET = "fiche"
# Decision filter of the list, as written in the URL.
DECISION_FILTERS: dict[str, DecisionValue | None] = {
    "a_examiner": None,
    "interesse": DecisionValue.INTERESTED,
    "ecarte": DecisionValue.REJECTED,
    "plus_tard": DecisionValue.LATER,
    "toutes": None,
}
OFFERS_CHANGED = "offers-changed"

router = APIRouter(prefix="/offres")


def install(app: FastAPI) -> None:
    app.state.decision_book = DecisionBook()
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        decision_labels=DECISION_LABELS,
        decision_keys=DECISION_KEYS,
        verdict_signs=VERDICT_SIGNS,
        reason_label=reason_label,
    )
    templates.env.filters["age"] = age
    imports_web.install(app)
    app.include_router(router)


def age(day: date | None) -> str:
    if day is None:
        return "date inconnue"
    days = (datetime.now(UTC).date() - day).days
    if days <= 0:
        return "aujourd'hui"
    if days == 1:
        return "hier"
    if days < 60:
        return f"il y a {days} j"
    return f"il y a {days // 30} mois"


@dataclass(frozen=True)
class ListFilters:
    track: str = ""
    decision: str = "a_examiner"
    below_threshold: bool = False
    incomplete: bool = False

    def query(self) -> str:
        values = {"piste": self.track, "decision": self.decision}
        if self.below_threshold:
            values["sous_seuil"] = "1"
        if self.incomplete:
            values["incompletes"] = "1"
        return urlencode({key: value for key, value in values.items() if value})


def _filters(
    piste: str | None,
    decision: str | None,
    sous_seuil: str | None,
    incompletes: str | None,
) -> ListFilters:
    return ListFilters(
        track=piste or "",
        decision=decision if decision in DECISION_FILTERS else "a_examiner",
        below_threshold=bool(sous_seuil),
        incomplete=bool(incompletes),
    )


class Screen:
    """What one account sees: the catalog and its decisions."""

    def __init__(self, request: Request, account: Account) -> None:
        self.request = request
        self.account = account
        self.catalog: Catalog = load_catalog()
        self.book: DecisionBook = request.app.state.decision_book
        self.decisions = self.book.decisions(account.id)

    @property
    def queue(self) -> list[Offer]:
        return self.catalog.queue(set(self.decisions))

    def counts(self) -> dict[str, int]:
        undecided_below = [
            o
            for o in self.catalog.offers
            if self.catalog.below_threshold(o) and o.id not in self.decisions
        ]
        return {"to_review": len(self.queue), "below": len(undecided_below)}

    def listed(self, filters: ListFilters) -> list[Offer]:
        wanted = DECISION_FILTERS[filters.decision]
        offers = []
        for offer in self.catalog.offers:
            if self.catalog.below_threshold(offer) != filters.below_threshold:
                continue
            if filters.track and filters.track not in offer.tracks:
                continue
            if filters.incomplete and offer.description_is_full:
                continue
            decision = self.decisions.get(offer.id)
            if filters.decision == "a_examiner" and decision is not None:
                continue
            if wanted is not None and (
                decision is None or decision.value is not wanted
            ):
                continue
            offers.append(offer)
        return offers

    def next_after(self, offer: Offer | None) -> Offer | None:
        """The offer to show after ``offer`` in triage mode: the next undecided one, else the first."""
        queue = self.queue
        if not queue:
            return None
        if offer is not None:
            order = [
                o for o in self.catalog.offers if not self.catalog.below_threshold(o)
            ]
            later = order[order.index(offer) + 1 :] if offer in order else []
            upcoming = next((o for o in later if o in queue), None)
            if upcoming is not None:
                return upcoming
        return queue[0]

    def neighbours(self, offer: Offer) -> tuple[Offer | None, Offer | None]:
        queue = self.queue
        if offer not in queue:
            return None, None
        index = queue.index(offer)
        previous = queue[index - 1] if index > 0 else None
        following = queue[index + 1] if index + 1 < len(queue) else None
        return previous, following

    def triage_context(self, current: Offer | None) -> dict[str, object]:
        previous, following = self.neighbours(current) if current else (None, None)
        return {"current": current, "previous": previous, "following": following}

    def render(
        self,
        name: str,
        values: Mapping[str, object] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        base = {
            "catalog": self.catalog,
            "decisions": self.decisions,
            "counts": self.counts(),
            "can_undo": self.book.can_undo(self.account.id),
        }
        return page(
            self.request,
            name,
            active="offers",
            status_code=status_code,
            context={**base, **(values or {})},
        )


def _whole_page(
    screen: Screen,
    view: str,
    filters: ListFilters,
    current: Offer | None = None,
    sheet: Offer | None = None,
) -> HTMLResponse:
    extra: dict[str, object] = {}
    if view == TRIAGE:
        current = current or screen.next_after(None)
        previous, following = screen.neighbours(current) if current else (None, None)
        extra = {"current": current, "previous": previous, "following": following}
    return screen.render(
        "offres/page.html",
        {
            "view": view,
            "filters": filters,
            "tracks": screen.catalog.tracks,
            "offers": screen.listed(filters),
            "sheet": sheet,
            **extra,
        },
    )


@router.get("", response_class=HTMLResponse)
def offers_page(
    request: Request,
    account: CurrentAccount,
    vue: str | None = None,
    piste: str | None = None,
    decision: str | None = None,
    sous_seuil: str | None = None,
    incompletes: str | None = None,
) -> HTMLResponse:
    screen = Screen(request, account)
    view = vue if vue in (TRIAGE, LIST) else (TRIAGE if screen.queue else LIST)
    return _whole_page(screen, view, _filters(piste, decision, sous_seuil, incompletes))


@router.get("/liste", response_class=HTMLResponse)
def offers_list(
    request: Request,
    account: CurrentAccount,
    piste: str | None = None,
    decision: str | None = None,
    sous_seuil: str | None = None,
    incompletes: str | None = None,
) -> Response:
    filters = _filters(piste, decision, sous_seuil, incompletes)
    if not is_htmx(request):
        return RedirectResponse(
            f"/offres?vue={LIST}&{filters.query()}", status_code=303
        )
    screen = Screen(request, account)
    return screen.render(
        "offres/list_rows.html",
        {
            "filters": filters,
            "offers": screen.listed(filters),
            "tracks": screen.catalog.tracks,
        },
    )


@router.get("/tri/{offer_id}", response_class=HTMLResponse)
def triage_offer(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id)
    if offer is None:
        return RedirectResponse("/offres", status_code=303)
    if not is_htmx(request):
        return _whole_page(screen, TRIAGE, ListFilters(), current=offer)
    return screen.render("offres/triage.html", screen.triage_context(offer))


@router.get("/{offer_id}/motifs", response_class=HTMLResponse)
def reasons_panel(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    decision: str,
    contexte: str = TRIAGE,
) -> Response:
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id)
    if offer is None or decision not in DecisionValue:
        return Response(status_code=404)
    value = DecisionValue(decision)
    current = screen.decisions.get(offer.id)
    checked = current.reasons if current and current.value is value else ()
    return screen.render(
        "offres/reasons.html",
        {
            "offer": offer,
            "value": value,
            "question": REASON_QUESTIONS[value],
            "reasons": REASONS[value],
            "checked": checked,
            "note": current.note if current and current.value is value else "",
            "context": contexte,
        },
    )


@router.get("/{offer_id}/actions", response_class=HTMLResponse)
def decision_actions(
    request: Request, account: CurrentAccount, offer_id: int, contexte: str = TRIAGE
) -> Response:
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id)
    if offer is None:
        return Response(status_code=404)
    return screen.render("offres/actions.html", {"offer": offer, "context": contexte})


@router.post("/{offer_id}/decision", response_class=HTMLResponse)
def record_decision(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    decision: Annotated[str, Form()],
    motifs: Annotated[list[str] | None, Form()] = None,
    precision: Annotated[str, Form()] = "",
    contexte: Annotated[str, Form()] = TRIAGE,
) -> Response:
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id)
    if offer is None:
        return Response(status_code=404)
    try:
        chosen = make_decision(decision, motifs or [], precision)
    except InvalidDecisionError as error:
        return _reasons_with_error(
            screen, offer, decision, motifs or [], precision, contexte, error
        )
    screen.book.record(account.id, offer.id, chosen)
    if not is_htmx(request):
        return RedirectResponse("/offres", status_code=303)
    screen = Screen(request, account)  # decisions changed
    if contexte == SHEET:
        response = screen.render(
            "offres/sheet.html", {"offer": offer, "with_counts": True}
        )
        response.headers["HX-Trigger"] = OFFERS_CHANGED
        return response
    return screen.render(
        "offres/triage.html",
        {"with_counts": True, **screen.triage_context(screen.next_after(offer))},
    )


def _reasons_with_error(
    screen: Screen,
    offer: Offer,
    decision: str,
    motifs: list[str],
    precision: str,
    context: str,
    error: InvalidDecisionError,
) -> Response:
    if decision not in DecisionValue:
        return Response(status_code=422)
    value = DecisionValue(decision)
    response = screen.render(
        "offres/reasons.html",
        {
            "offer": offer,
            "value": value,
            "question": REASON_QUESTIONS[value],
            "reasons": REASONS[value],
            "checked": tuple(motifs),
            "note": precision,
            "context": context,
            "error": str(error),
        },
    )
    # The form targets the whole card; an error only replaces the panel.
    response.headers["HX-Retarget"] = "#decision-area"
    response.headers["HX-Reswap"] = "innerHTML"
    return response


@router.post("/annuler", response_class=HTMLResponse)
def undo(request: Request, account: CurrentAccount) -> Response:
    screen = Screen(request, account)
    offer_id = screen.book.undo(account.id)
    if not is_htmx(request):
        return RedirectResponse("/offres?vue=tri", status_code=303)
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id) if offer_id is not None else None
    current = offer if offer in screen.queue else screen.next_after(None)
    response = screen.render(
        "offres/triage.html", {"with_counts": True, **screen.triage_context(current)}
    )
    response.headers["HX-Trigger"] = OFFERS_CHANGED
    return response


@router.get("/{offer_id}/pourquoi", response_class=HTMLResponse)
def why(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id)
    if offer is None:
        return Response(status_code=404)
    return screen.render("offres/why.html", {"offer": offer})


@router.get("/{offer_id}/fiche", response_class=HTMLResponse)
def sheet(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    screen = Screen(request, account)
    offer = screen.catalog.get(offer_id)
    if offer is None:
        return Response(status_code=404)
    if not is_htmx(request):
        return _whole_page(screen, LIST, ListFilters(), sheet=offer)
    return screen.render("offres/sheet.html", {"offer": offer})


@router.get("/fiche/fermer", response_class=HTMLResponse)
def close_sheet(account: CurrentAccount) -> HTMLResponse:
    return HTMLResponse("")


@router.post("/reinitialiser")
def reset(request: Request, account: CurrentAccount) -> RedirectResponse:
    """Prototype only: forget every decision of this account."""
    request.app.state.decision_book.reset(account.id)
    return RedirectResponse("/offres", status_code=303)
