"""The screen « Traduire en anglais » of Profil & kit (decision D3, Q5, Q6, Q13, Q14, Q19): what is missing, one call
to the model on the user's gesture, a review field by field, the glossary.

Registered before the profile's own routes (``/profil/{key}`` would take ``/profil/traduction``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from rocky.profil.rules import ProfileInputError
from rocky.profil.sql import SqlProfileStore
from rocky.profil.translation import (
    Proposal,
    TranslationError,
    glossary_pairs,
    propose,
    protected_names,
    to_translate,
)
from rocky.profil.usecases import ProfileEditor
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.shell import page, wants_fragment

router = APIRouter(prefix="/profil")


@contextmanager
def _editor(request: Request, account: Account) -> Iterator[ProfileEditor]:
    """One use case, one transaction."""
    engine: Engine = request.app.state.engine
    clock: Callable[[], datetime] = request.app.state.auth.clock
    with engine.begin() as connection:
        yield ProfileEditor(
            SqlProfileStore(connection),
            clock=clock,
            account_id=account.id,
            email=account.email,
        )


def back_to(value: str) -> str:
    """Where « Revenir » leads: a path of Rocky only (never another site)."""
    return (
        value if value.startswith("/") and not value.startswith("//") else "/profil/kit"
    )


def _screen(
    request: Request,
    account: Account,
    retour: str,
    *,
    proposals: tuple[Proposal, ...] = (),
    error: str | None = None,
    message: str | None = None,
) -> Response:
    with _editor(request, account) as editor:
        profile = editor.profile()
        memory = editor.translation_memory()
        glossary = editor.glossary()
    missing, stale = to_translate(profile, memory)
    context: Mapping[str, object] = {
        "missing": missing,
        "stale": stale,
        "glossary": glossary,
        "proposals": proposals,
        "retour": back_to(retour),
        "error": error,
        "message": message,
    }
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(
            request, "profil/translation_body.html", dict(context)
        )
    return page(request, "profil/translation.html", active="profile", context=context)


@router.get("/traduction", response_class=HTMLResponse)
def translation_page(
    request: Request, account: CurrentAccount, retour: str = ""
) -> Response:
    return _screen(request, account, retour)


@router.post("/traduction", response_class=HTMLResponse)
def translate(
    request: Request,
    account: CurrentAccount,
    consentement: Annotated[str, Form()] = "",
    retour: Annotated[str, Form()] = "",
) -> Response:
    """One call to the model for the texts without English and those to review (Q13), after the user's consent."""
    if not consentement:
        return _screen(
            request,
            account,
            retour,
            error="Coche l'accord d'envoi de ces textes pour les faire traduire.",
        )
    with _editor(request, account) as editor:
        profile = editor.profile()
        memory = editor.translation_memory()
        glossary = editor.glossary()
    missing, stale = to_translate(profile, memory)
    if not missing and not stale:
        return _screen(request, account, retour, message="Rien à traduire.")
    try:
        proposals = propose(
            (*missing, *stale),
            memory=memory,
            pairs=glossary_pairs(profile, glossary),
            protected=protected_names(profile),
            model=request.app.state.llm_model,
        )
    except TranslationError as error:
        return _screen(request, account, retour, error=error.reason)
    return _screen(request, account, retour, proposals=proposals)


@router.post("/traduction/accepter", response_class=HTMLResponse)
def accept(
    request: Request,
    account: CurrentAccount,
    cle: Annotated[str, Form()],
    empreinte: Annotated[str, Form()],
    anglais: Annotated[str, Form()] = "",
    ou: Annotated[str, Form()] = "",
    retour: Annotated[str, Form()] = "",
) -> Response:
    """Write one accepted translation (one transaction per field, Q13)."""
    try:
        with _editor(request, account) as editor:
            editor.accept_translation(cle, empreinte, anglais)
    except ProfileInputError as error:
        return _row(
            request,
            cle,
            ou,
            error=str(error),
            english=anglais,
            retour=retour,
            empreinte=empreinte,
        )
    if not wants_fragment(request):
        return RedirectResponse(
            f"/profil/traduction?retour={back_to(retour)}", status_code=303
        )
    return _row(request, cle, ou, accepted=True)


@router.post("/traduction/ignorer", response_class=HTMLResponse)
def ignore(request: Request, account: CurrentAccount) -> Response:
    """Nothing is kept of an ignored proposal (Q13): its row just goes."""
    if not wants_fragment(request):
        return RedirectResponse("/profil/traduction", status_code=303)
    return HTMLResponse("")


def _row(
    request: Request,
    key: str,
    where: str,
    *,
    accepted: bool = False,
    error: str | None = None,
    english: str = "",
    retour: str = "",
    empreinte: str = "",
) -> Response:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "profil/translation_row.html",
        {
            "key": key,
            "where": where,
            "accepted": accepted,
            "error": error,
            "english": english,
            "retour": back_to(retour),
            "empreinte": empreinte,
        },
    )


@router.post("/glossaire", response_class=HTMLResponse)
def add_term(
    request: Request,
    account: CurrentAccount,
    fr: Annotated[str, Form()] = "",
    en: Annotated[str, Form()] = "",
    retour: Annotated[str, Form()] = "",
) -> Response:
    try:
        with _editor(request, account) as editor:
            editor.save_glossary_term(fr, en)
    except ProfileInputError as error:
        return _screen(request, account, retour, error=str(error))
    return _screen(
        request, account, retour, message=f"« {fr.strip()} » ajouté au glossaire."
    )


@router.post("/glossaire/{term_id}/supprimer", response_class=HTMLResponse)
def delete_term(
    request: Request,
    account: CurrentAccount,
    term_id: int,
    retour: Annotated[str, Form()] = "",
) -> Response:
    with _editor(request, account) as editor:
        if not editor.delete_glossary_term(term_id):
            return Response(status_code=404)
    return _screen(request, account, retour)


def to_review(request: Request, account: Account) -> tuple[str, ...]:
    """The English texts whose French changed since their translation (Q14), for the other modules' screens: the
    English CV warns of them, never refuses."""
    with _editor(request, account) as editor:
        profile = editor.profile()
        memory = editor.translation_memory()
    _, stale = to_translate(profile, memory)
    return tuple(segment.where for segment in stale)
