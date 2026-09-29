"""Import of a CV PDF (decision D2, Q2, Q14, Q16, Q20): profile proposals, and the account's own template.

Everything slow happens here, outside any database transaction: reading the page, one language model call,
deriving the template, rendering a side-by-side preview. What is kept is written to the files root as immutable
bundles: the proposals (and the photo found), and the template. The PDF itself is never kept (Q14); the preview is
shown once and never stored. The caller then records the template in the profile, in one short transaction.
"""

from __future__ import annotations

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
    Role,
    SemanticsError,
    block_roles,
    profile_answer,
    prompt,
    titles,
)
from rocky.system.files import FileStore, StoredBundle
from rocky.system.llm import JsonModel, LlmUnavailableError
from rocky.system.render import RenderError, rasterize

# Rubrics a user may keep as the imported CV wrote them, in the French CV.
KEEPABLE = {
    "hobbies": "Loisirs",
    "languages": "Langues",
    "transversal": "Compétences transversales",
    "groups": "Compétences techniques",
}
IMPORTS = "imports"
TEMPLATES = "gabarits"
PROPOSALS_FILE = "propositions.json"
ANSWER_FILE = "reponse-du-modele.json"
PHOTO_FILE = "photo.jpg"
MAX_BYTES = 10 * 1024 * 1024
PREVIEW_DPI = 70


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
    kept: frozenset[Role] = frozenset(),
) -> ImportedCv:
    if len(pdf) > MAX_BYTES:
        raise ImportRefusedError("Le PDF dépasse 10 Mo.")
    try:
        layout = read_page(pdf)
    except PageError as error:
        raise ImportRefusedError(error.reason) from error
    try:
        answer = model.complete_json(INSTRUCTIONS, prompt(layout.blocks), SCHEMA)
        proposals = profile_answer(answer)
    except (LlmUnavailableError, SemanticsError) as error:
        raise ImportRefusedError(error.reason) from error
    name = f"Gabarit importé le {today.strftime('%d/%m/%Y')}"
    template: StoredBundle | None = None
    refusal: str | None = None
    warnings: list[str] = []
    preview: tuple[bytes, bytes] | None = None
    saved: dict[str, bytes] = {
        PROPOSALS_FILE: json.dumps(proposals, ensure_ascii=False, indent=1).encode(),
        # The model's whole answer (texts of the CV and their rubrics): a template can be derived again from it.
        ANSWER_FILE: json.dumps(answer, ensure_ascii=False, indent=1).encode(),
    }
    try:
        roles = block_roles(answer, layout.blocks)
        derived = derive(pdf, layout, roles, name, titles(answer, layout.blocks), kept)
    except (SemanticsError, PageError) as error:
        refusal = error.reason
    else:
        template = files.put_bundle(account_id, TEMPLATES, derived.files)
        warnings += derived.warnings
        if derived.photo is not None:
            saved[PHOTO_FILE] = derived.photo.content
        try:
            rendered, _, problems = draw_derived(
                derived.files,
                cv_content(preview_profile(proposals), "fr", today),
                derived.photo,
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
