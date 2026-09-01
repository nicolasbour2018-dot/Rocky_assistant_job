from pathlib import Path

import pytest

from dashboard.rocky.ats import (
    analyze_application_ats,
    analyze_application_ats_v2,
    extract_pdf_text,
    repair_spaced_pdf_text,
    save_ats_cv_text,
)
from dashboard.rocky.errors import DocumentError
from dashboard.rocky.models import JobOffer


def create_cv_pdf(path: Path) -> None:
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    canvas = reportlab.Canvas(str(path))
    text = canvas.beginText(45, 800)
    text.setLeading(13)
    lines = [
        "Nicolas Bour - Data Analyst",
        "nicolas@example.com - 06 12 34 56 78",
        "COMPETENCES",
        "Python, SQL, Power BI, communication et analyse statistique",
        "EXPERIENCE PROFESSIONNELLE",
        "Analyse de donnees, tableaux de bord et restitution aux equipes.",
        "FORMATION",
        "Certification Data Analyst et projets de machine learning.",
    ]
    lines.extend(
        "Projet data : preparation des donnees, controle qualite, reporting "
        "et presentation des resultats."
        for _ in range(12)
    )
    for line in lines:
        text.textLine(line)
    canvas.drawText(text)
    canvas.save()


def test_ats_report_checks_cv_letter_and_job_keywords(tmp_path):
    cv_path = tmp_path / "cv.pdf"
    create_cv_pdf(cv_path)
    offer = JobOffer(
        "Data Analyst",
        "Rocky Data",
        (
            "Nous recherchons une personne maîtrisant Python, SQL, Power BI, "
            "la communication et l'analyse statistique."
        ),
        detected_skills=[
            "Python",
            "SQL",
            "Power BI",
            "Communication",
            "Analyse statistique",
        ],
        description_is_full=True,
    )
    letter = (
        "Objet : Candidature au poste de Data Analyst chez Rocky Data\n\n"
        "Madame, Monsieur,\n\n"
        "Mon expérience en Python, SQL, Power BI et communication correspond "
        "aux missions proposées. "
        + "Je souhaite mettre mon expérience en analyse de données au service "
        "de votre équipe. " * 22 + "Je vous prie d’agréer mes salutations distinguées."
    )

    report = analyze_application_ats(cv_path, letter, offer)

    assert report.score >= 75
    assert report.cv_score >= 80
    assert report.keyword_coverage == 100
    assert set(report.matched_keywords) == set(offer.detected_skills)
    assert report.missing_keywords == ()
    assert report.cv_pages == 1
    assert report.letter_words >= 180


def test_ats_rejects_an_unreadable_pdf(tmp_path):
    invalid = tmp_path / "cv.pdf"
    invalid.write_bytes(b"%PDF-invalid")

    with pytest.raises(DocumentError, match="n’a pas pu être extrait"):
        extract_pdf_text(invalid)


def test_ats_v2_repairs_character_spacing_and_keeps_real_word_boundaries():
    text, ratio = repair_spaced_pdf_text(
        "P y t h o n  P a n d a s\nE X P E R I E N C E\nUne phrase normalement espacée"
    )

    assert text.splitlines() == [
        "Python Pandas",
        "EXPERIENCE",
        "Une phrase normalement espacée",
    ]
    assert ratio > 0.5


def test_ats_v2_distinguishes_exact_related_and_missing_skills(tmp_path):
    cv_path = tmp_path / "cv.pdf"
    create_cv_pdf(cv_path)
    offer = JobOffer(
        "Data Analyst",
        "Rocky Data",
        "Python, Git, Agile, Jupyter, Matplotlib et Power BI",
        detected_skills=[
            "Python",
            "Git",
            "Agile",
            "Jupyter",
            "Matplotlib",
            "Power BI",
        ],
        description_is_full=True,
    )
    cv_text = (
        "Nicolas Bour Data Analyst\n"
        "nicolas@example.com 06 12 34 56 78\n"
        "COMPÉTENCES\nPython, GitHub, gestion de projet, notebook et "
        "Data Visualisation\n"
        "EXPÉRIENCE\nAnalyse de données et tableaux de bord.\n"
        "FORMATION\nCertification Data."
    )
    letter = (
        "Objet : Candidature Data Analyst chez Rocky Data\n\n"
        "Madame, Monsieur,\n\n"
        + "Je maîtrise Python et je souhaite contribuer à vos projets. " * 25
        + "Veuillez agréer mes salutations distinguées."
    )

    report = analyze_application_ats_v2(
        cv_path, letter, offer, cv_text_override=cv_text
    )

    assert "Python" in report.exact_keywords
    related = {
        match.required_skill: match.cv_evidence for match in report.related_keywords
    }
    assert related["Git"] == "GitHub"
    assert "Agile" in related
    assert "Jupyter" in related
    assert "Matplotlib" in related
    assert "Power BI" in related
    assert report.exact_keyword_coverage < report.adjusted_keyword_coverage
    assert report.missing_keywords == ()


def test_manual_ats_text_is_saved_without_changing_the_pdf(tmp_path):
    cv_path = tmp_path / "cv.pdf"
    cv_bytes = b"%PDF-original"
    cv_path.write_bytes(cv_bytes)
    text_path = tmp_path / "cv_ats.txt"

    save_ats_cv_text(
        text_path,
        "COMPÉTENCES\nPython, SQL, Pandas\n" + "Expérience data. " * 10,
    )

    assert "Python, SQL, Pandas" in text_path.read_text(encoding="utf-8")
    assert cv_path.read_bytes() == cv_bytes
