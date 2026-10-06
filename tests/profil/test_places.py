from __future__ import annotations

import pytest

from rocky.profil.places import (
    PlaceKind,
    describe,
    posting_place,
    track_zone,
    unknown_locations,
)


@pytest.mark.parametrize(
    ("text", "read_as", "shown"),
    [
        ("Paris 01 - 75", "Paris 01", ["Paris (Paris)"]),
        ("Courbevoie - 92", "Courbevoie", ["Courbevoie (Hauts-de-Seine)"]),
        ("Chartres - 28", "Chartres", ["Chartres (Eure-et-Loir)"]),
        ("Paris (75)", "Paris", ["Paris (Paris)"]),
        ("Lyon 01 - 69", "Lyon 01", ["Lyon (Rhône)"]),
        ("8ème Arrondissement, Paris", "Paris", ["Paris"]),
        ("Val-d'Oise, Ile-de-France", "Val-d'Oise", ["Val-d'Oise"]),
        ("Levallois-Perret", "Levallois-Perret", ["Levallois-Perret (Hauts-de-Seine)"]),
        (
            "Vélizy-Villacoublay, France",
            "Vélizy-Villacoublay",
            ["Vélizy-Villacoublay (Yvelines)"],
        ),
        ("Ville de Paris", "Ville de Paris", ["Paris (Paris)"]),
        (
            "Paris et périphérie",
            "Paris et périphérie",
            ["Paris", "Hauts-de-Seine", "Seine-Saint-Denis", "Val-de-Marne"],
        ),
        ("La Défense, Courbevoie", "La Défense", ["Hauts-de-Seine"]),
        ("Aéroport Paris-Roissy-Charles-de-Gaulle (95)", "95", ["Val-d'Oise"]),
        ("Corbeil-Essonnes 91100", "Corbeil-Essonnes", ["Corbeil-Essonnes (Essonne)"]),
        ("Bretagne", "Bretagne", ["Bretagne"]),
    ],
)
def test_a_posting_place_is_read_in_the_reference(
    text: str, read_as: str, shown: list[str]
) -> None:
    reading = posting_place(text)

    assert reading is not None
    assert reading.read_as == read_as
    assert [describe(place) for place in reading.places] == shown


def test_a_homonym_gives_every_commune_of_that_name() -> None:
    reading = posting_place("Montreuil")

    assert reading is not None
    assert reading.homonyms
    assert {place.departement for place in reading.places} == {"28", "85", "93"}


def test_a_departement_code_picks_the_commune_among_homonyms() -> None:
    reading = posting_place("Montreuil - 93")

    assert reading is not None
    assert [describe(place) for place in reading.places] == [
        "Montreuil (Seine-Saint-Denis)"
    ]


@pytest.mark.parametrize("text", ["", "London", "New York", "Remote"])
def test_an_unknown_place_is_none(text: str) -> None:
    assert posting_place(text) is None


@pytest.mark.parametrize(
    ("label", "kind", "name"),
    [
        ("Ile de France", PlaceKind.REGION, "Île-de-France"),
        ("IDF", PlaceKind.REGION, "Île-de-France"),
        ("Eure et Loir", PlaceKind.DEPARTEMENT, "Eure-et-Loir"),
        ("eure-et-loir", PlaceKind.DEPARTEMENT, "Eure-et-Loir"),
        ("28", PlaceKind.DEPARTEMENT, "Eure-et-Loir"),
        ("Paris", PlaceKind.DEPARTEMENT, "Paris"),
        ("Centre", PlaceKind.REGION, "Centre-Val de Loire"),
        ("Chartres", PlaceKind.COMMUNE, "Chartres"),
    ],
)
def test_a_track_location_names_a_zone(label: str, kind: PlaceKind, name: str) -> None:
    zone = track_zone(label)

    assert zone is not None
    assert [(place.kind, place.name) for place in zone.places] == [(kind, name)]


def test_a_zone_covers_the_places_inside_it() -> None:
    region, departement, commune = (
        track_zone("Ile de France"),
        track_zone("Eure-et-Loir"),
        track_zone("Chartres"),
    )
    courbevoie, chartres, paris = (
        posting_place("Courbevoie - 92"),
        posting_place("Chartres - 28"),
        posting_place("Paris 08 - 75"),
    )
    assert region and departement and commune and courbevoie and chartres and paris

    assert region.covers(courbevoie.places[0])
    assert region.covers(paris.places[0])
    assert not region.covers(chartres.places[0])
    assert departement.covers(chartres.places[0])
    assert commune.covers(chartres.places[0])
    assert not commune.covers(courbevoie.places[0])


def test_a_commune_alone_in_its_departement_covers_that_departement() -> None:
    commune = track_zone("Ville de Paris")
    departement = posting_place("Paris")
    assert commune and departement

    assert departement.places[0].kind == PlaceKind.DEPARTEMENT
    assert commune.covers(departement.places[0])


def test_a_name_is_never_corrected() -> None:
    # "Eure et Loire" is not "Eure-et-Loir", and must not become the département of the Loire (Q3).
    assert track_zone("Eure et Loire") is None


def test_unknown_locations_leave_france_and_blanks_out() -> None:
    assert unknown_locations(["Ile de France", "Eure et Loire", "France", " "]) == (
        "Eure et Loire",
    )


def test_an_alias_gives_way_to_the_departement_written() -> None:
    renamed, elsewhere = posting_place("Saint-Ouen"), posting_place("Saint-Ouen - 41")
    assert renamed and elsewhere

    assert [describe(place) for place in renamed.places] == [
        "Saint-Ouen-sur-Seine (Seine-Saint-Denis)"
    ]
    assert [describe(place) for place in elsewhere.places] == [
        "Saint-Ouen (Loir-et-Cher)"
    ]
