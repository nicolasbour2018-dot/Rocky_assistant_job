"""The screen « Traduire en anglais » of Profil & kit (decision D3, Q5, Q6, Q13, Q14, Q19): what is missing, one call
to the model on the user's gesture, a review field by field, the glossary.

Registered before the profile's own routes (``/profil/{key}`` would take ``/profil/traduction``).
"""

from __future__ import annotations

import base64
import io
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image
from sqlalchemy import Engine

from rocky.profil.cv.content import cv_content
from rocky.profil.cv.derived import (
    KeptText,
    draw_derived,
    english_template,
    kept_texts,
)
from rocky.profil.cv.importer import PREVIEW_DPI, TEMPLATES
from rocky.profil.cv.rendering import CvRefusedError
from rocky.profil.model import CvTemplateRecord
from rocky.profil.rules import ProfileInputError, text_sha256
from rocky.profil.sql import SqlProfileStore
from rocky.profil.translation import (
    Proposal,
    Segment,
    TranslationError,
    glossary_pairs,
    propose,
    protected_names,
    to_translate,
)
from rocky.profil.usecases import ProfileEditor
from rocky.system.auth.model import Account
from rocky.system.auth.rules import safe_next_path
from rocky.system.auth.web import CurrentAccount
from rocky.system.clock import paris_day
from rocky.system.config import CallType
from rocky.system.files import FileError, FileStore
from rocky.system.llm.calls import model_for
from rocky.system.render import RenderError, rasterize
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


def html_id(key: str) -> str:
    """A key made fit for an HTML id and a CSS selector (« label:Stack technique » → « label-Stack-technique »)."""
    return re.sub(r"[^\w-]+", "-", key).strip("-")


