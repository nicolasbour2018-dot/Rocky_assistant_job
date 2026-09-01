import json

import pytest
import requests

from dashboard.rocky.config import Settings
from dashboard.rocky.errors import SourceError
from dashboard.rocky.models import CandidateProfile
from dashboard.rocky.sources.adzuna import AdzunaSource
from dashboard.rocky.sources.apec import ApecSource
from dashboard.rocky.sources.france_travail import FranceTravailSource
from dashboard.rocky.sources.indeed import IndeedSource
from dashboard.rocky.sources.linkedin import LinkedInSource
from dashboard.rocky.sources.registry import build_watch_sources
from dashboard.rocky.sources.wellfound import WellfoundSource
from dashboard.rocky.sources.wttj import WelcomeToTheJungleSource


def test_adzuna_mapping():
    offer = AdzunaSource._offer(
        {
            "id": "123",
            "title": "Data Analyst",
            "description": "Python et SQL",
            "redirect_url": "https://adzuna.example/123",
            "created": "2026-08-01T10:00:00Z",
            "company": {"display_name": "Exemple"},
            "location": {"display_name": "Paris"},
            "salary_min": 40_000,
            "salary_max": 45_000,
            "contract_type": "permanent",
            "contract_time": "full_time",
        }
    )
    assert offer.external_id == "123"
    assert offer.company_name == "Exemple"
    assert offer.publication_date.isoformat() == "2026-08-01"
    assert offer.contract_type == "CDI"
    assert offer.work_schedule == "Temps plein"


def test_france_travail_mapping():
    offer = FranceTravailSource._offer(
        {
            "id": "FT42",
            "intitule": "Data Scientist",
            "description": "Machine learning et Python",
            "typeContratLibelle": "CDI",
            "dureeTravailLibelleConverti": "Temps plein",
            "dateCreation": "2026-08-01T08:00:00Z",
            "entreprise": {"nom": "Exemple"},
            "lieuTravail": {"libelle": "75 - Paris"},
            "salaire": {"libelle": "Annuel de 40000 à 45000 Euros"},
            "origineOffre": {"urlOrigine": "https://example.org/ft42"},
        }
    )
    assert offer.external_id == "FT42"
    assert offer.salary_min == 40_000
    assert offer.salary_max == 45_000
    assert offer.contract_type == "CDI"
    assert offer.work_schedule == "Temps plein"


def test_france_travail_oauth_diagnostic_uses_allowlist():
    response = requests.Response()
    response.status_code = 400
    response._content = b'{"error": "invalid_scope"}'
    assert FranceTravailSource._oauth_error_code(response) == "invalid_scope"

    response._content = b'{"error": "CLIENT_SECRET_VALUE"}'
    assert FranceTravailSource._oauth_error_code(response) is None


