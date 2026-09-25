"""Apec: the public search webservice of apec.fr, filtered by Apec's own location reference.

The search gives an excerpt of about 280 characters. The public detail endpoint gives the full posting, but Apec
protects it with DataDome most of the time: a refusal leaves the offer incomplete (no browser, no challenge).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    CollectedOffer,
    InvalidLinkError,
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sources.rules import html_to_text, iso_date, same_place, text
from rocky.profil.rules import normalize_term

LABEL = SOURCE_LABELS[SourceCode.APEC]
SEARCH_URL = "https://www.apec.fr/cms/webservices/rechercheOffre"
PLACES_URL = "https://www.apec.fr/cms/webservices/autocompletion/lieuautocomplete"
DETAIL_URL = "https://www.apec.fr/cms/webservices/offre/public"
# Labels of Apec's codes (contract, remote work), as the apec.fr pages read them (C3, Q8).
REFERENCE_URL = "https://www.apec.fr/cms/webservices/referentielstatique/presentations/code/{code}/visuels"
SEARCH_PAGE = "https://www.apec.fr/candidat/recherche-emploi.html/emploi"
OFFER_PAGE = f"{SEARCH_PAGE}/detail-offre"
EXCERPT_REASON = (
    "Apec ne donne qu'un extrait de l'annonce dans ses résultats de recherche."
)
NO_DETAIL_REASON = "Apec n'a pas donné le détail de cette annonce."
# Labels of Apec's codes, from its public reference lists captured on 25/09/2026 (docs/procedures/c1-captures/
# apec_referentiel.py, tests/offres/sources/data/apec/referentiel-*.json). A code missing here stays empty.
CONTRACT_LABELS = {
    101888: "CDI",
    101887: "CDD",
    20053: "Alternance",
    597137: "CDD - Alternance - Contrat d'apprentissage",
    597138: "CDD - Alternance - Contrat de professionnalisation",
    597139: "CDI - Alternance - Contrat d'apprentissage",
    597140: "CDI - Alternance - Contrat de professionnalisation",
    101930: "Intérim",
    597141: "CDI interimaire",
    101889: "Mission d'intérim",
    597171: "Stage",
}
REMOTE_LABELS = {
    20766: "Ponctuel autorisé",
    20765: "Partiel possible",
    20767: "Total possible",
    20949: "Non autorisé",
}
# Offer numbers as Apec writes them (``179271987W``).
OFFER_NUMBER = re.compile(r"\d+[A-Z]?")
MAX_RESULTS = 100
# When one label names several places (Île-de-France is a region and a "grande région"), the widest wins.
PLACE_PRIORITY = (
    "FR_REGION",
    "FR_GRANDE_REGION",
    "FR_DEPARTEMENT",
    "FR_COMMUNE_A_ARRONDISSEMENT",
    "FR_COMMUNE",
)


class ApecSource:
    code = SourceCode.APEC
    filters_location = True

    def __init__(self, http: PublicHttp) -> None:
        self._http = http
        # Label (as a term) → Apec identifier, or the reason why Apec cannot use it.
        self._places: dict[str, str | QuerySkippedError] = {}

    def availability(self) -> Availability:
        return Availability.READY

    def search(self, query: SearchQuery, limit: int) -> list[CollectedOffer]:
        places = [] if query.location is None else [self._place_id(query.location)]
        data = self._http.post_json(
            LABEL,
            SEARCH_URL,
            _payload(query.title, places, limit),
            headers={"Referer": SEARCH_PAGE},
        )
        items = data.get("resultats") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        offers = (_offer(item) for item in items if isinstance(item, dict))
        return [offer for offer in offers if offer is not None][:limit]

    def complete(self, offer: CollectedOffer) -> CollectedOffer:
        data = self._http.get_json(
            LABEL,
            DETAIL_URL,
            params={"numeroOffre": offer.external_id},
            headers={"Referer": offer.url},
        )
        if not isinstance(data, dict):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        return _completed(offer, data)

    def from_link(self, url: str) -> CollectedOffer:
        """The offer of an Apec posting page (``…/detail-offre/<numéro>``): the page itself is an empty shell."""
        path = urlsplit(url).path.rstrip("/")
        number = path.rsplit("/", 1)[-1] if "/detail-offre/" in path else ""
        if not OFFER_NUMBER.fullmatch(number):
            raise InvalidLinkError(
                f"Ce lien {LABEL} ne désigne pas une annonce (il faut le lien de sa fiche)."
            )
        page = f"{OFFER_PAGE}/{number}"
        return CollectedOffer(
            source=SourceCode.APEC,
            external_id=number,
            url=page,
            application_url=page,
            title="",
            country="France",
            description="",
            description_complete=False,
            incomplete_reason=NO_DETAIL_REASON,
        )

    def _place_id(self, label: str) -> str:
        """Apec identifier of a location label; the reference is asked once per label and per collection."""
        key = normalize_term(label)
        if key not in self._places:
            candidates = self._matching_places(label, label)
            if not candidates:
                # The reference answers four names at most, in alphabetical order: "Paris" only comes out
                # of "Paris -" ("Paris - 75"), after "Cormeilles-en-Parisis - 95" and the like.
                candidates = self._matching_places(label, f"{label} -")
            try:
                self._places[key] = _chosen_place(label, candidates)
            except QuerySkippedError as skipped:
                # Every job title of the track would ask again for the same answer.
                self._places[key] = skipped
        place = self._places[key]
        if isinstance(place, QuerySkippedError):
            raise QuerySkippedError(place.reason)
        return place

    def _matching_places(self, label: str, search: str) -> list[dict[str, Any]]:
        data = self._http.get_json(
            LABEL, PLACES_URL, params={"q": search}, headers={"Referer": SEARCH_PAGE}
        )
        if not isinstance(data, list):
            raise SourceFailedError(f"{LABEL} a renvoyé une réponse inattendue.")
        return [
            place
            for place in data
            if isinstance(place, dict)
            and place.get("lieuId") is not None
            and _names_place(label, str(place.get("lieuDisplay") or ""))
        ]


def _names_place(label: str, display: str) -> bool:
    """ "Paris", "paris - 75" and "Paris - 75" all name "Paris - 75"."""
    return same_place(label, display) or same_place(label, display.split(" - ")[0])


def _chosen_place(label: str, candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        raise QuerySkippedError(f"Lieu non reconnu par {LABEL} : « {label} ».")
    rank = {kind: position for position, kind in enumerate(PLACE_PRIORITY)}
    best = min(rank.get(str(place.get("lieuType")), len(rank)) for place in candidates)
    widest = [
        place
        for place in candidates
        if rank.get(str(place.get("lieuType")), len(rank)) == best
    ]
    if len(widest) > 1:
        names = ", ".join(f"« {place['lieuDisplay']} »" for place in widest)
        raise QuerySkippedError(
            f"Lieu ambigu pour {LABEL} : « {label} » désigne {names}. "
            "Précise-le dans la piste, par exemple avec son département."
        )
    return str(widest[0]["lieuId"])


def _payload(title: str, places: list[str], limit: int) -> dict[str, Any]:
    """The criteria of the public search form, with only keywords and location filled in."""
    return {
        "motsCles": title,
        "lieux": places,
        "fonctions": [],
        "statutPoste": [],
        "typesContrat": [],
        "typesConvention": [],
        "niveauxExperience": [],
        "idsEtablissement": [],
        "secteursActivite": [],
        "typesTeletravail": [],
        "idNomZonesDeplacement": [],
        "positionNumbersExcluded": [],
        "typeClient": "CADRE",
        "sorts": [{"type": "DATE", "direction": "DESCENDING"}],
        "pagination": {"range": min(max(limit, 1), MAX_RESULTS), "startIndex": 0},
        "activeFiltre": True,
        "pointGeolocDeReference": {},
    }


def _offer(item: dict[str, Any]) -> CollectedOffer | None:
    number = text(item.get("numeroOffre"))
    title = text(item.get("intitule"))
    if number is None or title is None:
        return None
    url = f"{OFFER_PAGE}/{number}"
    return CollectedOffer(
        source=SourceCode.APEC,
        external_id=number,
        url=url,
        application_url=url,
        title=title,
        company=text(item.get("nomCommercial")),
        location=text(item.get("lieuTexte")),
        country="France",
        contract=_label(CONTRACT_LABELS, item.get("typeContrat")),
        remote=_label(REMOTE_LABELS, item.get("idNomTeletravail")),
        salary_text=text(item.get("salaireTexte")),
        published_on=iso_date(item.get("datePublication")),
        description=text(item.get("texteOffre")) or "",
        description_complete=False,
        incomplete_reason=EXCERPT_REASON,
    )


def _label(labels: Mapping[int, str], code: object) -> str | None:
    """The label of an Apec code (a number, sometimes sent as text); ``None`` for a code nobody knows."""
    if isinstance(code, str) and code.isdigit():
        code = int(code)
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return labels.get(code)


def _completed(offer: CollectedOffer, data: dict[str, Any]) -> CollectedOffer:
    sections = [
        (heading, html_to_text(data.get(key)))
        for heading, key in (
            ("", "texteHtml"),
            ("Profil recherché", "texteHtmlProfil"),
            ("Entreprise", "texteHtmlEntreprise"),
        )
    ]
    description = "\n\n".join(
        f"{heading}\n{body}" if heading else body for heading, body in sections if body
    )
    if not description:
        return offer
    # An offer designated by a link (import, C2) knows nothing yet; the facts found by the search stay as they are.
    return replace(
        offer,
        title=offer.title or text(data.get("intitule")) or "",
        company=offer.company
        or text(data.get("nomCommercial"))
        or text(data.get("enseigne")),
        location=offer.location or text(data.get("lieuTexte")),
        description=description,
        description_complete=True,
        incomplete_reason=None,
        salary_text=text(data.get("salaireTexte")) or offer.salary_text,
    )
