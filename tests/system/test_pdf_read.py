"""Three independent PDF readers; failures kept with their reason (decision D2, Q12)."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from rocky.system import pdf_read
from rocky.system.pdf_read import PdfUnreadableError, read_pdf


def _blank_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_every_reader_reads_in_a_fixed_order() -> None:
    readings = read_pdf(_blank_pdf(1))

    assert [reading.reader for reading in readings] == [
        "pypdf",
        "pdfminer.six",
        "pypdfium2",
    ]
    assert all(reading.text == "" and reading.error is None for reading in readings)


def test_a_file_that_is_not_a_pdf_is_refused_with_its_reason() -> None:
    with pytest.raises(PdfUnreadableError, match="pas un PDF lisible"):
        read_pdf(b"hello")


def test_too_many_pages_are_refused() -> None:
    with pytest.raises(PdfUnreadableError, match="6 pages"):
        read_pdf(_blank_pdf(6))


def test_a_failing_reader_keeps_its_reason_and_the_others_still_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(content: bytes) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        pdf_read,
        "READERS",
        (("broken", broken), *pdf_read.READERS[1:]),
    )

    readings = read_pdf(_blank_pdf(1))

    assert readings[0].error == "RuntimeError: boom"
    assert [reading.error for reading in readings[1:]] == [None, None]
