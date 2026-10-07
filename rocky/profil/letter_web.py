"""The screen « Ma lettre de motivation » of Profil & kit (decision D4, Q6, Q9, Q13, Q17): import a letter worked on
elsewhere, review its paragraphs, edit them, prepare its English version.

Registered before the profile's own routes (``/profil/{key}`` would take ``/profil/lettre``). ``generic_letters`` is
what the applications read of it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from rocky.profil.letter import (
    COMPANY,
    JOB,
    SET_ASIDE,
    TRANSLATION_INSTRUCTIONS,
    LetterImportError,
    SplitLetter,
    SplitParagraph,
    checked_text,
    english_letter,
    letter_segments,
    letter_text,
    make_letter,
    split_letter,
)
from rocky.profil.model import (
    LETTER_ROLE_LABELS,
    LetterOrigin,
    LetterRole,
    StoredLetter,
)
from rocky.profil.rules import ProfileInputError
from rocky.profil.sql import SqlProfileStore
from rocky.profil.translation import (
    Proposal,
    Segment,
    TranslationError,
    glossary_pairs,
    propose,
    protected_names,
)
from rocky.profil.translation_web import review_row
from rocky.profil.usecases import ProfileEditor
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.config import CallType
from rocky.system.docx_read import MAX_BYTES
from rocky.system.llm.calls import model_for
from rocky.system.shell import is_htmx, page, wants_fragment

router = APIRouter(prefix="/profil")
LETTER_PATH = "/profil/lettre"
ACCEPT_URL = "/profil/lettre/anglais/accepter"
SET_ASIDE_CODE = "ecarter"  # a row of the review left out of the letter


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


@dataclass(frozen=True)
class GenericLetters:
    """The versions in force of the account's generic letter (what the applications use)."""

    fr: StoredLetter | None
    en: StoredLetter | None

    @property
    def english_outdated(self) -> bool:
        """The English letter was translated from another French one than the one in force (Q17)."""
        return (
            self.en is not None
            and self.en.source_sha256 is not None
            and self.fr is not None
            and self.en.source_sha256 != self.fr.sha256
        )

    def of(self, language: str) -> StoredLetter | None:
        return self.en if language == "en" else self.fr


def generic_letters(request: Request, account: Account) -> GenericLetters:
    """For the other modules' screens (the application's letter, D4)."""
    with _editor(request, account) as editor:
        return GenericLetters(editor.generic_letter("fr"), editor.generic_letter("en"))


@dataclass(frozen=True)
class ReviewRow:
    role: str  # a ``LetterRole`` value or ``SET_ASIDE_CODE``
    text: str
    note: str = (
        ""  # why it is set aside, or that it is not word for word in the letter read
    )


@dataclass(frozen=True)
class Review:
    """The form of a letter to save: a cut proposed by the model (Q13), or the letter in force to edit."""

    language: str
    origin: LetterOrigin
    rows: tuple[ReviewRow, ...]
    replaced: tuple[tuple[str, str], ...] = ()  # (variable, text of the letter read)


@dataclass(frozen=True)
class EnglishLetterState:
    segments: tuple[Segment, ...] = ()
    validated: Mapping[str, str] = field(default_factory=dict)  # segment key → English

    @property
    def to_translate(self) -> tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.key not in self.validated)


def _english_state(
    letters: GenericLetters, editor: ProfileEditor
) -> EnglishLetterState:
    if letters.fr is None:
        return EnglishLetterState()
    memory = editor.translation_memory()
    segments = letter_segments(letters.fr.letter)
    return EnglishLetterState(
        segments,
        {
            s.key: memory[s.source_sha256].translation
            for s in segments
            if s.source_sha256 in memory
        },
    )


def _screen(
    request: Request,
    account: Account,
    *,
    review: Review | None = None,
    proposals: tuple[Proposal, ...] = (),
    error: str | None = None,
    message: str | None = None,
    status_code: int = 200,
) -> Response:
    with _editor(request, account) as editor:
        letters = GenericLetters(
            editor.generic_letter("fr"), editor.generic_letter("en")
        )
        english = _english_state(letters, editor)
    context: Mapping[str, object] = {
        "letters": letters,
        "english": english,
        "review": review,
        "proposals": proposals,
        "error": error,
        "message": message,
        "role_labels": LETTER_ROLE_LABELS,
        "roles": list(LetterRole),
        "set_aside_code": SET_ASIDE_CODE,
        "accept_url": ACCEPT_URL,
        "max_mb": MAX_BYTES // (1024 * 1024),
        "variables": (JOB, COMPANY),
    }
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(
            request, "profil/letter_body.html", dict(context), status_code=status_code
        )
    return page(
        request,
        "profil/letter.html",
        active="profile",
        status_code=status_code,
        context=context,
    )


