from datetime import date

import pytest

from dashboard.rocky.config import Settings
from dashboard.rocky.letters import (
    LetterVariables,
    create_docx,
    create_pdf,
    parse_letter_sections,
    render_letter,
)


def variables():
    return LetterVariables(
        job_title="Data Analyst",
        company_name="Entreprise Exemple",
        company_paragraph=(
            "Je suis particulièrement intéressé par les missions d'analyse "
            "proposées par Entreprise Exemple."
        ),
        company_address="10 rue Exemple\n75000 Paris",
        city="Paris",
        sender_name="Camille Exemple",
        sender_address="1 rue Exemple, 75000 Paris",
        sender_phone="0102030405",
        sender_email="camille@example.test",
        letter_date=date(2026, 8, 7),
    )


def test_letter_replaces_only_declared_variables():
    text = render_letter(Settings(), variables())
    assert "Data Analyst" in text
    assert "Entreprise Exemple" in text
    assert "7 août 2026" in text
    assert "{" not in text
    assert "Après plusieurs expériences professionnelles" in text


def test_docx_and_pdf_are_created(tmp_path):
    docx_module = pytest.importorskip("docx")
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    text = render_letter(Settings(), variables())
    docx_path = tmp_path / "lettre.docx"
    pdf_path = tmp_path / "lettre.pdf"
    create_docx(docx_path, variables(), text)
    create_pdf(pdf_path, variables(), text)
    assert docx_path.stat().st_size > 1_000
    assert pdf_path.read_bytes().startswith(b"%PDF")
    document = docx_module.Document(docx_path)
    docx_text = "\n".join(p.text for p in document.paragraphs)
    assert "Entreprise Exemple" in docx_text
    assert "{" not in docx_text
    reader = pypdf.PdfReader(pdf_path)
    assert len(reader.pages) == 1
    assert "Entreprise Exemple" in reader.pages[0].extract_text()


def test_edited_letter_is_used_in_preview_and_documents(tmp_path):
    docx_module = pytest.importorskip("docx")
    pytest.importorskip("reportlab")
    text = render_letter(Settings(), variables()).replace(
        "Je souhaite vous proposer ma candidature",
        "Texte modifié directement dans Rocky",
    )
    sections = parse_letter_sections(text)
    assert sections.body[0].startswith("Texte modifié directement")

    docx_path = tmp_path / "lettre_modifiee.docx"
    pdf_path = tmp_path / "lettre_modifiee.pdf"
    create_docx(docx_path, variables(), text)
    create_pdf(pdf_path, variables(), text)
    document = docx_module.Document(docx_path)
    assert "Texte modifié directement" in "\n".join(
        paragraph.text for paragraph in document.paragraphs
    )
