"""Text of a PDF as three independent readers see it: pypdf, pdfminer.six, pypdfium2.

Decision ``docs/decisions/D2-cv-rendu.md`` (Q12): recruiters' tools read a CV with one parser or another; a fact
read by every parser is robust, a fact read by some only is a warning. No OCR, no model: a page without a text
layer reads empty, and says so. A reader that fails gives its reason; it never hides the others.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass

import pypdfium2
from pdfminer.high_level import extract_text as pdfminer_text
from pypdf import PdfReader

logger = logging.getLogger(__name__)

MAX_PAGES = 5  # a CV; more is refused before any reader runs


@dataclass(frozen=True)
class Reading:
    reader: str
    text: str  # empty when the reader failed
    error: str | None = None


class PdfUnreadableError(Exception):
    """Not a PDF, encrypted, or too long; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def read_pdf(content: bytes) -> tuple[Reading, ...]:
    """One reading per reader, in a fixed order."""
    pages = _page_count(content)
    if pages > MAX_PAGES:
        raise PdfUnreadableError(
            f"Le PDF a {pages} pages : un CV en compte {MAX_PAGES} au plus."
        )
    return tuple(_read(name, reader, content) for name, reader in READERS)


def _page_count(content: bytes) -> int:
    try:
        document = pypdfium2.PdfDocument(content)
    except pypdfium2.PdfiumError as error:
        raise PdfUnreadableError(
            "Ce fichier n'est pas un PDF lisible (ou il est protégé par un mot de passe)."
        ) from error
    try:
        return len(document)
    finally:
        document.close()


def _read(name: str, reader: Callable[[bytes], str], content: bytes) -> Reading:
    try:
        return Reading(reader=name, text=_normalise(reader(content)))
    # Each parser has its own errors: whichever it raises, the reason is kept and shown.
    except Exception as error:
        logger.warning("PDF reader %s failed: %s", name, type(error).__name__)
        return Reading(
            reader=name, text="", error=f"{type(error).__name__}: {error}"[:200]
        )


def _pypdf(content: bytes) -> str:
    return "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
    )


def _pdfminer(content: bytes) -> str:
    return str(pdfminer_text(io.BytesIO(content)))


def _pdfium(content: bytes) -> str:
    document = pypdfium2.PdfDocument(content)
    try:
        texts = []
        for page in document:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        return "\n".join(texts)
    finally:
        document.close()


def _normalise(text: str) -> str:
    """Line ends and form feeds unified, trailing spaces dropped; the words themselves untouched."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    return "\n".join(line.rstrip() for line in lines.split("\n")).strip()


READERS: tuple[tuple[str, Callable[[bytes], str]], ...] = (
    ("pypdf", _pypdf),
    ("pdfminer.six", _pdfminer),
    ("pypdfium2", _pdfium),
)
