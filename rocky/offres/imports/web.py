"""« Importer une annonce » (steps C2, C3, C4): a link gives a preview of the offer, its analysis and its score, or the
reason why it gives none; the summary by the language model is asked on demand.

Nothing is stored (decisions C2, C3 and C4, Q1 and Q12). The server renders every state; HTMX places the result
under the form, and requests without HTMX get the whole page.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rocky.offres.analysis.model import (
    CONDITION_LABELS,
    IMPORTANCE_LABELS,
    SALARY_PERIOD_LABELS,
    Importance,
    PostingAnalysis,
    Salary,
)
from rocky.offres.analysis.rules import account_skills, analyze
from rocky.offres.analysis.usecases import summarize
from rocky.offres.imports.model import (
    METHOD_LABELS,
    ImportOutcome,
    ImportPreview,
    ImportResult,
    InvalidPasteError,
)
from rocky.offres.imports.rules import offer_from_paste
from rocky.offres.imports.usecases import import_link, link_sources
from rocky.offres.scoring.model import (
    CAP,
    COMPONENT_LABELS,
    CONFIDENCE_LABELS,
)
from rocky.offres.scoring.rules import number, score, scoring_profile
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    CollectedOffer,
    InvalidLinkError,
    source_label,
)
from rocky.offres.sources.registry import build_sources
from rocky.profil.model import (
    CONTRACT_LABELS,
    LANGUAGE_LEVEL_LABELS,
    LANGUAGE_NAMES,
    REMOTE_LABELS,
)
from rocky.profil.web import profile_of
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.llm import GeminiModel, JsonModel
from rocky.system.shell import page, wants_fragment

PAGE = "offres/import.html"
RESULT = "offres/import_result.html"
SUMMARY = "offres/import_summary.html"
# Outcomes after which pasting the posting text is the way on (an invalid link is corrected instead).
PASTE_OUTCOMES = {ImportOutcome.REFUSED, ImportOutcome.FAILED}
IMPORTANCE_ORDER = (Importance.ELIMINATORY, Importance.PREFERRED, Importance.DETECTED)

router = APIRouter(prefix="/offres/importer")


def install(app: FastAPI) -> None:
    # Replaced by the tests: the recorded pages, a fixed day, a fake language model.
    app.state.import_http = PublicHttp
    app.state.import_today = lambda: datetime.now(UTC).date()
    app.state.llm_model = GeminiModel(app.state.settings.llm)
    templates: Jinja2Templates = app.state.templates
    templates.env.globals.update(
        method_labels=METHOD_LABELS,
        source_label=source_label,
        offer_facts=offer_facts,
        analysis_facts=analysis_facts,
        paste_outcomes=PASTE_OUTCOMES,
        importance_order=IMPORTANCE_ORDER,
        importance_labels=IMPORTANCE_LABELS,
        condition_labels=CONDITION_LABELS,
        component_labels=COMPONENT_LABELS,
        confidence_labels=CONFIDENCE_LABELS,
        score_cap=number(CAP),
        number=number,
    )
    app.include_router(router)


def offer_facts(offer: CollectedOffer) -> list[tuple[str, str]]:
    """The facts of the preview that are known, as published."""
    place = ", ".join(part for part in (offer.location, offer.country) if part)
    facts = [
        ("Employeur", offer.company),
        ("Lieu", place),
        ("Secteur", offer.sector),
        ("Salaire affiché", offer.salary_text),
        ("Publiée le", _day(offer.published_on)),
    ]
    return [(label, value) for label, value in facts if value]


def analysis_facts(analysis: PostingAnalysis) -> list[tuple[str, str]]:
    """The facts read by the analysis, in the words of the profile."""
    languages = ", ".join(
        LANGUAGE_NAMES.get(need.code, need.code)
        + (f" ({LANGUAGE_LEVEL_LABELS[need.level]})" if need.level else "")
        for need in analysis.languages
    )
    facts = [
        (
            "Contrat",
            ", ".join(CONTRACT_LABELS[contract] for contract in analysis.contracts),
        ),
        ("Télétravail", REMOTE_LABELS[analysis.remote] if analysis.remote else None),
        ("Salaire", salary_label(analysis.salary) if analysis.salary else None),
        ("Date limite", _day(analysis.deadline)),
        (
            "Expérience demandée",
            f"{analysis.experience.years} an(s) minimum"
            if analysis.experience
            else None,
        ),
        ("Langues demandées", languages),
    ]
    return [(label, value) for label, value in facts if value]


def salary_label(salary: Salary) -> str:
    """ "45 000 – 55 000 EUR par an (période déduite du montant)"."""
    bounds = sorted({salary.minimum, salary.maximum})
    amount = " – ".join(f"{value:,.0f}".replace(",", " ") for value in bounds)
    period = SALARY_PERIOD_LABELS[salary.period]
    deduced = " (période déduite du montant)" if salary.period_deduced else ""
    return (
        " ".join(part for part in (amount, salary.currency, period) if part) + deduced
    )


@router.get("", response_class=HTMLResponse)
def import_page(request: Request, account: CurrentAccount) -> HTMLResponse:
    return _render(request, {})


@router.post("", response_class=HTMLResponse)
def import_posting(
    request: Request, account: CurrentAccount, lien: Annotated[str, Form()] = ""
) -> HTMLResponse:
    new_http: Callable[[], PublicHttp] = request.app.state.import_http
    http = new_http()
    try:
        sources = link_sources(build_sources(request.app.state.settings.sources, http))
        result = import_link(lien, http, sources, today=_today(request))
    finally:
        http.close()
    context: dict[str, object] = {"link": lien, "result": result}
    if result.preview is not None:
        context.update(_analysis(request, account, result.preview))
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
    context: dict[str, object] = {"link": lien, "result": ImportResult.ok(preview)}
    context.update(_analysis(request, account, preview))
    return _render(request, context)


@router.post("/resume", response_class=HTMLResponse)
def summarize_posting(
    request: Request,
    account: CurrentAccount,
    intitule: Annotated[str, Form()] = "",
    texte: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """The summary of the posting shown in the preview; one call to the language model, on demand (Q7)."""
    model: JsonModel = request.app.state.llm_model
    context = {"summary_result": summarize(intitule, texte, model)}
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(request, SUMMARY, context)
    return page(request, PAGE, active="offers", context=context)


def _analysis(
    request: Request, account: Account, preview: ImportPreview
) -> dict[str, object]:
    profile = profile_of(request, account)
    skills = account_skills(skill.content for skill in profile.skills)
    today = _today(request)
    analysis = analyze(preview.offer, skills, today=today)
    return {
        "analysis": analysis,
        "has_skills": bool(skills),
        "score": score(analysis, preview.offer, scoring_profile(profile), today=today),
    }


def _today(request: Request) -> date:
    today: Callable[[], date] = request.app.state.import_today
    return today()


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


def _day(day: date | None) -> str | None:
    return f"{day:%d/%m/%Y}" if day else None
