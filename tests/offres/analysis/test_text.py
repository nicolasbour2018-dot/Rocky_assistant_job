"""Text tools of the analysis: readable description, comparison form with positions, sentences, sections."""

from __future__ import annotations

from rocky.offres.analysis.text import (
    evidence,
    find,
    fold,
    formatted_description,
    headings,
    sentences,
    term_pattern,
)
from rocky.profil.rules import normalize_term


def test_html_becomes_lines_and_bullets() -> None:
    raw = "<p><strong>Profil</strong></p><ul><li>Python</li><li>SQL &amp; dbt</li></ul>"

    assert formatted_description(raw) == "Profil\n\n- Python\n- SQL & dbt"


def test_markdown_becomes_plain_text() -> None:
    raw = "### The Role\n**About us:** we [build](https://site.example) tools\n* Python\n* SQL"

    assert (
        formatted_description(raw)
        == "The Role\nAbout us: we build tools\n- Python\n- SQL"
    )


def test_the_comparison_form_is_the_one_of_the_profile_terms() -> None:
    source = "L’Analyse  de données (NLP)"

    folded = fold(source)

    assert folded.text == normalize_term(source) == "l analyse de donnees nlp"
    start = folded.text.index("donnees")
    assert (
        source[slice(*folded.source_span(start, start + len("donnees")))] == "données"
    )


def test_a_term_is_found_as_whole_words_with_a_plural() -> None:
    folded = fold("JavaScript, dashboards and Java.")

    assert list(find(folded, term_pattern("java"))) == [(27, 31)]
    assert list(find(folded, term_pattern("dashboard"))) == [(12, 22)]


def test_sentences_end_at_punctuation_lines_and_inline_bullets() -> None:
    source = "Python requis. SQL apprécié\nRigueur- Autonomie, - Agile"

    spans = sentences(source).spans

    assert [source[start:end] for start, end in spans] == [
        "Python requis.",
        "SQL apprécié",
        "Rigueur",
        "Autonomie,",
        "Agile",
    ]


def test_evidence_is_cut_around_the_match() -> None:
    source = "a" * 300 + " Python " + "b" * 300
    start = source.index("Python")

    quote = evidence(source, (start, start + 6), (0, len(source)))

    assert "Python" in quote
    assert quote.startswith("…") and quote.endswith("…")
    assert len(quote) <= 222


def test_short_lines_that_are_not_bullets_open_sections() -> None:
    source = "Compétences indispensables :\n- Python\n- SQL\nNous sommes une équipe de passionnés."

    assert headings(source) == ((0, "Compétences indispensables :"),)
