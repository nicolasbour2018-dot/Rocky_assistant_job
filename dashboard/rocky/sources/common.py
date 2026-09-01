"""Outils partagés par les connecteurs de plateformes publiques.

Ce module garde les détails HTTP et les petites normalisations hors des
connecteurs. Chaque source reste ainsi courte et ne contient que ce qui lui
est propre : URL, paramètres et conversion vers :class:`JobOffer`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from collections.abc import Iterable

import requests

from ..errors import SourceError
from ..models import JobOffer


BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
}


def public_get(
    source_name: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 25,
) -> requests.Response:
    """Effectue un GET public et transforme les erreurs en message sûr.

    Les URL complètes et réponses brutes ne sont jamais recopiées : elles
    peuvent contenir des paramètres techniques ou des données de session.
    """
    request_headers = {**BROWSER_HEADERS, **(headers or {})}
    try:
        response = requests.get(
            url,
            params=params,
            headers=request_headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "inconnu"
        raise SourceError(
            f"{source_name} a refusé la requête publique (HTTP {status})."
        ) from error
    except requests.RequestException as error:
        raise SourceError(
            f"{source_name} ne répond pas à la requête publique."
        ) from error


def public_post_json(
    source_name: str,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 25,
) -> requests.Response:
    """Effectue un POST JSON public avec la même politique d'erreur."""
    request_headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json",
        **(headers or {}),
    }
    try:
        response = requests.post(
            url,
            json=payload,
            headers=request_headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "inconnu"
        raise SourceError(
            f"{source_name} a refusé la requête publique (HTTP {status})."
        ) from error
    except requests.RequestException as error:
        raise SourceError(
            f"{source_name} ne répond pas à la requête publique."
        ) from error


def iso_date(value: object) -> date | None:
    """Convertit les formats ISO les plus fréquents, sans faire échouer la veille."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def unix_date(value: object) -> date | None:
    """Convertit un timestamp Unix en date UTC."""
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).date()
    except (TypeError, ValueError, OSError):
        return None


def salary_values(value: object) -> tuple[float | None, float | None, str]:
    """Extrait une fourchette simple, y compris les notations 45k/45 k€."""
    text = str(value or "")
    currency = "EUR"
    if "$" in text or "USD" in text.upper():
        currency = "USD"
    elif "£" in text or "GBP" in text.upper():
        currency = "GBP"

    values: list[float] = []
    range_uses_thousands = bool(re.search(r"\d\s*[kK]", text))
    for number, suffix in re.findall(r"(\d+(?:[\s.,]\d+)?)\s*([kK]?)", text):
        cleaned = number.replace(" ", "").replace(",", ".")
        try:
            parsed = float(cleaned)
        except ValueError:
            continue
        if suffix or (range_uses_thousands and parsed < 1_000):
            parsed *= 1_000
        if parsed >= 1_000:
            values.append(parsed)
    if not values:
        return None, None, currency
    return min(values), max(values), currency


def deduplicate_offers(offers: Iterable[JobOffer]) -> list[JobOffer]:
    """Déduplique les résultats recoupés par plusieurs intitulés du profil."""
    unique: list[JobOffer] = []
    seen: set[tuple[str, str]] = set()
    for offer in offers:
        identity = (
            offer.source_name,
            offer.external_id or offer.source_url or offer.job_title,
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(offer)
    return unique


def web_slug(value: str) -> str:
    """Crée un segment d'URL ASCII prévisible pour les pages de rôle."""
    from ..text_utils import normalize_text

    return re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")
