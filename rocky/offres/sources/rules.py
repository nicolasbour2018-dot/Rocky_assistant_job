"""Source rules: no I/O. Source names, search queries and the small conversions shared by the connectors."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from rocky.offres.sources.model import SearchQuery, SourceCode
from rocky.profil.rules import normalize_term

# Registrable domain → source code. Any other site is named after its host (see ``source_for_url``).
KNOWN_DOMAINS = {
    "apec.fr": SourceCode.APEC,
    "adzuna.fr": SourceCode.ADZUNA,
    "adzuna.com": SourceCode.ADZUNA,
    "welcometothejungle.com": SourceCode.WTTJ,
    "linkedin.com": SourceCode.LINKEDIN,
    "wellfound.com": SourceCode.WELLFOUND,
    "francetravail.fr": SourceCode.FRANCE_TRAVAIL,
    "francetravail.io": SourceCode.FRANCE_TRAVAIL,
}
_COUNTRY_LABEL = re.compile(r"^[a-z]{2}$")
_SPACES = re.compile(r"[ \t\xa0]+")


def source_for_url(url: str) -> str | None:
    """Source name of a posting URL: a connector code, else the host without ``www.`` nor a country prefix.

    ``https://fr.indeed.com/viewjob?jk=…`` gives ``indeed.com``, never the whole URL. ``None`` without a host.
    """
    host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    if "." not in host:
        return None
    labels = host.split(".")
    if labels[0] == "www" or (_COUNTRY_LABEL.match(labels[0]) and len(labels) > 2):
        labels = labels[1:]
    host = ".".join(labels)
    for domain, code in KNOWN_DOMAINS.items():
        if host == domain or host.endswith(f".{domain}"):
            return code.value
    return host


def queries_for_track(
    titles: Iterable[str], locations: Iterable[str]
) -> list[SearchQuery]:
    """One query per (job title, location) of a track; a track without location searches titles alone."""
    places: list[str | None] = [place for place in locations if place.strip()]
    if not places:
        places = [None]
    return [
        SearchQuery(title.strip(), place.strip() if place else None)
        for title in titles
        if title.strip()
        for place in places
    ]


def unique_queries(
    queries: Iterable[SearchQuery], *, filters_location: bool
) -> list[SearchQuery]:
    """Queries without repeats (compared as terms); a source that ignores locations gets one query per title."""
    seen: set[tuple[str, str]] = set()
    kept: list[SearchQuery] = []
    for query in queries:
        location = query.location if filters_location else None
        key = (normalize_term(query.title), normalize_term(location or ""))
        if key not in seen:
            seen.add(key)
            kept.append(SearchQuery(query.title, location))
    return kept


def same_place(label: str, candidate: str) -> bool:
    """A location label written by the user matches a place name of a source (no case, accent, punctuation)."""
    return normalize_term(label) == normalize_term(candidate)


def text(value: object) -> str | None:
    """A trimmed text, ``None`` when missing or blank."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def number(value: object) -> float | None:
    """A number given by an API (int, float or numeric string), ``None`` otherwise."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def iso_date(value: object) -> date | None:
    """The date of an ISO 8601 timestamp or date; ``None`` when missing or unreadable."""
    raw = text(value)
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def unix_date(value: object) -> date | None:
    """The UTC date of a Unix timestamp (seconds); ``None`` when missing or unreadable."""
    seconds = number(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def is_truncated(description: str) -> bool:
    """A search excerpt ends with an ellipsis: it is not the full description."""
    return description.rstrip().endswith(("...", "…"))


def html_to_text(value: object) -> str:
    """Readable text of an HTML fragment: line breaks kept, list items as ``- item`` lines."""
    raw = text(value)
    if raw is None:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")
    for item in soup.find_all("li"):
        if isinstance(item, Tag):
            # Flattening the item keeps "- label" on one line when it contains inline tags.
            content = item.get_text(" ", strip=True)
            item.clear()
            item.append(f"\n- {content}\n")
    for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "ul", "ol"]):
        if isinstance(block, Tag):
            block.insert_before("\n")
            block.insert_after("\n")
    lines = [_SPACES.sub(" ", line).strip() for line in soup.get_text().splitlines()]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()
