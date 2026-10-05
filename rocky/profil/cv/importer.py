"""Import of a CV PDF (decision D2, Q2, Q14, Q16, Q20, Q33): profile proposals, and the account's own template in
the CV's language (one imported CV per language, the English one optional).

Everything slow happens here, outside any database transaction: reading the page, one language model call,
deriving the template, rendering a side-by-side preview. What is kept is written to the files root as immutable
bundles: the proposals (and the photo found), and the template. The PDF itself is never kept (Q14); the preview is
shown once and never stored. The caller then records the template in the profile, in one short transaction.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from PIL import Image

from rocky.profil.cv.content import cv_content
from rocky.profil.cv.derived import derive, draw_derived
from rocky.profil.cv.pdf_page import PageError, read_page, render_page
from rocky.profil.cv.proposals import preview_profile
from rocky.profil.cv.semantics import (
    INSTRUCTIONS,
    SCHEMA,
    SemanticsError,
    block_roles,
    profile_answer,
    prompt,
)
from rocky.system.files import FileStore, StoredBundle
from rocky.system.llm import JsonModel, LlmUnavailableError
from rocky.system.render import RenderError, rasterize

LANGUAGES = {"fr": "français", "en": "anglais"}
IMPORTS = "imports"
TEMPLATES = "gabarits"
PROPOSALS_FILE = "propositions.json"
ANSWER_FILE = "reponse-du-modele.json"
# The SHA-256 of the texts sent to the model: the same CV imported again reuses its answer (decision D3, Q24).
TEXT_FILE = "texte-lu.sha256"
LANGUAGE_FILE = "langue.txt"
PHOTO_FILE = "photo.jpg"
MAX_BYTES = 10 * 1024 * 1024
PREVIEW_DPI = 150  # sharp on a high-density screen (preview about 500 CSS px wide)


class ImportRefusedError(Exception):
    """Nothing could be read from the file; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ImportedCv:
    proposals: StoredBundle  # propositions.json (+ photo.jpg when the CV has one)
    template: StoredBundle | None
    template_name: str
    language: str
    template_refusal: str | None  # why no template: the neutral one stays (Q20)
    warnings: tuple[str, ...]  # replaced fonts, rendering problems of the preview
    preview: (
        tuple[bytes, bytes] | None
    )  # PNG of the imported page and of its reproduction


def import_cv(
    pdf: bytes,
    *,
    model: JsonModel,
    files: FileStore,
    account_id: int,
    today: date,
    language: str = "fr",
) -> ImportedCv:
    """``language``: the language the CV is written in; its template serves the CVs in that language."""
    if language not in LANGUAGES:
        raise ImportRefusedError("Langue du CV inconnue.")
    if len(pdf) > MAX_BYTES:
        raise ImportRefusedError("Le PDF dépasse 10 Mo.")
    try:
        layout = read_page(pdf)
    except PageError as error:
        raise ImportRefusedError(error.reason) from error
    sent = prompt(layout.blocks)
    read = hashlib.sha256(sent.encode()).hexdigest().encode()
    earlier = files.find_bundle(account_id, IMPORTS, TEXT_FILE, read)
    try:
        answer = (
            json.loads(earlier[ANSWER_FILE])
            if earlier is not None and ANSWER_FILE in earlier
            else model.complete_json(INSTRUCTIONS, sent, SCHEMA)
        )
        proposals = profile_answer(answer)
    except (LlmUnavailableError, SemanticsError) as error:
        raise ImportRefusedError(error.reason) from error
    name = f"CV {LANGUAGES[language]} importé le {today.strftime('%d/%m/%Y')}"
    template: StoredBundle | None = None
    refusal: str | None = None
    warnings: list[str] = []
    preview: tuple[bytes, bytes] | None = None
    saved: dict[str, bytes] = {
        PROPOSALS_FILE: json.dumps(proposals, ensure_ascii=False, indent=1).encode(),
        # The model's whole answer (texts of the CV and their rubrics): a template can be derived again from it.
        ANSWER_FILE: json.dumps(answer, ensure_ascii=False, indent=1).encode(),
        LANGUAGE_FILE: language.encode(),
        TEXT_FILE: read,
    }
    try:
        roles = block_roles(answer, layout.blocks)
        derived = derive(pdf, layout, roles, name, language)
    except (SemanticsError, PageError) as error:
        refusal = error.reason
    else:
        template = files.put_bundle(account_id, TEMPLATES, derived.files)
        warnings += derived.warnings
        if derived.photo is not None:
            saved[PHOTO_FILE] = derived.photo.content
        try:
            rendered, _, problems = draw_derived(
                derived.files, cv_content(preview_profile(proposals), language, today)
            )
        except RenderError as error:
            warnings.append(f"Aperçu : {error.reason}")
        else:
            warnings += [f"Aperçu : {reason}" for reason in problems]
            preview = (
                _png(render_page(pdf, PREVIEW_DPI)),
                _png(rasterize(rendered.pdf, PREVIEW_DPI)[0]),
            )
    stored = files.put_bundle(account_id, IMPORTS, saved)
    return ImportedCv(
        proposals=stored,
        template=template,
        template_name=name,
        language=language,
        template_refusal=refusal,
        warnings=tuple(warnings),
        preview=preview,
    )


def read_proposals(
    files: FileStore, account_id: int, sha256: str
) -> tuple[Mapping[str, Any], bytes | None]:
    """The proposals of one import of this account, and the photo found in its CV."""
    if not sha256.isalnum():
        raise ImportRefusedError("Import introuvable.")
    bundle = files.read_bundle(f"comptes/{account_id}/{IMPORTS}/{sha256}", sha256)
    return json.loads(bundle[PROPOSALS_FILE]), bundle.get(PHOTO_FILE)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def import_language(files: FileStore, account_id: int, sha256: str) -> str:
    """The language of the CV of one import (« fr » for an import made before it was recorded)."""
    if not sha256.isalnum():
        raise ImportRefusedError("Import introuvable.")
    bundle = files.read_bundle(f"comptes/{account_id}/{IMPORTS}/{sha256}", sha256)
    return bundle.get(LANGUAGE_FILE, b"fr").decode()
