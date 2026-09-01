from dashboard.job_analysis import analyze_job, contains_expression, normalize_text


def test_normalize_text_removes_accents_and_spaces():
    assert normalize_text("  Pédagogie   avancée ") == "pedagogie avancee"


def test_short_aliases_require_word_boundaries():
    text = normalize_text("JavaScript et digital")
    assert not contains_expression(text, "Java")
    assert not contains_expression(text, "Git")


def test_analysis_classifies_known_skills():
    result = analyze_job(
        "Data Analyst",
        "Python, SQL, Power BI, reporting, rigueur et travail en équipe.",
    )
    assert {"Python", "SQL", "Power BI"} <= set(result["technical_skills"])
    assert "Reporting" in result["business_skills"]
    assert {"Rigueur", "Travail en équipe"} <= set(result["soft_skills"])