def _refused(
    request: Request, account: Account, reason: str, review: Review | None = None
) -> Response:
    # HTMX does not swap 4xx answers: a form error it asked for comes back as 200.
    return _screen(
        request,
        account,
        review=review,
        error=reason,
        status_code=200 if is_htmx(request) else 400,
    )


@router.get("/lettre", response_class=HTMLResponse)
def letter_page(
    request: Request, account: CurrentAccount, modifier: str = ""
) -> Response:
    """The letters in force; ``modifier=fr|en`` opens one to edit."""
    review = None
    if modifier in ("fr", "en"):
        with _editor(request, account) as editor:
            stored = editor.generic_letter(modifier)
        if stored is not None:
            review = Review(
                modifier,
                LetterOrigin.EDIT,
                tuple(
                    ReviewRow(p.role.value, p.text) for p in stored.letter.paragraphs
                ),
            )
    return _screen(request, account, review=review)


@router.post("/lettre/importer", response_class=HTMLResponse)
def import_letter(
    request: Request,
    account: CurrentAccount,
    fichier: Annotated[UploadFile | None, File()] = None,
    texte: Annotated[str, Form()] = "",
    langue: Annotated[str, Form()] = "fr",
    consentement: Annotated[str, Form()] = "",
) -> Response:
    """Read the letter (a DOCX, a PDF or a pasted text), then one call to the model to cut it (Q13)."""
    if not consentement:
        return _refused(
            request,
            account,
            "Coche l'accord d'envoi du texte de ta lettre pour l'importer.",
        )
    content = fichier.file.read(MAX_BYTES + 1) if fichier is not None else b""
    try:
        if content:
            if len(content) > MAX_BYTES:
                raise LetterImportError(
                    f"Le fichier dépasse {MAX_BYTES // (1024 * 1024)} Mo."
                )
            text = letter_text(content)
        elif texte.strip():
            text = checked_text(texte)
        else:
            raise LetterImportError(
                "Choisis le fichier de ta lettre (DOCX ou PDF), ou colle son texte."
            )
        split = split_letter(text, model_for(request, CallType.LETTER, account))
    except LetterImportError as error:
        return _refused(request, account, error.reason)
    return _screen(
        request,
        account,
        review=_review_of(split, "en" if langue == "en" else "fr"),
    )


def _review_of(split: SplitLetter, language: str) -> Review:
    def row(paragraph: SplitParagraph) -> ReviewRow:
        if paragraph.set_aside:
            return ReviewRow(
                SET_ASIDE_CODE,
                paragraph.text,
                f"Écarté : {SET_ASIDE[paragraph.role].lower()}, écrit par Rocky dans chaque lettre.",
            )
        note = (
            ""
            if paragraph.verbatim
            else "Ce paragraphe n'est pas mot pour mot dans ta lettre : vérifie-le."
        )
        return ReviewRow(paragraph.role, paragraph.text, note)

    replaced = tuple(
        (variable, original)
        for variable, original in ((JOB, split.job_title), (COMPANY, split.company))
        if original
    )
    return Review(
        language,
        LetterOrigin.IMPORT,
        tuple(row(p) for p in split.paragraphs),
        replaced,
    )


@router.post("/lettre/enregistrer", response_class=HTMLResponse)
def save_letter(
    request: Request,
    account: CurrentAccount,
    langue: Annotated[str, Form()] = "fr",
    origine: Annotated[str, Form()] = "edit",
    role: Annotated[list[str] | None, Form()] = None,
    texte: Annotated[list[str] | None, Form()] = None,
) -> Response:
    """Save the reviewed letter as the version in force of its language; the rows set aside are left out."""
    roles, texts = role or [], texte or []
    origin = LetterOrigin.IMPORT if origine == "import" else LetterOrigin.EDIT
    rows = tuple(ReviewRow(r, t) for r, t in zip(roles, texts, strict=False))
    language = "en" if langue == "en" else "fr"
    try:
        letter = make_letter(
            language, [(r.role, r.text) for r in rows if r.role != SET_ASIDE_CODE]
        )
        with _editor(request, account) as editor:
            current = editor.generic_letter(language)
            # An English letter edited by hand keeps the French it was translated from (Q17).
            source = (
                current.source_sha256
                if current is not None and origin is LetterOrigin.EDIT
                else None
            )
            editor.save_generic_letter(letter, origin, source)
    except ProfileInputError as error:
        return _refused(
            request, account, str(error), review=Review(language, origin, rows)
        )
    if not wants_fragment(request):
        return RedirectResponse(LETTER_PATH, status_code=303)
    return _screen(request, account, message="Ta lettre est enregistrée.")


