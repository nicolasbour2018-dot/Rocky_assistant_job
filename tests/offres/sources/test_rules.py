from __future__ import annotations

import csv
from datetime import date

import pytest

from rocky.offres.sources.model import SearchQuery
from rocky.offres.sources.rules import (
    html_to_text,
    iso_date,
    number,
    queries_for_track,
    source_for_url,
    unique_queries,
    unix_date,
)

# Source names recorded by the old Rocky (archive A1, job_offers.source_name) when an offer came from a URL.
ARCHIVE_NAMES = """url,expected
https://www.hellowork.com/fr-fr/emplois/1.html,hellowork.com
https://www.efinancialcareers.fr/emplois-France/1,efinancialcareers.fr
https://www.cadremploi.fr/emploi/detail_offre?offreId=1,cadremploi.fr
https://recrutement.groupe-vyv.fr/offre/1,recrutement.groupe-vyv.fr
https://www.free-work.com/fr/tech-it/1,free-work.com
https://eyglobal.yello.co/jobs/1,eyglobal.yello.co
https://www.croix-rouge.fr/offre/1,croix-rouge.fr
https://emertongroup.recruitee.com/o/1,emertongroup.recruitee.com
https://fr.indeed.com/viewjob?from=app-tracker-saved-appcard&hl=fr&jk=f49e1ba56a0643db,indeed.com
https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/1W,apec
https://fr.linkedin.com/jobs/view/1,linkedin
https://www.welcometothejungle.com/fr/companies/a/jobs/b,wttj
https://wellfound.com/jobs/1-data,wellfound
https://www.adzuna.fr/details/1,adzuna
https://candidat.francetravail.fr/offres/recherche/detail/1,france_travail
"""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (row["url"], row["expected"])
        for row in csv.DictReader(ARCHIVE_NAMES.splitlines())
    ],
)
def test_source_for_url_names_a_site_never_by_its_whole_address(
    url: str, expected: str
) -> None:
    assert source_for_url(url) == expected


@pytest.mark.parametrize("url", ["", "pas une adresse", "https://localhost/offre"])
def test_source_for_url_without_host(url: str) -> None:
    assert source_for_url(url) is None


def test_queries_for_track_cross_titles_and_locations() -> None:
    assert queries_for_track(
        ["Data analyst", " ", "BI analyst"], ["Paris", "Lyon"]
    ) == [
        SearchQuery("Data analyst", "Paris"),
        SearchQuery("Data analyst", "Lyon"),
        SearchQuery("BI analyst", "Paris"),
        SearchQuery("BI analyst", "Lyon"),
    ]
    assert queries_for_track(["Data analyst"], []) == [SearchQuery("Data analyst")]


def test_unique_queries_drop_repeats_and_locations_a_source_ignores() -> None:
    queries = [
        SearchQuery("Data analyst", "Paris"),
        SearchQuery("data analyst", "paris"),
        SearchQuery("Data analyst", "Lyon"),
    ]

    assert unique_queries(queries, filters_location=True) == queries[::2]
    assert unique_queries(queries, filters_location=False) == [
        SearchQuery("Data analyst")
    ]


def test_conversions() -> None:
    assert iso_date("2026-09-25T07:51:29.000+0000") == date(2026, 9, 25)
    assert iso_date("2026-09-25T07:51:29Z") == date(2026, 9, 25)
    assert iso_date("hier") is None
    assert unix_date(1_728_432_000) == date(2024, 10, 9)
    assert unix_date("jamais") is None
    assert number("42000.5") == 42000.5
    assert number(True) is None


def test_html_to_text_keeps_paragraphs_and_list_items() -> None:
    html = (
        "<p>Missions :</p><ul><li>Concevoir des tableaux de bord <strong>Power BI</strong></li>"
        "<li>Modéliser</li></ul><p>Profil<br>SQL</p>"
    )

    assert html_to_text(html) == (
        "Missions :\n\n- Concevoir des tableaux de bord Power BI\n\n- Modéliser\n\nProfil\nSQL"
    )
