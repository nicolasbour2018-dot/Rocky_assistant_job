"""Offers screen (step C7, started as the B4 prototype): triage mode, compact list, side sheet, « Pourquoi ? ».

The server renders every state as HTML from the stored offers; HTMX swaps the fragments. Requests without HTMX get
whole pages or a redirection. Decision ``docs/decisions/C7-ecran-offres.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from functools import cached_property
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import Connection, Engine

from rocky.offres.analysis.model import PostingAnalysis
from rocky.offres.analysis.rules import analyze, deadline_of
from rocky.offres.analysis.text import formatted_description
from rocky.offres.analysis.usecases import Summary, SummaryResult, summarize
from rocky.offres.decisions import (
    AUTOMATIC_REASONS,
    DECISION_KEYS,
    DECISION_LABELS,
    REASON_QUESTIONS,
    REASONS,
    Decision,
    DecisionValue,
    InvalidDecisionError,
    effective_decisions,
    make_decision,
    reason_key,
    reason_label,
    to_cancel,
)
from rocky.offres.imports import web as imports_web
from rocky.offres.imports.model import InvalidPasteError
from rocky.offres.imports.rules import BROWSER_REFUSED_REASON, readable_in_browser
from rocky.offres.model import OfferHeading, Origin
from rocky.offres.rules import match_key, scoring_inputs
from rocky.offres.screen import (
    DECISION_FILTER_LABELS,
    PAGE_SIZE,
    Counts,
    ListedOffer,
    ListFilters,
    OfferCard,
    band,
    counts,
    listed,
    make_filters,
    neighbours,
    next_after,
    offer_card,
    past_deadlines,
    queue,
)
from rocky.offres.sources.model import MESSAGE_SOURCE, CollectedOffer
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import (
    PageReading,
    ReadingOutcome,
    add_offer_from_message,
    cancel_decision,
    cancel_last_decision,
    enrich_offer,
    enrich_offer_from_page,
    keep_summary,
    record_decision,
    record_offer,
    stored_summary,
)
from rocky.offres.watch import web as watch_web
from rocky.profil.model import Profile
from rocky.profil.web import profile_of
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.llm import JsonModel
from rocky.system.shell import (
    Action,
    Card,
    Drawer,
    add_drawer,
    add_today_cards,
    page,
    wants_fragment,
)
from rocky.system.workstation import Workstation, WorkstationUnavailableError

TRIAGE = "tri"
LIST = "liste"
SHEET = "fiche"
OFFERS_CHANGED = "offers-changed"
SUMMARY = "offres/import_summary.html"

router = APIRouter(prefix="/offres")


def install(app: FastAPI) -> None:
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        decision_labels=DECISION_LABELS,
        decision_keys=DECISION_KEYS,
        decision_filter_labels=DECISION_FILTER_LABELS,
        reason_label=reason_label,
        reason_key=reason_key,
        band=band,
        list_query=list_query,
        offer_shortcuts=SHORTCUTS,
    )
    templates.env.filters["age"] = age
    imports_web.install(app)
    watch_web.install(app)
    add_today_cards(app, "offres", _today_cards)
    add_drawer(app, "offers", _drawer)
    app.include_router(router)


def _kbd(*keys: str) -> Markup:
    return Markup(" ").join(Markup("<kbd>{}</kbd>").format(key) for key in keys)


# The keyboard of the screen (decisions B4, C7): its help « ? » and the drawer 🐾 (decision F1, Q12).
SHORTCUTS: tuple[tuple[Markup, Markup | str], ...] = (
    (_kbd("i", "e", "p"), "Intéressé, écarté, plus tard"),
    (
        Markup("<kbd>1</kbd>…<kbd>9</kbd> <kbd>0</kbd>"),
        Markup("Cocher un motif (<kbd>0</kbd> : autre)"),
    ),
    (_kbd("t"), "Écrire une précision"),
    (_kbd("Entrée"), "Valider la décision"),
    (_kbd("d"), "Intéressé : valider et préparer la candidature"),
    (_kbd("Échap"), "Revenir sans décider"),
    (_kbd("u"), "Annuler la dernière décision (plusieurs fois possible)"),
    (_kbd("j", "k"), "Offre suivante, précédente"),
    (_kbd("w"), "Pourquoi ce score ?"),
    (_kbd("r"), "Résumer l'annonce"),
    (_kbd("c"), "Coller la description d'une annonce incomplète"),
    (
        _kbd("n"),
        "Ouvrir une annonce incomplète dans le navigateur, puis lire la page affichée",
    ),
    (_kbd("o"), "Ouvrir l'annonce d'origine"),
    (_kbd("?"), "Cette aide"),
)
IMPORT = Action("Importer une annonce", "/offres/importer")


def _drawer(request: Request, account: Account) -> Drawer:
    """What to do on 🔎 Offres: the triage, the incomplete offers to complete, an import."""
    screen = Screen(request, account)
    actions: list[Action] = []
    to_review = len(screen.queue)
    if to_review:
        actions.append(
            Action(
                f"Trier les {to_review} offres à examiner"
                if to_review > 1
                else "Trier l'offre à examiner",
                f"/offres?vue={TRIAGE}",
            )
        )
    incomplete = listed(screen.offers, screen.decisions, ListFilters(incomplete=True))
    if incomplete:
        actions.append(
            Action(
                f"Compléter les offres incomplètes ({len(incomplete)})",
                f"/offres?vue={LIST}&{list_query(ListFilters(incomplete=True))}",
            )
        )
    actions.append(IMPORT)
    return Drawer(actions=tuple(actions), shortcuts=SHORTCUTS)


def _today_cards(request: Request, account: Account) -> list[Card]:
    """The block « Offres à examiner » of 🏠 Aujourd'hui (decision F1, Q5): the queue of the triage."""
    screen = Screen(request, account)
    card = review_card(counts(screen.offers, screen.decisions))
    return [] if card is None else [card]


