"""Welcome to the Jungle: the public jobs endpoint of its website, then the public detail of each job.

The search ignores locations (it refuses any location field) and gives no description: the detail gives it.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any
from urllib.parse import quote, urlsplit

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sources.rules import as_mapping, html_to_text, iso_date, number, text

LABEL = SOURCE_LABELS[SourceCode.WTTJ]
WEBSITE = "https://www.welcometothejungle.com"
SEARCH_URL = "https://api.welcometothejungle.com/api/v3/public/jobs"
DETAIL_URL = (
    "https://api.welcometothejungle.com/api/v1/organizations/{organization}/jobs/{job}"
)
NO_DESCRIPTION_REASON = (
    "Welcome to the Jungle ne donne pas la description dans ses résultats de recherche."
)
HEADERS = {
    "Origin": WEBSITE,
    "Referer": f"{WEBSITE}/fr/jobs",
    "wttj-user-language": "fr",
}
DETAIL_SECTIONS = (
    ("Description du poste", "description"),
    ("Profil recherché", "profile"),
    ("Déroulement des entretiens", "recruitment_process"),
)


class WelcomeToTheJungleSource:
    code = SourceCode.WTTJ
    filters_location = False

    def __init__(self, http: PublicHttp) -> None:
        self._http = http

    def availability(self) -> Availability:
        return Availability.READY

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        # One page of ten jobs: the endpoint takes no page size.
        data = self._http.get_json(
            LABEL,
            SEARCH_URL,
            params={"job_title": query.title, "page": 1, "query_id": str(uuid.uuid4())},
            headers=HEADERS,
        )
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        offers = (_offer(item) for item in items if isinstance(item, dict))
        return [offer for offer in offers if offer is not None][:limit]

    def complete(self, offer: CollectedOffer) -> CollectedOffer:
        parts = urlsplit(offer.url).path.split("/")
        try:
            organization = parts[parts.index("companies") + 1]
            job = parts[parts.index("jobs") + 1]
        except (ValueError, IndexError) as error:
            raise SourceFailedError(
                f"L'adresse de l'offre {LABEL} n'est pas reconnue."
            ) from error
        data = self._http.get_json(
            LABEL,
            DETAIL_URL.format(
                organization=quote(organization, safe=""), job=quote(job, safe="")
            ),
            params={"o": offer.external_id},
            headers={**HEADERS, "Referer": offer.url},
        )
        detail = data.get("job") if isinstance(data, dict) else None
        if not isinstance(detail, dict):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        return _completed(offer, detail)


def _offer(item: dict[str, Any]) -> CollectedOffer | None:
    reference, title, slug = (
        text(item.get(key)) for key in ("reference", "name", "slug")
    )
    organization = as_mapping(item.get("organization"))
    organization_slug = text(organization.get("slug"))
    if reference is None or title is None or slug is None or organization_slug is None:
        return None
    office = as_mapping(item.get("office"))
    url = f"{WEBSITE}/fr/companies/{organization_slug}/jobs/{slug}"
    return CollectedOffer(
        source=SourceCode.WTTJ,
        external_id=reference,
        url=url,
        application_url=url,
        title=title,
        company=text(organization.get("name")),
        location=text(office.get("city")),
        country=text(office.get("country_code")),
        contract=text(item.get("contract_type")),
        remote=text(item.get("remote")),
        salary_min=number(item.get("salary_min")),
        salary_max=number(item.get("salary_max")),
        salary_currency=text(item.get("salary_currency")),
        salary_period=text(item.get("salary_period")),
        sector=text(organization.get("industry")),
        published_on=iso_date(item.get("published_at")),
        description="",
        description_complete=False,
        incomplete_reason=NO_DESCRIPTION_REASON,
    )


def _completed(offer: CollectedOffer, detail: dict[str, Any]) -> CollectedOffer:
    sections = [
        (heading, html_to_text(detail.get(key))) for heading, key in DETAIL_SECTIONS
    ]
    missions = [
        html_to_text(mission)
        for mission in detail.get("key_missions") or []
        if html_to_text(mission)
    ]
    if missions:
        sections.insert(
            1, ("Missions clés", "\n".join(f"- {mission}" for mission in missions))
        )
    description = "\n\n".join(
        f"{heading}\n{body}" for heading, body in sections if body
    )
    if not description:
        return offer
    return replace(
        offer,
        description=description,
        description_complete=True,
        incomplete_reason=None,
        application_url=text(detail.get("apply_url")) or offer.application_url,
    )
