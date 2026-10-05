"""France Travail: the official "Offres d'emploi v2" API (OAuth client credentials).

Waiting for access (D8): the source is ``pending_access`` until ``ROCKY_FRANCE_TRAVAIL_ENABLED`` is ``true``, and
is then never called. Locations need the INSEE codes of the API: they come with the access, the source searches
titles alone meanwhile.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sources.rules import as_mapping, iso_date, number, text

LABEL = SOURCE_LABELS[SourceCode.FRANCE_TRAVAIL]
TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"  # noqa: S105  (an address)
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"
MAX_RESULTS = 150
# Seconds; France Travail gives about 1500 in expires_in.
DEFAULT_TOKEN_LIFETIME = 1200.0
TOKEN_MARGIN = 60.0


class FranceTravailSource:
    code = SourceCode.FRANCE_TRAVAIL
    filters_location = False

    def __init__(
        self,
        http: PublicHttp,
        *,
        enabled: bool,
        client_id: str | None,
        client_secret: str | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._enabled = enabled
        self._client_id = client_id
        self._client_secret = client_secret
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    def availability(self) -> Availability:
        if not self._enabled:
            return Availability.PENDING_ACCESS
        if self._client_id and self._client_secret:
            return Availability.READY
        return Availability.NOT_CONFIGURED

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        count = min(max(limit, 1), MAX_RESULTS)
        data = self._http.get_json(
            LABEL,
            SEARCH_URL,
            params={"motsCles": query.title},
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Range": f"offres=0-{count - 1}",
            },
        )
        if data is None:  # 204: nothing matches
            return []
        items = data.get("resultats") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        offers = (_offer(item) for item in items if isinstance(item, dict))
        return [offer for offer in offers if offer is not None][:limit]

    def _access_token(self) -> str:
        """A short-lived token, asked again a minute before it expires (the watch keeps its sources)."""
        if self._token is None or self._clock() >= self._token_expires_at:
            if not self._client_id or not self._client_secret:
                raise SourceFailedError(f"Les identifiants {LABEL} sont absents.")
            data = self._http.post_form(
                LABEL,
                TOKEN_URL,
                {
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": SCOPE,
                },
            )
            token = text(data.get("access_token")) if isinstance(data, dict) else None
            if token is None:
                raise SourceFailedError(f"{LABEL} n'a pas délivré de jeton d'accès.")
            lifetime = number(data.get("expires_in")) or DEFAULT_TOKEN_LIFETIME
            self._token = token
            self._token_expires_at = self._clock() + lifetime - TOKEN_MARGIN
        return self._token


def _offer(item: dict[str, Any]) -> CollectedOffer | None:
    identifier, title = text(item.get("id")), text(item.get("intitule"))
    if identifier is None or title is None:
        return None
    company, place, origin, salary, contact = (
        as_mapping(item.get(key))
        for key in ("entreprise", "lieuTravail", "origineOffre", "salaire", "contact")
    )
    url = (
        text(origin.get("urlOrigine"))
        or f"https://candidat.francetravail.fr/offres/recherche/detail/{identifier}"
    )
    description = text(item.get("description")) or ""
    return CollectedOffer(
        source=SourceCode.FRANCE_TRAVAIL,
        external_id=identifier,
        url=url,
        application_url=text(contact.get("urlPostulation")) or url,
        title=title,
        company=text(company.get("nom")),
        location=text(place.get("libelle")),
        country="France",
        contract=text(item.get("typeContratLibelle")) or text(item.get("typeContrat")),
        remote=text(item.get("typeLieuTravail")),
        salary_text=text(salary.get("libelle")),
        sector=text(item.get("secteurActiviteLibelle")),
        published_on=iso_date(item.get("dateCreation")),
        description=description,
        description_complete=bool(description),
        incomplete_reason=None
        if description
        else f"{LABEL} ne donne pas la description de cette offre.",
    )