def review_card(found: Counts) -> Card | None:
    if not found.to_review:
        return None
    s = "s" if found.to_review > 1 else ""
    return Card(
        "🔎 Offres à examiner",
        (
            f"{found.to_review} offre{s} au-dessus du seuil attend{'ent' if s else ''} ta décision.",
        ),
        action=Action("Trier les offres", f"/offres?vue={TRIAGE}"),
    )


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


def list_query(filters: ListFilters, start: int = 0) -> str:
    """The filters of the list as written in its URL (and the first row of a page)."""
    values = {
        "piste": "" if filters.track_id is None else str(filters.track_id),
        "decision": filters.decision,
        "sous_seuil": "1" if filters.below_threshold else "",
        "incompletes": "1" if filters.incomplete else "",
        "depuis": str(start) if start else "",
    }
    return urlencode({key: value for key, value in values.items() if value})


def _track(value: str | None) -> int | None:
    return int(value) if value and value.isascii() and value.isdigit() else None


class Screen:
    """What one account sees: its offers, their current scores and the decisions in force."""

    def __init__(self, request: Request, account: Account) -> None:
        self.request = request
        self.account = account
        with self.engine.begin() as connection:
            store = SqlStore(connection)
            self.offers = store.listed_offers(account.id)
            rows = store.decision_rows(account.id)
        self.decisions = effective_decisions(rows)
        self.can_undo = to_cancel(rows) is not None

    @property
    def engine(self) -> Engine:
        engine: Engine = self.request.app.state.engine
        return engine

    @cached_property
    def profile(self) -> Profile:
        return profile_of(self.request, self.account)

    @cached_property
    def track_names(self) -> dict[int, str]:
        return {track.id: track.name for track in self.profile.tracks}

    @property
    def queue(self) -> list[ListedOffer]:
        return queue(self.offers, self.decisions)

    def listed_offer(self, offer_id: int) -> ListedOffer | None:
        return next((offer for offer in self.offers if offer.id == offer_id), None)

    def page_of(
        self, filters: ListFilters, start: int = 0
    ) -> tuple[list[ListedOffer], int | None]:
        """One page of the list, and the first row of the next page (None on the last one)."""
        offers = listed(self.offers, self.decisions, filters)
        end = start + PAGE_SIZE
        return offers[start:end], end if end < len(offers) else None

    def card(self, offer_id: int, track_id: int | None = None) -> OfferCard | None:
        """The card of an offer of the account; None for an unknown offer or one of another account."""
        with self.engine.begin() as connection:
            store = SqlStore(connection)
            stored = store.offer_of(self.account.id, offer_id)
            score = None if stored is None else store.current_score(offer_id)
            if stored is None or score is None:
                return None
            linked = store.track_ids(offer_id)
            same = store.same_posting(
                self.account.id, offer_id, match_key(stored.offer)
            )
            summary = stored_summary(store, stored)
        inputs = scoring_inputs(self.profile)
        return offer_card(
            stored,
            score=score,
            analysis=analyze(stored.offer, inputs.skills, today=_today(self.request)),
            profile=inputs.profile,
            track_names=self.track_names,
            linked=linked,
            same_posting=same,
            decision=self.decisions.get(offer_id),
            summary=summary,
            today=_today(self.request),
            track_id=track_id,
        )

    def triage_context(self, current: int | None) -> dict[str, object]:
        """The triage card of ``current`` (else the first of the queue), with its neighbours."""
        if current is None:
            first = next_after(self.offers, self.decisions, None)
            current = None if first is None else first.id
        card = None if current is None else self.card(current)
        previous, following = (
            neighbours(self.offers, self.decisions, card.id)
            if card is not None
            else (None, None)
        )
        return {"card": card, "previous": previous, "following": following}

    def render(
        self,
        name: str,
        values: Mapping[str, object] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        base = {
            "decisions": self.decisions,
            "counts": counts(self.offers, self.decisions),
            "has_offers": bool(self.offers),
            "can_undo": self.can_undo,
            "past_deadlines": past_deadlines(self.offers, _today(self.request)),
        }
        return page(
            self.request,
            name,
            active="offers",
            status_code=status_code,
            context={**base, **(values or {})},
        )


def _decision_of(
    request: Request, account: Account, offer_id: int
) -> tuple[bool, Decision | None]:
    """Whether the offer belongs to the account, and its decision in force; reads that offer only."""
    engine: Engine = request.app.state.engine
    with engine.begin() as connection:
        store = SqlStore(connection)
        if store.offer_of(account.id, offer_id) is None:
            return False, None
        row = effective_decisions(store.decision_rows(account.id, offer_id)).get(
            offer_id
        )
    return True, None if row is None else row.decision


def _fragment(
    request: Request, name: str, context: Mapping[str, object]
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, name, dict(context))


def _today(request: Request) -> date:
    today: Callable[[], date] = request.app.state.import_today
    return today()


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.auth.clock
    return clock()


def _whole_page(
    screen: Screen,
    view: str,
    filters: ListFilters,
    *,
    current: int | None = None,
    sheet: OfferCard | None = None,
    sheet_extra: Mapping[str, object] | None = None,
) -> HTMLResponse:
    extra = screen.triage_context(current) if view == TRIAGE else {}
    rows, more = screen.page_of(filters)
    return screen.render(
        "offres/page.html",
        {
            "view": view,
            "filters": filters,
            "tracks": screen.track_names,
            "offers": rows,
            "more": more,
            "sheet": sheet,
            **extra,
            **(sheet_extra or {}),
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
    filters = make_filters(piste, decision, sous_seuil, incompletes)
    return _whole_page(screen, view, filters)


@router.get("/liste", response_class=HTMLResponse)
def offers_list(
    request: Request,
    account: CurrentAccount,
    piste: str | None = None,
    decision: str | None = None,
    sous_seuil: str | None = None,
    incompletes: str | None = None,
    depuis: int = 0,
) -> Response:
    filters = make_filters(piste, decision, sous_seuil, incompletes)
    if not wants_fragment(request):
        return RedirectResponse(
            f"/offres?vue={LIST}&{list_query(filters)}", status_code=303
        )
    screen = Screen(request, account)
    rows, more = screen.page_of(filters, max(depuis, 0))
    return screen.render(
        "offres/list_rows.html" if depuis <= 0 else "offres/offer_rows.html",
        {"filters": filters, "offers": rows, "more": more},
    )


@router.get("/tri/{offer_id}", response_class=HTMLResponse)
def triage_offer(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    screen = Screen(request, account)
    if screen.listed_offer(offer_id) is None:
        return RedirectResponse("/offres", status_code=303)
    if not wants_fragment(request):
        return _whole_page(screen, TRIAGE, ListFilters(), current=offer_id)
    return screen.render("offres/triage.html", screen.triage_context(offer_id))


def _reasons(
    request: Request,
    offer_id: int,
    value: DecisionValue,
    *,
    context: str,
    track_id: int | None,
    checked: tuple[str, ...] = (),
    note: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return _fragment(
        request,
        "offres/reasons.html",
        {
            "offer_id": offer_id,
            "value": value,
            "question": REASON_QUESTIONS[value],
            "reasons": REASONS[value],
            "checked": checked,
            "note": note or "",
            "context": context,
            "piste": "" if track_id is None else track_id,
            "error": error,
        },
    )


@router.get("/{offer_id}/motifs", response_class=HTMLResponse)
def reasons_panel(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    decision: str,
    contexte: str = TRIAGE,
    piste: str | None = None,
) -> Response:
    found, current = _decision_of(request, account, offer_id)
    if not found or decision not in DecisionValue:
        return Response(status_code=404)
    value = DecisionValue(decision)
    same = current is not None and current.value is value
    return _reasons(
        request,
        offer_id,
        value,
        context=contexte,
        track_id=_track(piste),
        checked=current.reasons if same and current else (),
        note=current.note if same and current else None,
    )


@router.get("/{offer_id}/actions", response_class=HTMLResponse)
def decision_actions(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    contexte: str = TRIAGE,
    piste: str | None = None,
) -> Response:
    found, current = _decision_of(request, account, offer_id)
    if not found:
        return Response(status_code=404)
    return _fragment(
        request,
        "offres/actions.html",
        {
            "offer_id": offer_id,
            "chosen": current,
            "context": contexte,
            "piste": piste or "",
        },
    )


@router.post("/{offer_id}/decision", response_class=HTMLResponse)
def decide(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    decision: Annotated[str, Form()],
    motifs: Annotated[list[str] | None, Form()] = None,
    precision: Annotated[str, Form()] = "",
    contexte: Annotated[str, Form()] = TRIAGE,
    piste: Annotated[str, Form()] = "",
) -> Response:
    engine: Engine = request.app.state.engine
    with engine.begin() as connection:
        found = SqlStore(connection).offer_of(account.id, offer_id) is not None
    if not found:
        return Response(status_code=404)
    track_id = _track(piste)
    try:
        chosen: Decision = make_decision(decision, motifs or [], precision)
    except InvalidDecisionError as error:
        if decision not in DecisionValue:
            return Response(status_code=422)
        response = _reasons(
            request,
            offer_id,
            DecisionValue(decision),
            context=contexte,
            track_id=track_id,
            checked=tuple(motifs or ()),
            note=precision,
            error=str(error),
        )
        # The form targets the whole card; an error only replaces the panel.
        response.headers["HX-Retarget"] = "#decision-area"
        response.headers["HX-Reswap"] = "innerHTML"
        return response
    with engine.begin() as connection:
        record_decision(
            SqlStore(connection),
            account_id=account.id,
            offer_id=offer_id,
            decision=chosen,
            track_id=track_id,
            now=_now(request),
        )
    return _after_change(request, account, offer_id, contexte, track_id)


def _after_change(
    request: Request,
    account: Account,
    offer_id: int,
    context: str,
    track_id: int | None,
    *,
    stay: bool = False,
    extra: Mapping[str, object] | None = None,
) -> Response:
    """The screen after a decision or a pasted description: the sheet again, or the triage card (the next offer
    after a decision, the same one when ``stay``)."""
    if not wants_fragment(request):
        if context == SHEET:
            return RedirectResponse(f"/offres/{offer_id}/fiche", status_code=303)
        target = f"/offres/tri/{offer_id}" if stay else f"/offres?vue={TRIAGE}"
        return RedirectResponse(target, status_code=303)
    screen = Screen(request, account)  # decisions or scores changed
    if context == SHEET:
        response = screen.render(
            "offres/sheet.html",
            {
                "card": screen.card(offer_id, track_id),
                "with_counts": True,
                **(extra or {}),
            },
        )
        response.headers["HX-Trigger"] = OFFERS_CHANGED
        return response
    current = (
        offer_id
        if stay
        else (
            None
            if (upcoming := next_after(screen.offers, screen.decisions, offer_id))
            is None
            else upcoming.id
        )
    )
    triage = screen.triage_context(current) if current is not None else {}
    return screen.render(
        "offres/triage.html",
        {"with_counts": True, "card": None, **triage, **(extra or {})},
    )


@router.post("/annuler", response_class=HTMLResponse)
def undo(request: Request, account: CurrentAccount) -> Response:
    engine: Engine = request.app.state.engine
    with engine.begin() as connection:
        offer_id = cancel_last_decision(
            SqlStore(connection), account_id=account.id, now=_now(request)
        )
    if not wants_fragment(request):
        return RedirectResponse(f"/offres?vue={TRIAGE}", status_code=303)
    screen = Screen(request, account)
    back = offer_id if any(o.id == offer_id for o in screen.queue) else None
    response = screen.render(
        "offres/triage.html", {"with_counts": True, **screen.triage_context(back)}
    )
    response.headers["HX-Trigger"] = OFFERS_CHANGED
    return response


@router.post("/{offer_id}/description", response_class=HTMLResponse)
def paste_description(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    texte: Annotated[str, Form()] = "",
    contexte: Annotated[str, Form()] = TRIAGE,
    piste: Annotated[str, Form()] = "",
) -> Response:
    """« Coller la description » (Q5, Q13): the score is computed again at once; the offer stays on screen."""
    screen = Screen(request, account)
    with screen.engine.begin() as connection:
        stored = SqlStore(connection).offer_of(account.id, offer_id)
    if stored is None:
        return Response(status_code=404)
    inputs = scoring_inputs(screen.profile)
    error: str | None = None
    try:
        with screen.engine.begin() as connection:
            enrich_offer(
                SqlStore(connection),
                stored,
                texte,
                inputs=inputs,
                now=_now(request),
                today=_today(request),
            )
    except InvalidPasteError as invalid:
        error = str(invalid)
    return _after_change(
        request,
        account,
        offer_id,
        contexte,
        _track(piste),
        stay=True,
        extra={"paste_error": error},
    )


# The lecture assistée (decision E5): the Rocky workstation opens the posting in a visible browser on the user's
# computer; the user passes any challenge, then asks Rocky to read the page shown (Q1). The workstation is called
# outside any transaction.
READING = "offres/browser_reading.html"
READ_NOTE = "Description lue sur la page affichée : le score est recalculé."
FACTS_NOTE = "Les faits qui manquaient ont été repris de la page."
NOTHING_NOTE = "La page affichée n'apporte rien de nouveau à cette offre."


@router.post("/{offer_id}/navigateur", response_class=HTMLResponse)
def open_in_browser(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    contexte: Annotated[str, Form()] = TRIAGE,
    piste: Annotated[str, Form()] = "",
) -> Response:
    """« Ouvrir dans le navigateur »: the posting in a tab of the workstation; then « Lire la page affichée »."""
    screen = Screen(request, account)
    with screen.engine.begin() as connection:
        stored = SqlStore(connection).offer_of(account.id, offer_id)
    if stored is None:
        return Response(status_code=404)
    workstation: Workstation = request.app.state.workstation
    values: dict[str, object] = {}
    if not readable_in_browser(stored.offer):
        values["reading_error"] = BROWSER_REFUSED_REASON
    else:
        try:
            values["reading_tab"] = workstation.open_page(stored.offer.url)
        except WorkstationUnavailableError as error:
            values["reading_error"] = error.reason
    if not wants_fragment(request):
        card = screen.card(offer_id, _track(piste))
        filters = ListFilters(track_id=_track(piste))
        return _whole_page(screen, LIST, filters, sheet=card, sheet_extra=values)
    return screen.render(
        READING, {"offer_id": offer_id, "context": contexte, "piste": piste, **values}
    )


@router.post("/{offer_id}/navigateur/lire", response_class=HTMLResponse)
def read_shown_page(
    request: Request,
    account: CurrentAccount,
    offer_id: int,
    onglet: Annotated[str, Form()] = "",
    contexte: Annotated[str, Form()] = TRIAGE,
    piste: Annotated[str, Form()] = "",
) -> Response:
    """« Lire la page affichée »: the page shown in the tab completes the offer (``enrich_offer_from_page``), whose
    score is computed again at once; the offer stays on screen with what the reading gave."""
    screen = Screen(request, account)
    with screen.engine.begin() as connection:
        stored = SqlStore(connection).offer_of(account.id, offer_id)
    if stored is None:
        return Response(status_code=404)
    workstation: Workstation = request.app.state.workstation
    try:
        shown = workstation.read_page(onglet)
    except WorkstationUnavailableError as error:
        message = ("error", error.reason)
    else:
        with screen.engine.begin() as connection:
            reading = enrich_offer_from_page(
                SqlStore(connection),
                stored,
                shown.url,
                shown.html,
                inputs=scoring_inputs(screen.profile),
                now=_now(request),
                today=_today(request),
            )
        message = _reading_message(reading)
    return _after_change(
        request,
        account,
        offer_id,
        contexte,
        _track(piste),
        stay=True,
        extra={"reading_message": message},
    )


def _reading_message(reading: PageReading) -> tuple[str, str]:
    """The kind (``done``, ``info``, ``error``: the class of the alert) and the French text of a reading."""
    match reading.outcome:
        case ReadingOutcome.COMPLETED:
            return "done", READ_NOTE
        case ReadingOutcome.FACTS_ONLY:
            return "info", f"{reading.reason} {FACTS_NOTE}"
        case ReadingOutcome.NOTHING_NEW:
            return "info", reading.reason or NOTHING_NOTE
        case ReadingOutcome.OTHER_PAGE | ReadingOutcome.UNREADABLE:
            return "error", reading.reason or NOTHING_NOTE


@router.post("/{offer_id}/resume", response_class=HTMLResponse)
def summary(request: Request, account: CurrentAccount, offer_id: int) -> Response:
    """The summary of the offer (Q6): the one kept, or one call to the language model, kept when it succeeds."""
    engine: Engine = request.app.state.engine
    with engine.begin() as connection:
        store = SqlStore(connection)
        stored = store.offer_of(account.id, offer_id)
        kept = None if stored is None else stored_summary(store, stored)
    if stored is None:
        return Response(status_code=404)
    if kept is not None:
        result = SummaryResult(summary=kept)
    else:
        model: JsonModel = request.app.state.llm_model
        # The model is called outside any transaction (a network call never holds one, C6).
        result = summarize(
            stored.offer.title, formatted_description(stored.offer.description), model
        )
        if result.summary is not None:
            with engine.begin() as connection:
                keep_summary(
                    SqlStore(connection), stored, result.summary, now=_now(request)
                )
    if not wants_fragment(request):
        return RedirectResponse(f"/offres/{offer_id}/fiche", status_code=303)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, SUMMARY, {"summary_result": result})


@router.get("/{offer_id}/pourquoi", response_class=HTMLResponse)
def why(
    request: Request, account: CurrentAccount, offer_id: int, piste: str | None = None
) -> Response:
    screen = Screen(request, account)
    card = screen.card(offer_id, _track(piste))
    if card is None:
        return Response(status_code=404)
    return screen.render("offres/why.html", {"card": card})


@router.get("/{offer_id}/fiche", response_class=HTMLResponse)
def sheet(
    request: Request, account: CurrentAccount, offer_id: int, piste: str | None = None
) -> Response:
    screen = Screen(request, account)
    card = screen.card(offer_id, _track(piste))
    if card is None:
        return Response(status_code=404)
    if not wants_fragment(request):
        filters = ListFilters(track_id=_track(piste))
        return _whole_page(screen, LIST, filters, sheet=card)
    return screen.render("offres/sheet.html", {"card": card})


@router.get("/fiche/fermer", response_class=HTMLResponse)
def close_sheet(account: CurrentAccount) -> HTMLResponse:
    return HTMLResponse("")


# For the other modules (the applications, D1), on the caller's connection and inside its transaction: they never
# read the tables of ``offres`` themselves.


def offer_headings(
    connection: Connection, account_id: int, offer_ids: Iterable[int]
) -> dict[int, OfferHeading]:
    """The account's offers among ``offer_ids``; an offer of another account is absent."""
    return SqlStore(connection).headings(account_id, offer_ids)


def offer_analysis(
    connection: Connection,
    account_id: int,
    offer_id: int,
    profile: Profile,
    today: date,
) -> PostingAnalysis | None:
    """The analysis of an offer of the account with its profile's skills (D3: the CV of an application is targeted
    with it); None for an unknown offer or one of another account."""
    stored = SqlStore(connection).offer_of(account_id, offer_id)
    if stored is None:
        return None
    return analyze(stored.offer, scoring_inputs(profile).skills, today=today)


def offer_deadlines(
    connection: Connection, account_id: int, offer_ids: Iterable[int], today: date
) -> dict[int, date]:
    """The deadline of the account's offers among ``offer_ids`` that have one (the applications, decision D6, Q8)."""
    return {
        stored.id: deadline
        for stored in SqlStore(connection).offers_of(account_id, offer_ids)
        if (deadline := deadline_of(stored.offer, today=today)) is not None
    }


def decision_in_force(
    connection: Connection, account_id: int, offer_id: int
) -> DecisionValue | None:
    """The value of the offer's decision in force, None when it has none (to examine)."""
    rows = SqlStore(connection).decision_rows(account_id, offer_id)
    row = effective_decisions(rows).get(offer_id)
    return None if row is None or row.decision is None else row.decision.value


def interested_reason(
    connection: Connection, account_id: int, offer_id: int
) -> tuple[tuple[str, ...], str | None] | None:
    """The reasons (French labels) and the note of the offer's « Intéressé » in force (decision D4, Q15: the letter
    starts from why the user wants this offer); None when the decision in force is another one, or none."""
    rows = SqlStore(connection).decision_rows(account_id, offer_id)
    row = effective_decisions(rows).get(offer_id)
    if row is None or row.decision is None:
        return None
    decision = row.decision
    if decision.value is not DecisionValue.INTERESTED:
        return None
    automatic = {reason.code for reason in AUTOMATIC_REASONS[decision.value]}
    labels = tuple(
        reason_label(decision.value, code)
        for code in decision.reasons
        if code not in automatic
    )
    return labels, decision.note


def offer_summary(
    connection: Connection, account_id: int, offer_id: int
) -> Summary | None:
    """The summary kept for the offer (C7), unless its description changed since; never asks the model."""
    store = SqlStore(connection)
    stored = store.offer_of(account_id, offer_id)
    return None if stored is None else stored_summary(store, stored)


def interested_offers(connection: Connection, account_id: int) -> list[int]:
    """The account's offers whose decision in force is « Intéressé », the latest decided first (D3, Q26)."""
    rows = effective_decisions(SqlStore(connection).decision_rows(account_id))
    kept = [
        row
        for row in rows.values()
        if row.decision is not None and row.decision.value is DecisionValue.INTERESTED
    ]
    return [row.offer_id for row in sorted(kept, key=lambda row: row.id, reverse=True)]


def record_application_decision(
    connection: Connection,
    *,
    account_id: int,
    offer_id: int,
    decision: Decision,
    now: datetime,
) -> int:
    """Record the « Intéressé » of « Préparer la candidature » (D1, Q8), with the best track's score shown."""
    return record_decision(
        SqlStore(connection),
        account_id=account_id,
        offer_id=offer_id,
        decision=decision,
        track_id=None,
        now=now,
    )


def record_message_offer(
    connection: Connection,
    *,
    account_id: int,
    message_id: int,
    company: str,
    title: str,
    link: str,
    profile: Profile,
    now: datetime,
    today: date,
) -> int:
    """The minimal offer of an application made outside Rocky, created from a message (decision E4, Q4, Q12): the
    employer and title the user confirmed, the posting's ``link`` (or the message's own link). Returns its id."""
    offer = CollectedOffer(
        source=MESSAGE_SOURCE,
        external_id=f"message-{message_id}",
        url=link,
        title=title,
        company=company or None,
        description="",
        description_complete=False,
        incomplete_reason="Créée depuis un message : colle la description de l'annonce pour la compléter.",
    )
    return add_offer_from_message(
        SqlStore(connection),
        account_id=account_id,
        offer=offer,
        inputs=scoring_inputs(profile),
        message_id=message_id,
        now=now,
        today=today,
    ).offer_id


def record_alert_offer(
    connection: Connection,
    *,
    account_id: int,
    offer: CollectedOffer,
    profile: Profile,
    now: datetime,
    today: date,
) -> tuple[int, bool]:
    """The offer of a card of a job alert (decision E3, Q3), with its best track and its scores: its id and whether it
    is new. A known offer is completed, never overwritten (C6, Q7). No event per offer, as for the watch: the reading
    of the alert is the fact (``messages.alert_read``)."""
    recorded = record_offer(
        SqlStore(connection),
        account_id=account_id,
        offer=offer,
        inputs=scoring_inputs(profile),
        origin=Origin.ALERT,
        now=now,
        today=today,
    )
    return recorded.offer_id, recorded.created


def complete_offer_keys(
    connection: Connection, account_id: int, keys: Iterable[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Among ``(source, external_id)`` keys, those of the account's offers already known with a complete description
    (decision E3: their posting is not read again)."""
    return SqlStore(connection).complete_keys(account_id, keys)


def try_lock_offers(connection: Connection, account_id: int) -> bool:
    """The lock of the account's offers for the transaction in progress; False while a watch holds it (decision E3)."""
    return SqlStore(connection).try_lock(account_id)


def cancel_application_decision(
    connection: Connection, *, account_id: int, decision_id: int, now: datetime
) -> bool:
    """Cancel the decision written with an application whose creation is cancelled (D1, Q9)."""
    return cancel_decision(
        SqlStore(connection), account_id=account_id, decision_id=decision_id, now=now
    )
