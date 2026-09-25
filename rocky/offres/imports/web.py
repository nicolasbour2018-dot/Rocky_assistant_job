"""« Importer une annonce » (step C2): a link gives a preview of the offer or the reason why it gives none.

Nothing is stored (decision C2, Q1). The server renders every state; HTMX places the result under the form, and
requests without HTMX get the whole page.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rocky.offres.imports.model import (
    METHOD_LABELS,
    ImportOutcome,
    ImportResult,
    InvalidPasteError,
)
from rocky.offres.imports.rules import offer_from_paste
from rocky.offres.imports.usecases import import_link, link_sources
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    CollectedOffer,
    InvalidLinkError,
    source_label,
)
from rocky.offres.sources.registry import build_sources
from rocky.system.auth.web import CurrentAccount
from rocky.system.shell import page, wants_fragment

PAGE = "offres/import.html"
RESULT = "offres/import_result.html"
# Outcomes after which pasting the posting text is the way on (an invalid link is corrected instead).
PASTE_OUTCOMES = {ImportOutcome.REFUSED, ImportOutcome.FAILED}

router = APIRouter(prefix="/offres/importer")


def install(app: FastAPI) -> None:
    # Replaced by the tests: the recorded pages, and a fixed day.
    app.state.import_http = PublicHttp
    app.state.import_today = lambda: datetime.now(UTC).date()
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        method_labels=METHOD_LABELS,
        source_label=source_label,
        offer_facts=offer_facts,
        paste_outcomes=PASTE_OUTCOMES,
    )
    app.include_router(router)


def offer_facts(offer: CollectedOffer) -> list[tuple[str, str]]:
    """The facts of the preview that are known, as published (their interpretation is the posting analysis, C3)."""
    place = ", ".join(part for part in (offer.location, offer.country) if part)
    facts = [
        ("Employeur", offer.company),
        ("Lieu", place),
        ("Contrat", offer.contract),
        ("Télétravail", offer.remote),
        ("Salaire", _salary(offer)),
        ("Secteur", offer.sector),
        ("Publiée le", _day(offer.published_on)),
        ("Date limite", _day(offer.deadline)),
    ]
    return [(label, value) for label, value in facts if value]


@router.get("", response_class=HTMLResponse)
def import_page(request: Request, account: CurrentAccount) -> HTMLResponse:
    return _render(request, {})


@router.post("", response_class=HTMLResponse)
def import_posting(
    request: Request, account: CurrentAccount, lien: Annotated[str, Form()] = ""
) -> HTMLResponse:
    new_http: Callable[[], PublicHttp] = request.app.state.import_http
    today: Callable[[], date] = request.app.state.import_today
    http = new_http()
    try:
        sources = link_sources(build_sources(request.app.state.settings.sources, http))
        result = import_link(lien, http, sources, today=today())
    finally:
        http.close()
    context: dict[str, object] = {"link": lien, "result": result}
    if result.outcome in PASTE_OUTCOMES or (
        result.preview is not None and not result.preview.offer.description_complete
    ):
        offer = result.preview.offer if result.preview else None
        context["paste"] = {
            "link": offer.url if offer else lien.strip(),
            "title": offer.title if offer else "",
            "company": (offer.company or "") if offer else "",
            "text": "",
        }
    status = (
        400
        if result.outcome == ImportOutcome.INVALID and not wants_fragment(request)
        else 200
    )
    return _render(request, context, status)


@router.post("/texte", response_class=HTMLResponse)
def import_pasted(
    request: Request,
    account: CurrentAccount,
    lien: Annotated[str, Form()] = "",
    intitule: Annotated[str, Form()] = "",
    employeur: Annotated[str, Form()] = "",
    texte: Annotated[str, Form()] = "",
) -> HTMLResponse:
    paste = {"link": lien, "title": intitule, "company": employeur, "text": texte}
    try:
        preview = offer_from_paste(lien, intitule, texte, employeur)
    except InvalidLinkError as error:
        return _paste_error(request, paste, error.reason)
    except InvalidPasteError as error:
        return _paste_error(request, paste, str(error))
    return _render(request, {"link": lien, "result": ImportResult.ok(preview)})


def _paste_error(request: Request, paste: dict[str, str], reason: str) -> HTMLResponse:
    context = {"link": paste["link"], "paste": {**paste, "error": reason}}
    # HTMX does not swap 4xx answers: a form error it asked for comes back as 200.
    return _render(request, context, 200 if wants_fragment(request) else 400)


def _render(
    request: Request, context: Mapping[str, object], status_code: int = 200
) -> HTMLResponse:
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(
            request, RESULT, dict(context), status_code=status_code
        )
    return page(
        request, PAGE, active="offers", status_code=status_code, context=context
    )


def _salary(offer: CollectedOffer) -> str | None:
    if offer.salary_text:
        return offer.salary_text
    bounds = sorted(
        {value for value in (offer.salary_min, offer.salary_max) if value is not None}
    )
    if not bounds:
        return None
    amount = " – ".join(f"{value:,.0f}".replace(",", " ") for value in bounds)
    return " ".join(
        part for part in (amount, offer.salary_currency, offer.salary_period) if part
    )


def _day(day: date | None) -> str | None:
    return f"{day:%d/%m/%Y}" if day else None
