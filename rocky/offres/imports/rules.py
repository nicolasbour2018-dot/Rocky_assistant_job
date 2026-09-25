"""Import rules: no I/O. Link checks, the reading of a posting page, and the enrichment of an offer.

A page is read in this order (decision C2): the ``JobPosting`` of its JSON-LD data, else a known description
container, else its visible text, kept but marked incomplete. Facts stay as published (C1 rule): contract, remote
work and salary as source texts, no value guessed.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from rocky.offres.imports.model import ImportMethod, ImportPreview, InvalidPasteError
from rocky.offres.sources.model import (
    CollectedOffer,
    InvalidLinkError,
    SourceFailedError,
)
from rocky.offres.sources.rules import (
    as_mapping,
    html_to_text,
    iso_date,
    number,
    source_for_url,
    text,
)

MAX_LINK_LENGTH = 2048
# Ordinary web ports only: a link cannot be used to probe other services.
ALLOWED_PORTS = {None, 80, 443}
MAX_PASTED_CHARACTERS = 50_000
VISIBLE_TEXT_LIMIT = 20_000
# Containers known to hold the whole posting (ported from the old importer).
DESCRIPTION_SELECTORS = (
    "#jobDescriptionText",  # Indeed
    ".show-more-less-html__markup",  # LinkedIn
    ".description__text",  # LinkedIn, older public page
    "[data-testid='job-section-description']",  # Welcome to the Jungle
    "[data-testid='job-description']",
    "[data-test='JobDescription']",  # Wellfound
    "[class*='job-description']",
)
# Not part of a posting: dropped before the visible text is read.
NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "template",
    "iframe",
    "nav",
    "header",
    "footer",
    "form",
    "button",
)
VISIBLE_TEXT_REASON = (
    "Extraction approximative : la page ne publie pas d'annonce structurée, la description "
    "est son texte visible (menus et mentions compris)."
)
EXCERPT_REASON = "La page ne donne qu'un extrait de l'annonce."
NO_CONTENT_REASON = (
    "La page ne contient aucun texte lisible : elle est sans doute affichée par JavaScript. "
    "Colle la description de l'annonce."
)
_SPACES = re.compile(r"[ \t\xa0]+")
# Fact fields that an enrichment may fill when the offer does not know them.
FACT_FIELDS = (
    "company",
    "location",
    "country",
    "application_url",
    "contract",
    "remote",
    "salary_text",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "sector",
    "published_on",
    "deadline",
)


def check_link(link: str) -> str:
    """The link to read, without its fragment; raises ``InvalidLinkError`` with the reason."""
    cleaned = link.strip()
    if not cleaned:
        raise InvalidLinkError("Colle le lien de l'annonce.")
    if len(cleaned) > MAX_LINK_LENGTH:
        raise InvalidLinkError("Le lien est trop long pour être celui d'une annonce.")
    parts = urlsplit(cleaned)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise InvalidLinkError("Le lien doit commencer par http:// ou https://.")
    if parts.username is not None or parts.password is not None:
        raise InvalidLinkError(
            "Le lien ne doit contenir ni identifiant ni mot de passe."
        )
    host = parts.hostname or ""
    if "." not in host.strip("."):
        raise InvalidLinkError("Le lien n'a pas de nom de site valide.")
    try:
        port = parts.port
    except ValueError as error:
        raise InvalidLinkError("Le port indiqué dans le lien est invalide.") from error
    if port not in ALLOWED_PORTS:
        raise InvalidLinkError(
            f"Le lien utilise un port inhabituel ({port}) : Rocky ne lit que les sites web ordinaires."
        )
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, ""))


def parse_page(page_html: str, url: str, *, today: date) -> ImportPreview:
    """The offer published by a page read at ``url``; raises ``SourceFailedError`` when it holds nothing to read."""
    soup = BeautifulSoup(page_html, "html.parser")
    postings, unreadable = _postings(soup)
    posting = postings[0] if postings else {}
    warnings: list[str] = []
    if unreadable:
        warnings.append(
            f"Données structurées illisibles ignorées ({unreadable} bloc{'s' if unreadable > 1 else ''})."
        )
    address = _canonical(soup, url)
    title = _plain(posting.get("title")) or _meta(soup, "og:title") or _title(soup)
    if title is None:
        warnings.append("Intitulé introuvable sur la page.")

    description = _description(posting.get("description"))
    method = ImportMethod.JSON_LD
    if not description:
        description = _targeted_description(soup)
        method = ImportMethod.TARGETED_HTML
    complete, reason = True, None
    if not description:
        description = _visible_text(soup)
        method = ImportMethod.VISIBLE_TEXT
        complete, reason = False, VISIBLE_TEXT_REASON
        if not description:
            raise SourceFailedError(NO_CONTENT_REASON)
        if len(description) > VISIBLE_TEXT_LIMIT:
            description = description[:VISIBLE_TEXT_LIMIT]
            warnings.append(
                f"Texte visible tronqué à {VISIBLE_TEXT_LIMIT:,} caractères.".replace(
                    ",", " "
                )
            )
    elif is_excerpt(description):
        complete, reason = False, EXCERPT_REASON

    deadline = iso_date(posting.get("validThrough"))
    if deadline is not None and deadline < today:
        warnings.append(
            f"La date limite de candidature est passée ({deadline:%d/%m/%Y})."
        )
    location, country = _place(posting.get("jobLocation"))
    salary_min, salary_max, currency, period = _salary(posting)
    offer = CollectedOffer(
        source=source_for_url(address) or "",
        # The page address names the posting; an ``identifier`` is the employer's reference, not the platform's.
        external_id=address,
        url=address,
        application_url=address,
        title=title or "",
        description=description,
        description_complete=complete,
        incomplete_reason=reason,
        company=_plain(posting.get("hiringOrganization")),
        location=location,
        country=country,
        contract=_plain(posting.get("employmentType")),
        remote=_plain(posting.get("jobLocationType")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=period,
        sector=_plain(posting.get("industry")),
        published_on=iso_date(posting.get("datePosted")),
        deadline=deadline,
    )
    return ImportPreview(offer, method, tuple(warnings))


def is_excerpt(description: str) -> bool:
    """A description cut by its site (``…`` or ``...`` at the end) is an excerpt, not the posting."""
    return description.rstrip().endswith(("...", "…"))


def enriched(offer: CollectedOffer, found: CollectedOffer) -> CollectedOffer:
    """``offer`` completed by another reading of its posting (its page, a visible browser, an alert).

    The description is replaced only by a complete one; facts the offer does not know are filled, the others are
    never overwritten; the identity of the offer (source, identifier, address) is kept.
    """
    changes: dict[str, Any] = {
        name: getattr(found, name)
        for name in FACT_FIELDS
        if getattr(offer, name) is None and getattr(found, name) is not None
    }
    if not offer.title and found.title:
        changes["title"] = found.title
    if (
        not offer.description_complete
        and found.description_complete
        and found.description
    ):
        changes.update(
            description=found.description,
            description_complete=True,
            incomplete_reason=None,
        )
    return replace(offer, **changes)


def pasted_text(value: str) -> str:
    """A pasted description: spaces normalised, at most one blank line in a row."""
    lines = [_SPACES.sub(" ", line).strip() for line in value.splitlines()]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def with_pasted_description(offer: CollectedOffer, value: str) -> CollectedOffer:
    """The offer with the description the user pasted from its posting; raises ``InvalidPasteError``."""
    description = pasted_text(value)
    if not description:
        raise InvalidPasteError("Colle le texte de l'annonce.")
    if len(description) > MAX_PASTED_CHARACTERS:
        raise InvalidPasteError(
            "Le texte collé est trop long pour une annonce (50 000 caractères au plus)."
        )
    return replace(
        offer,
        description=description,
        description_complete=True,
        incomplete_reason=None,
    )


def offer_from_paste(
    link: str, title: str, value: str, company: str | None = None
) -> ImportPreview:
    """The offer of a posting whose link gave nothing usable, from what the user copied of it.

    Raises ``InvalidLinkError`` or ``InvalidPasteError``.
    """
    address = check_link(link)
    cleaned_title = _SPACES.sub(" ", title).strip()
    if not cleaned_title:
        raise InvalidPasteError("Indique l'intitulé de l'annonce.")
    offer = CollectedOffer(
        source=source_for_url(address) or "",
        external_id=address,
        url=address,
        application_url=address,
        title=cleaned_title,
        company=text(company),
        description="",
        description_complete=False,
    )
    return ImportPreview(with_pasted_description(offer, value), ImportMethod.PASTED)


def _postings(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], int]:
    """The ``JobPosting`` objects of the JSON-LD blocks, and the number of unreadable blocks."""
    postings: list[dict[str, Any]] = []
    unreadable = 0
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            # strict=False: some sites leave raw line breaks inside their strings.
            data = json.loads(script.get_text(), strict=False)
        except ValueError:
            unreadable += 1
            continue
        postings.extend(_postings_in(data))
    return postings, unreadable


def _postings_in(value: object) -> Iterator[dict[str, Any]]:
    """JobPosting objects wherever they are: a list of blocks, a ``@graph``, a nested value."""
    if isinstance(value, list):
        for item in value:
            yield from _postings_in(item)
    elif isinstance(value, dict):
        kind = value.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            yield value
            return
        for child in value.values():
            yield from _postings_in(child)


def _plain(value: object) -> str | None:
    """A text of the JSON-LD data: a name for an object, items joined for a list, HTML entities decoded."""
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        parts = [part for part in (_plain(item) for item in value) if part]
        return ", ".join(parts) or None
    raw = text(value)
    return text(html.unescape(raw)) if raw else None


def _description(value: object) -> str:
    """Readable text of a JSON-LD description, HTML or plain."""
    raw = text(value)
    if raw is None:
        return ""
    # LinkedIn escapes its HTML once more inside the JSON (``&lt;p&gt;``).
    if "<" not in raw and "&lt;" in raw:
        raw = html.unescape(raw)
    return html_to_text(raw)


def _place(value: object) -> tuple[str | None, str | None]:
    """Locality (or region) and country of the first place that has one."""
    places = value if isinstance(value, list) else [value]
    for place in places:
        address = as_mapping(place).get("address")
        if isinstance(address, str):
            return _plain(address), None
        address = as_mapping(address)
        locality = _plain(address.get("addressLocality")) or _plain(
            address.get("addressRegion")
        )
        country = _plain(address.get("addressCountry"))
        if locality or country:
            return locality, country
    return None, None


def _salary(
    posting: dict[str, Any],
) -> tuple[float | None, float | None, str | None, str | None]:
    """Bounds, currency and period of ``baseSalary``, the employer's figure.

    ``estimatedSalary`` is the platform's estimate (Hellowork), not a fact of the posting: it is not read.
    """
    salary = as_mapping(posting.get("baseSalary"))
    value = salary.get("value")
    if isinstance(value, dict):
        minimum, maximum = number(value.get("minValue")), number(value.get("maxValue"))
        if minimum is None and maximum is None:
            minimum = maximum = number(value.get("value"))
        period = _plain(value.get("unitText"))
    else:
        minimum = maximum = number(value)
        period = _plain(salary.get("unitText"))
    if minimum is None and maximum is None:
        return None, None, None, None
    currency = _plain(salary.get("currency")) or _plain(posting.get("salaryCurrency"))
    return minimum, maximum, currency, period


def _canonical(soup: BeautifulSoup, url: str) -> str:
    link = soup.find("link", rel="canonical")
    href = text(link.get("href")) if isinstance(link, Tag) else None
    if href is None:
        return url
    address = urljoin(url, href)
    return address if urlsplit(address).scheme in {"http", "https"} else url


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", property=name)
    return _plain(tag.get("content")) if isinstance(tag, Tag) else None


def _title(soup: BeautifulSoup) -> str | None:
    return _plain(soup.title.get_text()) if soup.title else None


def _targeted_description(soup: BeautifulSoup) -> str:
    for selector in DESCRIPTION_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            description = html_to_text(str(node))
            if description:
                return description
    return ""


def _visible_text(soup: BeautifulSoup) -> str:
    """The text a reader sees, without scripts, menus, headers and footers (the soup is changed)."""
    body = soup.body or soup
    for tag in body.find_all(NOISE_TAGS):
        tag.decompose()
    return html_to_text(str(body))
