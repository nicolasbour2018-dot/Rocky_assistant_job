"""Adzuna: the official search API (application keys in the query string, never shown)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sources.rules import iso_date, number, text

LABEL = SOURCE_LABELS[SourceCode.ADZUNA]
SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
EXCERPT_REASON = "Adzuna ne donne qu'un extrait de l'annonce."
MAX_RESULTS = 50


class AdzunaSource:
    code = SourceCode.ADZUNA
    filters_location = True

    def __init__(
        self, http: PublicHttp, app_id: str | None, app_key: str | None
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._app_key = app_key

    def availability(self) -> Availability:
        if self._app_id and self._app_key:
            return Availability.READY
        return Availability.NOT_CONFIGURED

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        if not self._app_id or not self._app_key:
            raise SourceFailedError(f"Les clés {LABEL} sont absentes.")
        params: dict[str, str | int] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": min(max(limit, 1), MAX_RESULTS),
            "what": query.title,
            "sort_by": "date",
        }
        if query.location:
            params["where"] = query.location
        data = self._http.get_json(LABEL, SEARCH_URL, params=params)
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        offers = (_offer(item) for item in items if isinstance(item, dict))
        return [offer for offer in offers if offer is not None][:limit]


def _offer(item: dict[str, Any]) -> CollectedOffer | None:
    identifier, title = text(item.get("id")), text(item.get("title"))
    redirect = text(item.get("redirect_url"))
    if identifier is None or title is None or redirect is None:
        return None
    url = without_tracking(redirect)
    company, place, category = (
        _mapping(item.get(key)) for key in ("company", "location", "category")
    )
    # Adzuna estimates a salary when the posting has none: an estimate is not a fact of the posting.
    predicted = str(item.get("salary_is_predicted") or "0") == "1"
    contract = " ".join(
        value
        for value in (text(item.get("contract_type")), text(item.get("contract_time")))
        if value
    )
    return CollectedOffer(
        source=SourceCode.ADZUNA,
        external_id=identifier,
        url=url,
        application_url=url,
        title=title,
        company=text(company.get("display_name")),
        location=text(place.get("display_name")),
        country="France",
        contract=contract or None,
        salary_min=None if predicted else number(item.get("salary_min")),
        salary_max=None if predicted else number(item.get("salary_max")),
        salary_currency=None if predicted or item.get("salary_min") is None else "EUR",
        salary_period=None if predicted or item.get("salary_min") is None else "year",
        sector=text(category.get("label")),
        published_on=iso_date(item.get("created")),
        # The API documents its description as a snippet of the posting.
        description=text(item.get("description")) or "",
        description_complete=False,
        incomplete_reason=EXCERPT_REASON,
    )


def without_tracking(url: str) -> str:
    """The redirect address without its ``utm_*`` parameters: ``utm_source`` names the application keys."""
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if not key.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