# English letter (Q9): one call to the model for the paragraphs not validated yet, a review paragraph by paragraph,
# then the letter once every paragraph is validated.


@router.post("/lettre/anglais", response_class=HTMLResponse)
def translate_letter(
    request: Request,
    account: CurrentAccount,
    consentement: Annotated[str, Form()] = "",
) -> Response:
    if not consentement:
        return _refused(
            request,
            account,
            "Coche l'accord d'envoi de ces textes pour les faire traduire.",
        )
    with _editor(request, account) as editor:
        letters = GenericLetters(
            editor.generic_letter("fr"), editor.generic_letter("en")
        )
        state = _english_state(letters, editor)
        profile = editor.profile()
        glossary = editor.glossary()
        memory = editor.translation_memory()
    if letters.fr is None:
        return _refused(request, account, "Importe d'abord ta lettre en français.")
    if not state.to_translate:
        return _screen(
            request, account, message="Tous les paragraphes sont déjà traduits."
        )
    try:
        proposals = propose(
            state.to_translate,
            memory=memory,
            pairs=glossary_pairs(profile, glossary),
            protected=(*protected_names(profile), JOB, COMPANY),
            model=model_for(request, CallType.LETTER, account),
            instructions=TRANSLATION_INSTRUCTIONS,
        )
    except TranslationError as error:
        return _refused(request, account, error.reason)
    return _screen(request, account, proposals=proposals)


@router.post("/lettre/anglais/accepter", response_class=HTMLResponse)
def accept_paragraph(
    request: Request,
    account: CurrentAccount,
    cle: Annotated[str, Form()],
    empreinte: Annotated[str, Form()],
    anglais: Annotated[str, Form()] = "",
    ou: Annotated[str, Form()] = "",
) -> Response:
    """Keep one validated paragraph in the translation memory; the letter is written once all are (Q9)."""
    try:
        with _editor(request, account) as editor:
            french = editor.generic_letter("fr")
            segments = () if french is None else letter_segments(french.letter)
            segment = next((s for s in segments if s.key == cle), None)
            if segment is None or segment.source_sha256 != empreinte:
                raise ProfileInputError(
                    "Ce paragraphe n'est plus dans ta lettre française : recharge la page."
                )
            editor.validate_translation(segment.source, anglais)
    except ProfileInputError as error:
        return review_row(
            request,
            cle,
            ou,
            error=str(error),
            english=anglais,
            empreinte=empreinte,
            accept_url=ACCEPT_URL,
        )
    if not wants_fragment(request):
        return RedirectResponse(LETTER_PATH, status_code=303)
    return review_row(request, cle, ou, accepted=True, accept_url=ACCEPT_URL)


@router.post("/lettre/anglais/creer", response_class=HTMLResponse)
def create_english_letter(request: Request, account: CurrentAccount) -> Response:
    with _editor(request, account) as editor:
        letters = GenericLetters(
            editor.generic_letter("fr"), editor.generic_letter("en")
        )
        state = _english_state(letters, editor)
        if letters.fr is None:
            error = "Importe d'abord ta lettre en français."
        elif state.to_translate:
            left = len(state.to_translate)
            error = f"Il reste {left} paragraphe{'s' if left > 1 else ''} à valider avant de créer ta lettre anglaise."
        else:
            editor.save_generic_letter(
                english_letter(letters.fr.letter, state.validated),
                LetterOrigin.TRANSLATION,
                letters.fr.sha256,
            )
            error = None
    if error is not None:
        return _refused(request, account, error)
    if not wants_fragment(request):
        return RedirectResponse(LETTER_PATH, status_code=303)
    return _screen(request, account, message="Ta lettre anglaise est prête.")
