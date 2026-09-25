"""Wellfound: the public role pages (``/role/r/<role>``, ``/role/l/<role>/<place>``), read from their page data.

No fallback when the CDN refuses the request (the old ``curl`` fallback imitated another client): a refusal stops.
"""

from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    NotFoundError,
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sources.rules import text, unix_date
from rocky.profil.rules import normalize_term

LABEL = SOURCE_LABELS[SourceCode.WELLFOUND]
WEBSITE = "https://wellfound.com"
RESULTS_KEY = "seoLandingPageJobSearchResults("
NO_DESCRIPTION_REASON = "Wellfound ne donne pas la description de cette offre."


class WellfoundSource:
    code = SourceCode.WELLFOUND
    filters_location = True

    def __init__(self, http: PublicHttp) -> None:
        self._http = http

    def availability(self) -> Availability:
        return Availability.READY

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        role = slug(query.title)
        path = (
            f"/role/l/{role}/{slug(query.location)}"
            if query.location
            else f"/role/r/{role}"
        )
        try:
            html = self._http.get_text(
                LABEL, f"{WEBSITE}{path}", headers={"Referer": f"{WEBSITE}/jobs"}
            )
        except NotFoundError as error:
            place = f" à « {query.location} »" if query.location else ""
            raise QuerySkippedError(
                f"{LABEL} n'a pas de page pour « {query.title} »{place}."
            ) from error
        return parse_page(html)[:limit]


def slug(value: str) -> str:
    """URL segment of a role or a place: "Data analyst" → ``data-analyst``, "Île-de-France" → ``ile-de-france``."""
    return normalize_term(value).replace(" ", "-")


def parse_page(html: str) -> list[CollectedOffer]:
    """Offers of the Apollo cache rendered by the server in ``__NEXT_DATA__``."""
    script = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise SourceFailedError(f"{LABEL} n'a pas fourni de données d'offres.")
    try:
        apollo = json.loads(script.string)["props"]["pageProps"]["apolloState"]
        state: dict[str, Any] = apollo.get("data", apollo)
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
        raise SourceFailedError(f"{LABEL} a renvoyé des données illisibles.") from error
    root = state.get("ROOT_QUERY") or {}
    queries = root.get("talent") or root
    results = next(
        (
            value
            for key, value in queries.items()
            if key.startswith(RESULTS_KEY) and isinstance(value, dict)
        ),
        {},
    )
    offers: list[CollectedOffer] = []
    for startup_ref in results.get("startups") or []:
        startup = state.get(str(_mapping(startup_ref).get("__ref")), {})
        for job_ref in startup.get("highlightedJobListings") or []:
            item = state.get(str(_mapping(job_ref).get("__ref")), {})
            offer = _offer(item, text(startup.get("name")))
            if offer is not None:
                offers.append(offer)
    return offers


def _offer(item: dict[str, Any], company: str | None) -> CollectedOffer | None:
    identifier, title = text(item.get("id")), text(item.get("title"))
    if identifier is None or title is None:
        return None
    url = f"{WEBSITE}/jobs/{identifier}-{text(item.get('slug')) or 'job'}"
    description = text(item.get("description")) or ""
    places = [
        str(place) for place in item.get("locationNames") or [] if str(place).strip()
    ]
    return CollectedOffer(
        source=SourceCode.WELLFOUND,
        external_id=identifier,
        url=url,
        application_url=url,
        title=title,
        company=company,
        location=", ".join(places) or None,
        contract=text(item.get("jobType")),
        remote="remote" if item.get("remote") else None,
        salary_text=text(item.get("compensation")),
        published_on=unix_date(item.get("liveStartAt")),
        description=description,
        description_complete=bool(description),
        incomplete_reason=None if description else NO_DESCRIPTION_REASON,
    )


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
