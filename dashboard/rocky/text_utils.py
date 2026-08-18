"""Petites fonctions de normalisation sans dépendance externe."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text


def ensure_list(value: object) -> list[str]:
    """Convertit proprement tableaux PostgreSQL, listes et texte séparé."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def canonical_url(url: str) -> str:
    """Retire fragment et paramètres de tracking pour la déduplication."""
    parts = urlsplit(url.strip())
    kept_query = "&".join(
        pair
        for pair in parts.query.split("&")
        if pair and not pair.lower().startswith(("utm_", "trk=", "ref="))
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, kept_query, "")
    )


def safe_slug(value: str, fallback: str = "element") -> str:
    text = normalize_text(value)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:70] or fallback


def project_relative(path: str | Path, project_dir: Path) -> str:
    """Stocke un chemin relatif au projet, ou absolu pour un volume externe."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(project_dir.resolve()))
    except ValueError:
        return str(resolved)
