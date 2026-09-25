"""LinkedIn: the public job cards served to visitors who are not signed in (no account, no session).

The cards give the title, the company and the place, never the description.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    SearchQuery,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.offres.sources.rules import iso_date, text

LABEL = SOURCE_LABELS[SourceCode.LINKEDIN]
SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
NO_DESCRIPTION_REASON = (
    "LinkedIn ne donne que l'intitulé, l'entreprise et le lieu dans sa liste publique."
)
# Postings of the last 30 days, newest first.
PERIOD = "r2592000"
_TRAILING_ID = re.compile(r"-(\d+)$")


class LinkedInSource:
    code = SourceCode.LINKEDIN
    filters_location = True

    def __init__(self, http: PublicHttp) -> None:
        self._http = http

    def availability(self) -> Availability:
        return Availability.READY

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        html = self._http.get_text(
            LABEL,
            SEARCH_URL,
            params={
                "keywords": query.title,
                "location": query.location or "France",
                "f_TPR": PERIOD,
                "sortBy": "DD",
                "start": 0,
            },
            headers={"Referer": "https://www.linkedin.com/jobs/search/"},
        )
        return parse_cards(html)[:limit]


def parse_cards(html: str) -> list[CollectedOffer]:
    """Offers of a page of public cards, read from their semantic classes rather than their layout.

    An empty answer is "no result". A page without any card is not: a sign-in wall is a refusal, anything else a
    changed page, never a silent "0 offers".
    """
    if not html.strip():
        return []
    if "base-search-card" not in html:
        if "authwall" in html or "uas/login" in html:
            raise SourceRefusedError(
                f"Refusé par {LABEL} : la plateforme demande de se connecter."
            )
        raise SourceFailedError(
            f"{LABEL} a renvoyé une page sans liste d'offres (page modifiée ?)."
        )
    offers: list[CollectedOffer] = []
    for card in BeautifulSoup(html, "html.parser").select("div.base-search-card"):
        offer = _offer(card)
        if offer is not None:
            offers.append(offer)
    return offers


def _offer(card: Tag) -> CollectedOffer | None:
    link = card.select_one("a.base-card__full-link")
    title = _text_of(card, ".base-search-card__title")
    url = str(link.get("href") or "").split("?", 1)[0] if link else ""
    if not url or title is None:
        return None
    identifier = str(card.get("data-entity-urn") or "").rsplit(":", 1)[-1]
    if not identifier:
        match = _TRAILING_ID.search(url)
        identifier = match.group(1) if match else url
    published = card.select_one("time[datetime]")
    return CollectedOffer(
        source=SourceCode.LINKEDIN,
        external_id=identifier,
        url=url,
        application_url=url,
        title=title,
        company=_text_of(card, ".base-search-card__subtitle"),
        location=_text_of(card, ".job-search-card__location"),
        published_on=iso_date(published.get("datetime") if published else None),
        description="",
        description_complete=False,
        incomplete_reason=NO_DESCRIPTION_REASON,
    )


def _text_of(card: Tag, selector: str) -> str | None:
    node = card.select_one(selector)
    return text(node.get_text(" ", strip=True)) if node else None
