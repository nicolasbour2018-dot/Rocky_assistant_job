"""Tests du petit avatar Rocky embarqué dans l'interface."""

from dashboard.rocky.mascot import EXPRESSIONS, mascot_data_uri, mascot_svg


def test_each_rocky_expression_is_renderable_and_distinct():
    """Chaque état conserve un SVG autonome et une variation visible."""
    svgs = [mascot_svg(expression) for expression in EXPRESSIONS]

    assert all(svg.startswith("<svg") and "Rocky" in svg for svg in svgs)
    assert len(set(svgs)) == len(EXPRESSIONS)
    assert all(mascot_data_uri(expression).startswith("data:image/svg+xml;base64,") for expression in EXPRESSIONS)


def test_unknown_expression_falls_back_to_a_safe_avatar():
    """Une valeur de session inconnue ne doit jamais casser le rendu."""
    assert mascot_svg("not-a-real-expression") == mascot_svg("smiling")