def test_adzuna_errors_never_expose_credentials(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("https://api.adzuna.com/?app_key=SUPER_SECRET")

    monkeypatch.setattr("dashboard.rocky.sources.adzuna.requests.get", fail)
    source = AdzunaSource(Settings(adzuna_app_id="id", adzuna_app_key="SUPER_SECRET"))
    with pytest.raises(SourceError) as captured:
        source.search(
            CandidateProfile(id=1, profile_name="Data"),
            results_per_query=1,
        )
    assert "SUPER_SECRET" not in str(captured.value)


def test_linkedin_public_cards_mapping():
    html = """
    <div class="base-search-card" data-entity-urn="urn:li:jobPosting:42">
      <a class="base-card__full-link"
         href="https://fr.linkedin.com/jobs/view/data-analyst-42?trackingId=x"></a>
      <h3 class="base-search-card__title">Data Analyst</h3>
      <h4 class="base-search-card__subtitle">Rocky Data</h4>
      <span class="job-search-card__location">Paris, France</span>
      <time datetime="2026-08-06"></time>
    </div>
    """
    offers = LinkedInSource.parse_html(html, limit=5)
    assert len(offers) == 1
    assert offers[0].external_id == "42"
    assert offers[0].source_url == "https://fr.linkedin.com/jobs/view/data-analyst-42"
    assert offers[0].publication_date.isoformat() == "2026-08-06"


def test_indeed_theirstack_collection_uses_profile_and_normalizes():
    description = " ".join(["Analyse de données avec Python, SQL et Power BI."] * 20)

    class Client:
        def __init__(self):
            self.location_calls = []
            self.payloads = []

        def resolve_location_ids(self, locations, country_code="FR"):
            self.location_calls.append((locations, country_code))
            return [2988507]

        def search_jobs(self, payload):
            self.payloads.append(payload)
            return [
                {
                    "id": 987,
                    "job_title": "Data Analyst",
                    "company": "Rocky Data",
                    "description": description,
                    "short_location": "Paris",
                    "country": "France",
                    "date_posted": "2026-08-12",
                    "source_url": (
                        "https://fr.indeed.com/viewjob?jk=abc123&utm_source=test"
                    ),
                    "final_url": "https://careers.example/jobs/data-analyst",
                    "hybrid": True,
                    "employment_statuses": ["full_time"],
                    "technology_slugs": ["python", "power-bi"],
                    "min_annual_salary": 42_000,
                    "max_annual_salary": 48_000,
                    "salary_currency": "EUR",
                    "seniority": "junior",
                    "company_object": {"industry": "Data"},
                },
                {
                    "id": 654,
                    "job_title": "Annonce hors Indeed",
                    "company": "Autre",
                    "description": description,
                    "source_url": "https://jobs.example/654",
                },
            ]

    client = Client()
    source = IndeedSource(
        Settings(
            theirstack_api_key="secret",
            theirstack_indeed_max_age_days=14,
        ),
        client,
    )
    profile = CandidateProfile(
        id=1,
        profile_name="Data",
        target_job_titles=["Data Analyst", "BI Analyst"],
        preferred_contracts=["CDI"],
        preferred_locations=["Paris"],
        remote_preferences=["Hybride"],
    )

    offers = source.search(profile, results_per_query=5)

    assert client.location_calls == [(["Paris"], "FR")]
    assert client.payloads == [
        {
            "job_title_or": ["Data Analyst", "BI Analyst"],
            "job_country_code_or": ["FR"],
            "url_domain_or": ["indeed.com"],
            "posted_at_max_age_days": 14,
            "is_closed": False,
            "limit": 5,
            "offset": 0,
            "job_location_or": [{"id": 2988507}],
            "employment_statuses_or": ["full_time"],
            "workplace_types_or": ["hybrid"],
        }
    ]
    assert len(offers) == 1
    offer = offers[0]
    assert offer.source_name == "Indeed"
    assert offer.collector_name == "TheirStack"
    assert offer.external_id == "abc123"
    assert offer.source_url.startswith("https://fr.indeed.com/viewjob")
    assert offer.application_url == "https://careers.example/jobs/data-analyst"
    assert offer.description_is_full is True
    assert offer.publication_date.isoformat() == "2026-08-12"
    assert offer.remote_policy == "Hybride"
    assert offer.work_schedule == "Temps plein"
    assert offer.salary_min == 42_000
    assert offer.detected_skills == ["python", "power bi"]


def test_indeed_theirstack_error_is_readable_and_does_not_expose_key():
    class Client:
        def resolve_location_ids(self, locations, country_code="FR"):
            return []

        def search_jobs(self, payload):
            raise SourceError("TheirStack n’a pas pu répondre (HTTP 503).")

    with pytest.raises(SourceError, match="HTTP 503"):
        IndeedSource(Settings(theirstack_api_key="secret"), Client()).search(
            CandidateProfile(id=1, profile_name="Data"),
            results_per_query=1,
        )


def test_apec_mapping():
    offer = ApecSource._offer(
        {
            "numeroOffre": "179215860W",
            "intitule": "Data Engineer BI Tableau Senior F/H",
            "nomCommercial": "Rocky Data",
            "lieuTexte": "Paris 01 - 75",
            "typeContrat": "CDD",
            "tempsTravail": "Temps partiel",
            "salaireTexte": "50 - 55 k€ brut annuel",
            "texteOffre": "Python, SQL et Tableau.",
            "datePublication": "2026-08-07T11:02:50.000+0000",
        }
    )
    assert offer.external_id == "179215860W"
    assert offer.salary_min == 50_000
    assert offer.salary_max == 55_000
    assert offer.source_url.endswith("/179215860W")
    assert offer.contract_type == "CDD"
    assert offer.work_schedule == "Temps partiel"
    assert offer.description_is_full is False


def test_wttj_mapping():
    offer = WelcomeToTheJungleSource._offer(
        {
            "name": "Data Analyst",
            "reference": "job-ref",
            "slug": "data-analyst",
            "published_at": "2026-08-05T08:00:00Z",
            "remote": "partial",
            "contract_type": "full_time",
            "salary_min": 40_000,
            "salary_max": 50_000,
            "salary_currency": "EUR",
            "company_summary": "Conseil et projets data.",
            "office": {"city": "Paris", "country_code": "FR"},
            "organization": {
                "name": "Rocky Data",
                "slug": "rocky-data",
                "sectors": [{"name": "Data"}],
            },
        }
    )
    assert offer.company_name == "Rocky Data"
    assert offer.city == "Paris"
    assert offer.source_url.endswith("/rocky-data/jobs/data-analyst")
    assert offer.contract_type == ""
    assert offer.work_schedule == "Temps plein"


def test_wellfound_next_data_mapping():
    payload = {
        "props": {
            "pageProps": {
                "apolloState": {
                    "data": {
                        "ROOT_QUERY": {
                            "talent": {
                                'seoLandingPageJobSearchResults({"page":1})': {
                                    "startups": [{"__ref": "StartupResult:1"}]
                                }
                            }
                        },
                        "StartupResult:1": {
                            "name": "Rocky Data",
                            "highlightedJobListings": [
                                {"__ref": "JobListingSearchResult:42"}
                            ],
                        },
                        "JobListingSearchResult:42": {
                            "id": "42",
                            "slug": "data-analyst",
                            "title": "Data Analyst",
                            "description": "Python et SQL",
                            "jobType": "full-time",
                            "remote": True,
                            "locationNames": ["France"],
                            "compensation": "€40k – €50k",
                            "liveStartAt": 1_786_032_000,
                        },
                    }
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script>"
    )
    offers = WellfoundSource.parse_html(html, limit=5)
    assert offers[0].company_name == "Rocky Data"
    assert offers[0].salary_min == 40_000
    assert offers[0].remote_policy == "Télétravail complet"
    assert offers[0].contract_type == ""
    assert offers[0].work_schedule == "Temps plein"


def test_watch_registry_contains_every_platform():
    names = [source.name for source in build_watch_sources(Settings())]
    assert names == [
        "France Travail",
        "Adzuna",
        "LinkedIn",
        "Indeed",
        "Welcome to the Jungle",
        "Apec",
        "Wellfound",
    ]
    indeed = next(
        source
        for source in build_watch_sources(Settings(theirstack_api_key="secret"))
        if source.name == "Indeed"
    )
    assert indeed.collector_name == "TheirStack"
