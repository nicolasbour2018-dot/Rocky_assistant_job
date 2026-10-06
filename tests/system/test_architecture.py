"""The imports between modules (step H4): a module reads another one through its ``api.py``, never through its routes
nor its SQL; ``system`` imports the business modules only where it assembles them."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import rocky

ROOT = Path(rocky.__file__).parent
BUSINESS = frozenset({"profil", "offres", "candidatures", "messages"})
# The files of ``system`` that assemble the modules: the application, the command line, the tables of the migrations.
ASSEMBLY = frozenset({"web.py", "admin.py", "tables.py"})
# The profile's screen helpers take a request: another module's routes may import them, by name (decision H4).
SCREEN_HELPERS = {
    "rocky.profil.web": frozenset(
        {"profile_of", "cv_document", "cv_drawing", "cv_fingerprint", "cv_slots"}
    ),
    "rocky.profil.letter_web": frozenset({"generic_letters"}),
    "rocky.profil.translation_web": frozenset({"to_review", "english_cv_outdated"}),
}


def _is_routes(name: str) -> bool:
    return name == "web" or name.endswith("_web")


def _imports(path: Path) -> Iterator[tuple[str, str | None]]:
    """``(module, name)`` of each import of ``rocky`` in the file; ``name`` is None for ``import rocky.…``."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("rocky"):
            yield from ((node.module or "", alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            yield from ((alias.name, None) for alias in node.names)


def _forbidden(path: Path) -> Iterator[str]:
    owner = path.relative_to(ROOT).parts[0]
    for module, name in _imports(path):
        # ``from rocky.offres import web`` imports the module ``rocky.offres.web``.
        parts = [*module.split("."), *([name] if name else [])]
        if parts[0] != "rocky" or len(parts) < 2:
            continue
        target = parts[1]
        if target not in BUSINESS or target == owner:
            continue
        if owner == "system":
            allowed = str(path.relative_to(ROOT / "system")) in ASSEMBLY
        else:
            inner = any(part == "sql" or _is_routes(part) for part in parts[2:])
            helper = _is_routes(path.stem) and name in SCREEN_HELPERS.get(module, ())
            allowed = not inner or helper
        if not allowed:
            yield f"{path.relative_to(ROOT.parent)} → {module} ({name})"


def test_a_module_reads_another_one_through_its_api_only() -> None:
    assert [
        line for path in sorted(ROOT.rglob("*.py")) for line in _forbidden(path)
    ] == []
