"""French places: what a track location covers, and where a posting is (decision G2, lieux et date limite).

The reference is the INSEE Code officiel géographique (``data/lieux-cog-2026.csv``, built by
``docs/procedures/g2-lieux/build.py``), read once, without network. Pure functions: a name is compared as a term
(``normalize_term``), never corrected (Q3: "Loire" would answer the département of the Loire).
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

from rocky.profil.rules import normalize_term

REFERENCE = Path(__file__).parent / "data" / "lieux-cog-2026.csv"
# "France" covers the whole country: the score reads it apart, it is not a place of the reference.
FRANCE_KEYS = frozenset({"france", "fr", "fra"})
# Remote work written as a track location (the form suggests it): not a place, never reported as unknown.
REMOTE_KEYS = frozenset(
    {"teletravail", "teletravail complet", "full remote", "remote", "a distance"}
)


class PlaceKind(StrEnum):
    REGION = "region"
    DEPARTEMENT = "departement"
    COMMUNE = "commune"


@dataclass(frozen=True)
class Place:
    """A place of the reference: a région, a département or a commune (an arrondissement reads as its commune)."""

    kind: PlaceKind
    name: str
    region: str
    departement: str = ""
    commune: str = ""


@dataclass(frozen=True)
class Zone:
    """What a track location covers: some places of the reference (an alias may name several)."""

    label: str
    places: tuple[Place, ...]

    def covers(self, place: Place) -> bool:
        return any(_covers(zone, place) for zone in self.places)


@dataclass(frozen=True)
class PostingPlace:
    """Where a posting is, read in the reference: the places its text may name (several for a homonym, Q4)."""

    places: tuple[Place, ...]
    # The words that named it, as written ("Courbevoie", "92").
    read_as: str

    @property
    def homonyms(self) -> bool:
        return len(self.places) > 1


# Names the reference does not know, written once (Q12). Codes of the reference: régions, départements, communes.
_ALIASES: dict[str, tuple[tuple[PlaceKind, str], ...]] = {
    "idf": ((PlaceKind.REGION, "11"),),
    "region parisienne": ((PlaceKind.REGION, "11"),),
    "ville de paris": ((PlaceKind.COMMUNE, "75056"),),
    "paris et peripherie": tuple(
        (PlaceKind.DEPARTEMENT, code) for code in ("75", "92", "93", "94")
    ),
    "petite couronne": tuple(
        (PlaceKind.DEPARTEMENT, code) for code in ("92", "93", "94")
    ),
    "paris la defense": ((PlaceKind.DEPARTEMENT, "92"),),
    "la defense": ((PlaceKind.DEPARTEMENT, "92"),),
    # Renamed Saint-Ouen-sur-Seine in 2018, still written "Saint-Ouen" by the postings.
    "saint ouen": ((PlaceKind.COMMUNE, "93070"),),
    # Régions before 2016.
    "centre": ((PlaceKind.REGION, "24"),),
    "alsace": ((PlaceKind.REGION, "44"),),
    "lorraine": ((PlaceKind.REGION, "44"),),
    "champagne ardenne": ((PlaceKind.REGION, "44"),),
    "aquitaine": ((PlaceKind.REGION, "75"),),
    "limousin": ((PlaceKind.REGION, "75"),),
    "poitou charentes": ((PlaceKind.REGION, "75"),),
    "midi pyrenees": ((PlaceKind.REGION, "76"),),
    "languedoc roussillon": ((PlaceKind.REGION, "76"),),
    "auvergne": ((PlaceKind.REGION, "84"),),
    "rhone alpes": ((PlaceKind.REGION, "84"),),
    "bourgogne": ((PlaceKind.REGION, "27"),),
    "franche comte": ((PlaceKind.REGION, "27"),),
    "basse normandie": ((PlaceKind.REGION, "28"),),
    "haute normandie": ((PlaceKind.REGION, "28"),),
    "nord pas de calais": ((PlaceKind.REGION, "32"),),
    "picardie": ((PlaceKind.REGION, "32"),),
    "paca": ((PlaceKind.REGION, "93"),),
}
# "St-Denis" is "Saint-Denis".
_ABBREVIATIONS = {"st": "saint", "ste": "sainte"}
# A département code ("92", "2A", "971") after a dash or in brackets, at the end; or a postal code.
_DEPARTEMENT_CODE = re.compile(
    r"(?:\s-\s*|\()\s*(\d{2,3}|2[abAB])\s*\)?\s*$|\b(\d{5})\b", re.ASCII
)
# "Paris 08", "Lyon 1er", "Paris 8ème arrondissement": the commune without its arrondissement.
_ARRONDISSEMENT = re.compile(
    r"\s+\d{1,2}(?:\s*(?:er|e|eme|em))?(?:\s+arrondissement)?$", re.ASCII
)


@dataclass(frozen=True)
class _Reference:
    regions: dict[str, Place]
    departements: dict[str, Place]
    communes: dict[str, Place]
    by_name: dict[
        str, tuple[Place, ...]
    ]  # term → regions, then départements, then communes
    communes_by_departement: dict[str, int]


def _key(name: str) -> str:
    words = normalize_term(name).split()
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words)


@cache
def _reference() -> _Reference:
    regions: dict[str, Place] = {}
    departements: dict[str, Place] = {}
    communes: dict[str, Place] = {}
    names: dict[str, list[Place]] = defaultdict(list)
    count: dict[str, int] = defaultdict(int)
    with REFERENCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            kind = row["type"]
            if kind == "region":
                place = Place(PlaceKind.REGION, row["nom"], row["region"])
                regions[row["code"]] = place
            elif kind == "departement":
                place = Place(
                    PlaceKind.DEPARTEMENT, row["nom"], row["region"], row["departement"]
                )
                departements[row["code"]] = place
            else:
                place = Place(
                    PlaceKind.COMMUNE,
                    row["nom"],
                    row["region"],
                    row["departement"],
                    row["commune"],
                )
                if kind == "commune":
                    communes[row["code"]] = place
                    count[row["departement"]] += 1
            names[_key(row["nom"])].append(place)
    # The widest first: "Paris" is the département before the commune (they cover the same place).
    order = list(PlaceKind)
    by_name = {
        name: tuple(sorted(places, key=lambda place: order.index(place.kind)))
        for name, places in names.items()
    }
    return _Reference(regions, departements, communes, by_name, dict(count))


def _covers(zone: Place, place: Place) -> bool:
    if zone.kind == PlaceKind.REGION:
        return place.region == zone.region
    if zone.kind == PlaceKind.DEPARTEMENT:
        return bool(place.departement) and place.departement == zone.departement
    if place.kind == PlaceKind.COMMUNE:
        return place.commune == zone.commune
    # A commune alone in its département covers that département (Paris, 75).
    return (
        place.kind == PlaceKind.DEPARTEMENT
        and place.departement == zone.departement
        and _reference().communes_by_departement.get(zone.departement) == 1
    )


def _aliased(key: str) -> tuple[Place, ...]:
    reference = _reference()
    tables = {
        PlaceKind.REGION: reference.regions,
        PlaceKind.DEPARTEMENT: reference.departements,
        PlaceKind.COMMUNE: reference.communes,
    }
    return tuple(tables[kind][code] for kind, code in _ALIASES.get(key, ()))


@cache
def track_zone(label: str) -> Zone | None:
    """What a track location covers: a région, a département (name or number), a commune; None when unknown (Q3).

    "France" is not a zone of the reference: the score reads it apart (it never covers a posting abroad).
    """
    key = _key(label)
    if not key:
        return None
    if aliased := _aliased(key):
        return Zone(label, aliased)
    reference = _reference()
    if code := _departement_code(label):
        return Zone(label, (reference.departements[code],))
    places = reference.by_name.get(key, ())
    if not places:
        return None
    # A name of several kinds is the widest (Q2); several communes of that name are all covered.
    widest = places[0].kind
    return Zone(label, tuple(place for place in places if place.kind == widest))


def unknown_locations(locations: Iterable[str]) -> tuple[str, ...]:
    """The track locations the reference does not know, besides "France" and remote work: compared word for word
    (Q3, Q15)."""
    return tuple(
        location
        for location in locations
        if location.strip()
        and _key(location) not in FRANCE_KEYS | REMOTE_KEYS
        and track_zone(location) is None
    )


@cache
def posting_place(text: str) -> PostingPlace | None:
    """Where a posting's place text is, in the reference, or None (Q4).

    In order: a département code ("- 92", "(95)", a postal code) narrows the name next to it; the whole text, then each
    part between commas, read as a name of the reference (an alias, a région, a département, a commune); a code alone
    gives its département.
    """
    text = text.strip()
    if not text:
        return None
    reference = _reference()
    match = _DEPARTEMENT_CODE.search(text)
    code: str | None = None
    if match:
        written, postal = match.groups()
        code = _departement_code(written) if written else _postal_departement(postal)
        text = (text[: match.start()] + text[match.end() :]).strip(" -,")
    parts = [text, *(part for part in text.split(",") if part.strip() != text)]
    for part in parts:
        key = _key(part)
        if not key:
            continue
        # An alias gives way to a département code that contradicts it ("Saint-Ouen - 41").
        aliased = tuple(
            place
            for place in _aliased(key)
            if code is None or place.departement in ("", code)
        )
        places = aliased or _named(key, code)
        if not places and (shorter := _ARRONDISSEMENT.sub("", key)) != key:
            places = _named(shorter, code)
        if places:
            return PostingPlace(places, part.strip())
    if code is not None:
        return PostingPlace((reference.departements[code],), code)
    return None


def _named(key: str, code: str | None) -> tuple[Place, ...]:
    """The places of that name; with a département code, only those in it (a commune of the département first)."""
    places = _reference().by_name.get(key, ())
    if code is None:
        widest = places[0].kind if places else None
        return tuple(place for place in places if place.kind == widest)
    inside = [place for place in places if place.departement == code]
    communes = [place for place in inside if place.kind == PlaceKind.COMMUNE]
    return tuple(communes[:1] or inside[:1])


def _postal_departement(postal: str) -> str | None:
    """The département of a postal code: "92400" is 92, "97400" is 974; Corsica ("20…") is two, hence None."""
    if postal.startswith("20"):
        return None
    return _departement_code(postal[:3] if postal.startswith("97") else postal[:2])


def _departement_code(value: str) -> str | None:
    """The reference code of a département written as a number ("92", "2a", "971"), or None; ASCII digits only
    ("²" is not 2)."""
    code = value.strip().upper()
    if not code.isascii():
        return None
    if code.isdigit() and len(code) == 1:
        code = f"0{code}"
    return code if code in _reference().departements else None


def describe(place: Place) -> str:
    """How a place is shown in the score detail: "Courbevoie (Hauts-de-Seine)", "Hauts-de-Seine", "Île-de-France"."""
    if place.kind == PlaceKind.COMMUNE:
        departement = _reference().departements.get(place.departement)
        return f"{place.name} ({departement.name})" if departement else place.name
    return place.name
