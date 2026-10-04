"""Paragraphs of a Word document (DOCX), read with the standard library only.

Decision ``docs/decisions/D4-lettre-message.md`` (Q13): a letter worked on elsewhere is imported from its file. A DOCX
is a zip archive whose text is in ``word/document.xml``; nothing else of it is read. A document type declaration is
refused before parsing (no XML entity is ever expanded), and so are an archive or a text too large for a letter.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024  # the file as uploaded
MAX_XML_BYTES = 10 * 1024 * 1024  # ``word/document.xml`` once uncompressed
DOCUMENT = "word/document.xml"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxUnreadableError(Exception):
    """Not a DOCX, or one Rocky refuses to read; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_docx(content: bytes) -> bool:
    return content.startswith(b"PK")


def docx_paragraphs(content: bytes) -> tuple[str, ...]:
    """The paragraphs of the document body, in order, without the empty ones; a tab is a space, a line break a
    space too (a letter's paragraph is one block of text)."""
    if len(content) > MAX_BYTES:
        raise DocxUnreadableError("Le fichier dépasse 5 Mo.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise DocxUnreadableError(
            "Ce fichier n'est pas un document Word (DOCX)."
        ) from error
    with archive:
        try:
            info = archive.getinfo(DOCUMENT)
        except KeyError as error:
            raise DocxUnreadableError(
                "Ce fichier n'est pas un document Word (DOCX) : son texte est introuvable."
            ) from error
        if info.file_size > MAX_XML_BYTES:
            raise DocxUnreadableError("Le texte de ce document est trop volumineux.")
        xml = archive.read(info)
    declarations = xml.upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise DocxUnreadableError(
            "Ce document Word contient une déclaration que Rocky ne lit pas."
        )
    try:
        # Safe here: a document type or entity declaration is refused above, so nothing is ever expanded.
        root = ElementTree.fromstring(xml)  # noqa: S314
    except ElementTree.ParseError as error:
        raise DocxUnreadableError(
            "Le texte de ce document Word est illisible."
        ) from error
    body = root.find(f"{_W}body")
    if body is None:
        return ()
    paragraphs = []
    for paragraph in body.iter(f"{_W}p"):
        text = "".join(_runs(paragraph))
        cleaned = " ".join(text.split())
        if cleaned:
            paragraphs.append(cleaned)
    return tuple(paragraphs)


def _runs(paragraph: ElementTree.Element) -> list[str]:
    parts = []
    for element in paragraph.iter():
        if element.tag == f"{_W}t" and element.text:
            parts.append(element.text)
        elif element.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
            parts.append(" ")
    return parts
