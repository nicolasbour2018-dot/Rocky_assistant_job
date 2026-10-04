"""Paragraphs of a DOCX read with the standard library (decision D4, Q13)."""

from __future__ import annotations

import io
import zipfile

import pytest

from rocky.system.docx_read import (
    DOCUMENT,
    MAX_BYTES,
    DocxUnreadableError,
    docx_paragraphs,
    is_docx,
)

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(body: str, *, prolog: str = "", name: str = DOCUMENT) -> bytes:
    """A minimal Word document whose body is ``body`` (WordprocessingML)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            name,
            f'<?xml version="1.0"?>{prolog}<w:document {W}><w:body>{body}</w:body></w:document>',
        )
    return buffer.getvalue()


def paragraph(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def test_the_paragraphs_come_in_order_without_the_empty_ones() -> None:
    content = docx(
        paragraph(run("Madame, Monsieur,"))
        + paragraph()
        + paragraph(
            run("Data "), run("analyste"), "<w:r><w:tab/></w:r>", run("depuis 2024.")
        )
        + paragraph(run("Ligne un"), "<w:r><w:br/></w:r>", run("ligne deux"))
    )

    assert is_docx(content)
    assert docx_paragraphs(content) == (
        "Madame, Monsieur,",
        "Data analyste depuis 2024.",
        "Ligne un ligne deux",
    )


def test_a_document_type_declaration_is_refused_before_parsing() -> None:
    content = docx(
        paragraph(run("&a;")),
        prolog='<!DOCTYPE w:document [<!ENTITY a "aaaaaaaaaa">]>',
    )

    with pytest.raises(DocxUnreadableError, match="déclaration"):
        docx_paragraphs(content)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"PK not a zip at all", "pas un document Word"),
        (docx(paragraph(run("x")), name="word/other.xml"), "texte est introuvable"),
        (b"PK" + b"0" * (MAX_BYTES + 1), "dépasse 5 Mo"),
    ],
)
def test_what_is_not_a_readable_docx_says_why(content: bytes, reason: str) -> None:
    with pytest.raises(DocxUnreadableError, match=reason):
        docx_paragraphs(content)