def back_to(value: str) -> str:
    """Where « Revenir » leads: a path of Rocky only (never another site, step H5)."""
    return safe_next_path(value, default="/profil/kit")


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
            model=model_for(request, CallType.TRANSLATION, account),
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
        return review_row(
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
    return review_row(request, cle, ou, accepted=True)


@router.post("/traduction/ignorer", response_class=HTMLResponse)
def ignore(request: Request, account: CurrentAccount) -> Response:
    """Nothing is kept of an ignored proposal (Q13): its row just goes."""
    if not wants_fragment(request):
        return RedirectResponse("/profil/traduction", status_code=303)
    return HTMLResponse("")


def review_row(
    request: Request,
    key: str,
    where: str,
    *,
    accepted: bool = False,
    error: str | None = None,
    english: str = "",
    retour: str = "",
    empreinte: str = "",
    accept_url: str = "/profil/traduction/accepter",
    source: str = "",
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
            "accept_url": accept_url,
            "source": source,
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


# « Préparer mon CV anglais » (decision D3, Q8, Q16–Q20): the English version of the imported French CV.


@dataclass(frozen=True)
class EnglishState:
    """Where the English version of the account's French template stands."""

    french: CvTemplateRecord | None
    refusal: (
        str | None
    )  # why it cannot be prepared (no French template, one to import again)
    texts: tuple[KeptText, ...] = ()
    validated: Mapping[str, str] = field(default_factory=dict)  # kept text id → English
    files: Mapping[str, bytes] = field(default_factory=dict)

    @property
    def to_translate(self) -> tuple[KeptText, ...]:
        return tuple(text for text in self.texts if text.id not in self.validated)


def _english_state(request: Request, account: Account) -> EnglishState:
    with _editor(request, account) as editor:
        french = editor.active_cv_template("fr")
        memory = editor.translation_memory()
    if french is None:
        return EnglishState(
            None,
            "Ton CV anglais se prépare à partir de ton CV français importé : importe-le d'abord dans Profil & kit.",
        )
    try:
        files = _file_store(request).read_bundle(french.path, french.sha256)
        texts = kept_texts(files)
    except (CvRefusedError, FileError) as error:
        reason = (
            " ".join(error.reasons)
            if isinstance(error, CvRefusedError)
            else error.reason
        )
        return EnglishState(french, reason)
    validated = {
        text.id: memory[text_sha256(text.text)].translation
        for text in texts
        if text_sha256(text.text) in memory
    }
    return EnglishState(french, None, texts, validated, files)


def _file_store(request: Request) -> FileStore:
    root = request.app.state.settings.storage_root
    if root is None:
        raise FileError(
            "Le stockage des fichiers n'est pas configuré (ROCKY_STORAGE_ROOT)."
        )
    return FileStore(root)


def _english_screen(
    request: Request,
    account: Account,
    *,
    proposals: tuple[Proposal, ...] = (),
    error: str | None = None,
    message: str | None = None,
) -> Response:
    state = _english_state(request, account)
    preview: str | None = None
    problems: tuple[str, ...] = ()
    with _editor(request, account) as editor:
        profile = editor.profile()
        memory = editor.translation_memory()
        english = editor.active_cv_template("en")
    missing_fields, _ = to_translate(profile, memory)
    preview_refusal: tuple[str, ...] = ()
    if state.refusal is None and state.french is not None:
        clock: Callable[[], datetime] = request.app.state.auth.clock
        files = english_template(
            state.files, state.validated, state.french.sha256, partial=True
        )
        try:
            rendered, _, problems = draw_derived(
                files, cv_content(profile, "en", paris_day(clock()))
            )
            preview = base64.b64encode(
                _png(rasterize(rendered.pdf, PREVIEW_DPI)[0])
            ).decode()
        except (RenderError, CvRefusedError) as refused:
            # The screen stays usable: the preview says why it is missing (step H1).
            preview_refusal = refused.lines
    context: Mapping[str, object] = {
        "state": state,
        "proposals": proposals,
        "missing_fields": missing_fields,
        "preview": preview,
        "preview_refusal": preview_refusal,
        "problems": problems,
        "outdated": english is not None
        and english.source_sha256 is not None
        and state.french is not None
        and english.source_sha256 != state.french.sha256,
        "english": english,
        "error": error,
        "message": message,
    }
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(
            request, "profil/english_body.html", dict(context)
        )
    return page(request, "profil/english.html", active="profile", context=context)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return bytes(buffer.getvalue())


@router.get("/cv-anglais", response_class=HTMLResponse)
def english_page(request: Request, account: CurrentAccount) -> Response:
    return _english_screen(request, account)


@router.post("/cv-anglais", response_class=HTMLResponse)
def translate_cv(
    request: Request,
    account: CurrentAccount,
    consentement: Annotated[str, Form()] = "",
) -> Response:
    """One call to the model for the texts of the imported CV not validated yet (Q18), after the user's consent."""
    if not consentement:
        return _english_screen(
            request,
            account,
            error="Coche l'accord d'envoi de ces textes pour les faire traduire.",
        )
    state = _english_state(request, account)
    if state.refusal is not None:
        return _english_screen(request, account, error=state.refusal)
    with _editor(request, account) as editor:
        profile = editor.profile()
        memory = editor.translation_memory()
        glossary = editor.glossary()
    segments = [
        Segment(text.id, text.where, text.text, None) for text in state.to_translate
    ]
    if not segments:
        return _english_screen(
            request, account, message="Tous les textes sont déjà traduits."
        )
    try:
        proposals = propose(
            segments,
            memory=memory,
            pairs=glossary_pairs(profile, glossary),
            protected=protected_names(profile),
            model=model_for(request, CallType.TRANSLATION, account),
        )
    except TranslationError as error:
        return _english_screen(request, account, error=error.reason)
    return _english_screen(request, account, proposals=proposals)


@router.post("/cv-anglais/accepter", response_class=HTMLResponse)
def accept_cv_text(
    request: Request,
    account: CurrentAccount,
    cle: Annotated[str, Form()],
    empreinte: Annotated[str, Form()],
    anglais: Annotated[str, Form()] = "",
    ou: Annotated[str, Form()] = "",
) -> Response:
    """Keep one validated text of the English version (in the memory: nothing else is stored before the whole CV)."""
    state = _english_state(request, account)
    text = next((t for t in state.texts if t.id == cle), None)
    try:
        if text is None or text_sha256(text.text) != empreinte:
            raise ProfileInputError(
                "Ce texte n'est plus dans ton CV français : recharge la page."
            )
        with _editor(request, account) as editor:
            editor.validate_translation(text.text, anglais)
    except ProfileInputError as error:
        return review_row(
            request,
            cle,
            ou,
            error=str(error),
            english=anglais,
            empreinte=empreinte,
            accept_url="/profil/cv-anglais/accepter",
        )
    if not wants_fragment(request):
        return RedirectResponse("/profil/cv-anglais", status_code=303)
    return review_row(
        request, cle, ou, accepted=True, accept_url="/profil/cv-anglais/accepter"
    )


@router.post("/cv-anglais/modifier", response_class=HTMLResponse)
def edit_cv_text(
    request: Request, account: CurrentAccount, cle: Annotated[str, Form()]
) -> Response:
    """Reopen a validated text of the English version, its English ready to correct (too long for its place)."""
    state = _english_state(request, account)
    text = next((t for t in state.texts if t.id == cle), None)
    if text is None or cle not in state.validated:
        return _english_screen(
            request, account, error="Ce texte n'est plus dans ton CV français."
        )
    if not wants_fragment(request):
        segment = Segment(text.id, text.where, text.text, None)
        proposal = Proposal(segment, state.validated[cle], from_memory=True)
        return _english_screen(request, account, proposals=(proposal,))
    return review_row(
        request,
        text.id,
        text.where,
        english=state.validated[cle],
        empreinte=text_sha256(text.text),
        accept_url="/profil/cv-anglais/accepter",
        source=text.text,
    )


@router.post("/cv-anglais/creer", response_class=HTMLResponse)
def create_english_cv(request: Request, account: CurrentAccount) -> Response:
    """The English template, once every text is validated (Q18): an immutable bundle, recorded and made active (Q17)."""
    state = _english_state(request, account)
    if state.refusal is not None or state.french is None:
        return _english_screen(request, account, error=state.refusal)
    if state.to_translate:
        return _english_screen(
            request,
            account,
            error=f"Il reste {len(state.to_translate)} texte(s) à valider avant de créer ton CV anglais.",
        )
    files = english_template(state.files, state.validated, state.french.sha256)
    stored = _file_store(request).put_bundle(account.id, TEMPLATES, files)
    with _editor(request, account) as editor:
        template_id = editor.record_cv_template(
            stored.path,
            stored.sha256,
            f"{state.french.name} — version anglaise",
            "en",
            source_sha256=state.french.sha256,
        )
        editor.activate_cv_template(template_id, "en")
    return _english_screen(
        request,
        account,
        message="Ton CV anglais est prêt : il sert désormais à tous tes CV en anglais.",
    )


def english_cv_outdated(request: Request, account: Account) -> bool:
    """The active English template was translated from another French one than the active one (Q19)."""
    with _editor(request, account) as editor:
        french = editor.active_cv_template("fr")
        english = editor.active_cv_template("en")
    return (
        english is not None
        and english.source_sha256 is not None
        and (french is None or english.source_sha256 != french.sha256)
    )
