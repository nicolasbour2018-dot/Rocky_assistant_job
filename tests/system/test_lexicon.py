"""One name for one thing, all over Rocky (decision G6, Q3, R8; exit criterion 5): the names set aside by the lexicon
of the review never come back in a template nor in a string of the code. Comments and docstrings are not read: they
may name the old words to explain the change."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROCKY = Path(__file__).resolve().parents[2] / "rocky"
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
# The name set aside → the name kept (decision G6, lexicon of the artifact).
SET_ASIDE = {
    r"Sans nouvelles": "Sans réponse",
    r"Relever maintenant": "Relever les messages",
    r"Lancer maintenant|Lancer la veille maintenant|Relancer la veille": "Lancer la veille",
    r"Reconnecter\b(?! la boîte)": "Reconnecter la boîte",
    r"Pourquoi (intéressé|écartée?|plus tard) \?|Pourquoi cette offre t'intéresse": "Pourquoi « <geste> » ?",
    r"Comment ces chiffres sont comptés": "Ce qu'on compte, exactement",
    r"Ouvrir l'annonce d'origine": "Voir l'annonce d'origine ↗",
    r"Download in English|\bPreview\b|Check my CV|Check this CV": "libellés en français",
    r"Abandonner les modifications": "Fermer",
    r"\bPrêtes\b(?! à envoyer)": "Prêtes à envoyer",
    r"Accusés\b(?! de réception)": "Accusés de réception",
    r">\s*Annuler\s*<|\"Annuler\"": "Fermer (abandonner une saisie) ou ↶ Annuler (défaire)",
}
# Gmail is read by a « relevé »; a source of offers is still « collectée » (C1).
SET_ASIDE_IN_MESSAGES = {r"\b[Cc]ollecte\b": "relevé"}


def texts() -> list[tuple[Path, str]]:
    """The templates without their comments, and the strings of the code without the docstrings."""
    found = [
        (path, JINJA_COMMENT.sub("", path.read_text()))
        for path in ROCKY.rglob("*.html")
    ]
    for path in ROCKY.rglob("*.py"):
        tree = ast.parse(path.read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        found += [
            (path, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
    return found


def test_the_names_set_aside_never_come_back() -> None:
    found = []
    for path, text in texts():
        rules = {
            **SET_ASIDE,
            **(SET_ASIDE_IN_MESSAGES if "messages" in path.parts else {}),
        }
        for pattern, kept in rules.items():
            for match in re.finditer(pattern, text):
                found.append(f"{path.relative_to(ROCKY)}: « {match.group()} » → {kept}")

    assert found == []
