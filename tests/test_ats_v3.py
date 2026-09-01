from __future__ import annotations

from io import BytesIO

import pytest

import dashboard.rocky.ats_v3 as ats_v3
from dashboard.rocky.ats_v3 import analyze_ats_v3


def _pdf(lines: list[str], *, two_columns: bool = False) -> bytes:
    canvas_module = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = BytesIO()
    document = canvas_module.Canvas(buffer)
    if two_columns:
        y = 805
        for index, line in enumerate(lines):
            x = 45 if index % 2 == 0 else 330
            document.drawString(x, y, line)
            if index % 2:
                y -= 18
    else:
        text = document.beginText(45, 805)
        text.setLeading(14)
        for line in lines:
            text.textLine(line)
        document.drawText(text)
    document.save()
    return buffer.getvalue()


def _docx(lines: list[str]) -> bytes:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _standard_cv(skill_line: str) -> list[str]:
    return [
        "Amina Diallo",
        "Data Analyst",
        "amina.diallo@example.org | +33 6 11 22 33 44",
        "COMPETENCES",
        skill_line,
        "EXPERIENCE PROFESSIONNELLE",
        "Data Analyst - Atelier Fictif | 2021 - 2025",
        "Analyse de donnees, reporting et controle qualite pour les equipes.",
        "FORMATION",
        "Master Statistiques - Universite Exemple | 2019 - 2021",
        *(
            "Projet independant : nettoyage de donnees, documentation et restitution."
            for _ in range(9)
        ),
    ]


DATA_JOB = (
    "Nous recherchons une Data Analyst. Python et SQL sont obligatoires pour "
    "analyser les données, automatiser les contrôles et produire du reporting. "
    "Power BI est apprécié pour créer des tableaux de bord lisibles."
)


def _skill(report, name: str):
    return next(item for item in report.skill_comparisons if item.skill == name)


def test_v3_detects_when_an_important_skill_disappears_from_the_real_file():
    complete = analyze_ats_v3(
        _pdf(_standard_cv("Python, SQL, Pandas et analyse statistique")),
        "amina_complete.pdf",
        DATA_JOB,
        "Data Analyst",
    )
    without_sql = analyze_ats_v3(
        _pdf(_standard_cv("Python, Pandas et analyse statistique")),
        "amina_without_sql.pdf",
        DATA_JOB,
        "Data Analyst",
    )

    assert len(_skill(complete, "SQL").exact_parsers) >= 2
    assert not _skill(without_sql, "SQL").exact_parsers
    assert not _skill(without_sql, "SQL").variant_parsers
    assert without_sql.lexical_coverage < complete.lexical_coverage


def test_v3_flags_a_multi_column_pdf_as_a_parsing_risk():
    lines = _standard_cv("Python, SQL, Power BI, Git et Pandas")
    lines.extend(f"Mission {index} : analyse et reporting" for index in range(30))
    report = analyze_ats_v3(
        _pdf(lines, two_columns=True),
        "amina_columns.pdf",
        DATA_JOB,
        "Data Analyst",
    )

    pypdf = next(
        item for item in report.parser_extractions if item.parser_id == "pypdf"
    )
    assert pypdf.metadata["has_multiple_columns"] is True
    assert "Disposition multi-colonnes probable." in pypdf.warnings
    assert len({item.raw_text for item in report.parser_extractions}) >= 2


def test_v3_works_on_an_external_fictitious_cv_without_profile_enrichment():
    cv = _pdf(
        _standard_cv("Excel, gestion des stocks, planification logistique et achats")
    )
    distant_job = (
        "Nous recrutons un ingénieur plateforme. Python, Kubernetes, Docker, "
        "PostgreSQL et Git sont obligatoires pour construire des services cloud, "
        "maintenir les déploiements et automatiser la production."
    )

    report = analyze_ats_v3(cv, "amina_logistique.pdf", distant_job)

    assert report.lexical_coverage == 0
    assert all(
        not item.exact_parsers and not item.variant_parsers
        for item in report.skill_comparisons
    )
    assert any("absent" in item for item in report.recommendations)


def test_v3_compares_pdf_and_docx_built_from_the_same_content():
    lines = _standard_cv("Python, SQL, Pandas et Power BI")
    pdf_report = analyze_ats_v3(_pdf(lines), "amina.pdf", DATA_JOB)
    docx_report = analyze_ats_v3(_docx(lines), "amina.docx", DATA_JOB)

    assert len(pdf_report.parser_extractions) == 3
    assert len(docx_report.parser_extractions) == 2
    assert len(_skill(pdf_report, "Python").exact_parsers) >= 2
    assert len(_skill(docx_report, "Python").exact_parsers) == 2
    assert pdf_report.file_type == "pdf"
    assert docx_report.file_type == "docx"


def test_v3_keeps_semantic_evidence_separate_from_lexical_presence():
    cv = _pdf(_standard_cv("Python, requetage relationnel et production de rapports"))
    report = analyze_ats_v3(cv, "amina_semantic.pdf", DATA_JOB)
    sql = _skill(report, "SQL")

    assert not sql.exact_parsers
    assert not sql.variant_parsers
    assert len(sql.semantic_evidence) >= 2
    assert report.semantic_coverage is not None


def test_v3_exposes_six_explicitly_approximate_ats_benchmarks():
    report = analyze_ats_v3(
        _pdf(_standard_cv("Python, SQL et Power BI")),
        "amina.pdf",
        DATA_JOB,
    )

    names = {item.name for item in report.benchmark_results}
    assert names == {
        "Workday-like",
        "Taleo / Oracle-like",
        "iCIMS-like",
        "Greenhouse-like",
        "Lever-like",
        "SuccessFactors-like",
    }
    assert all(0 <= item.score <= 100 for item in report.benchmark_results)


def test_v3_makes_a_single_parser_failure_visible(monkeypatch):
    def fail(_data: bytes):
        raise RuntimeError("simulated parser failure")

    monkeypatch.setattr(ats_v3, "_pypdf_extract", fail)
    report = analyze_ats_v3(
        _pdf(_standard_cv("Python, SQL et Power BI")),
        "amina.pdf",
        DATA_JOB,
    )

    failed = next(
        item for item in report.parser_extractions if item.parser_id == "pypdf"
    )
    assert failed.quality_score == 0
    assert failed.metadata == {"parser_error": "RuntimeError"}
    assert failed.warnings == ("Échec du parseur (RuntimeError).",)
