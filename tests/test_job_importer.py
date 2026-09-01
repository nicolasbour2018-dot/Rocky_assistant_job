import json

import requests

from dashboard.rocky import job_importer
from dashboard.rocky.job_importer import (
    ImportPreview,
    description_is_probably_truncated,
    hydrate_job_offer,
    parse_html,
)
from dashboard.rocky.models import JobOffer

HTML = """
<html>
  <head>
    <link rel="canonical" href="https://jobs.example/offre-42?utm_source=test">
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "Data Analyst",
      "description": "<p>Python et SQL au quotidien.</p>",
      "identifier": {"value": "42"},
      "datePosted": "2026-08-01",
      "employmentType": ["CDI", "FULL_TIME"],
      "hiringOrganization": {"name": "Entreprise Exemple"},
      "jobLocation": {
        "address": {
          "addressLocality": "Paris",
          "addressCountry": "France"
        }
      },
      "baseSalary": {
        "currency": "EUR",
        "value": {"minValue": 40000, "maxValue": 45000}
      }
    }
    </script>
  </head>
  <body><h1>Data Analyst</h1></body>
</html>
"""


def test_parse_job_posting_json_ld():
    preview = parse_html(HTML, "https://jobs.example/original")
    offer = preview.offer
    assert preview.extraction_method == "JSON-LD"
    assert offer.job_title == "Data Analyst"
    assert offer.company_name == "Entreprise Exemple"
    assert offer.external_id == "42"
    assert offer.city == "Paris"
    assert offer.salary_min == 40_000
    assert offer.source_url == "https://jobs.example/offre-42"
    assert offer.contract_type == "CDI"
    assert offer.work_schedule == "Temps plein"


def test_html_fallback_is_explicit():
    preview = parse_html(
        "<html><head><title>Data chez Exemple</title></head>"
        "<body>Description publique</body></html>",
        "https://example.org/job",
    )
    assert preview.extraction_method == "HTML"
    assert preview.warnings
    assert "Description publique" in preview.offer.responsibilities
    assert preview.offer.description_is_full is False


def test_known_detail_container_is_read_as_full_description():
    preview = parse_html(
        "<html><head><title>Data Analyst</title></head>"
        "<body><div id='jobDescriptionText'>"
        "Mission complète avec Python, SQL et Power BI."
        "</div></body></html>",
        "https://example.org/job",
    )
    assert preview.extraction_method == "HTML ciblé"
    assert preview.offer.description_is_full is True
    assert preview.offer.responsibilities.startswith("Mission complète")


def test_truncated_json_ld_is_never_marked_as_complete():
    truncated_html = HTML.replace(
        "<p>Python et SQL au quotidien.</p>",
        "<p>Python et SQL dans un environnement de pl...</p>",
    )
    preview = parse_html(truncated_html, "https://jobs.example/original")
    assert description_is_probably_truncated(preview.offer.responsibilities)
    assert preview.offer.description_is_full is False


def test_hydration_replaces_preview_with_detail_page(monkeypatch):
    preview_offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities="Bref aperçu Python",
        source_url="https://example.org/job",
    )
    detailed_offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities="Description complète avec Python, SQL et Power BI.",
        source_url="https://example.org/job",
        description_is_full=True,
    )
    monkeypatch.setattr(
        job_importer,
        "import_job_url",
        lambda url: ImportPreview(
            detailed_offer,
            "JSON-LD",
            [],
            detailed_offer.responsibilities,
        ),
    )
    hydration = hydrate_job_offer(preview_offer)
    assert hydration.is_complete is True
    assert hydration.offer.description_is_full is True
    assert hydration.offer.responsibilities == detailed_offer.responsibilities


def test_wttj_hydration_uses_public_detail_api(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(
        {
            "job": {
                "description": "<p>Mission complète en CDI avec SQL.</p>",
                "profile": "<p>Maîtrise de Python demandée.</p>",
                "recruitment_process": "<p>Un entretien.</p>",
                "contract_type": "full_time",
                "apply_url": "https://apply.example/job",
                "tools": [{"name": "Power BI"}],
            }
        }
    ).encode()
    monkeypatch.setattr(
        job_importer.requests,
        "get",
        lambda *args, **kwargs: response,
    )
    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities="Aperçu",
        source_name="Welcome to the Jungle",
        source_url=(
            "https://www.welcometothejungle.com/fr/companies/exemple/jobs/data-analyst"
        ),
        external_id="reference-42",
    )
    hydration = hydrate_job_offer(offer)
    assert hydration.is_complete is True
    assert hydration.method == "API détail Welcome to the Jungle"
    assert "Profil recherché" in hydration.offer.responsibilities
    assert hydration.offer.contract_type == "CDI"
    assert hydration.offer.work_schedule == "Temps plein"
    assert hydration.offer.application_url == "https://apply.example/job"
    assert "Power BI" in hydration.offer.detected_skills


def test_apec_hydration_uses_detail_instead_of_search_excerpt(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(
        {
            "texteOffre": (
                "<p>Description complète de la mission avec Python, SQL, "
                "SAS et gestion de projet.</p>"
            ),
            "typeContratLibelle": "CDI",
            "tempsTravail": "Temps plein",
        }
    ).encode()
    monkeypatch.setattr(
        job_importer.requests,
        "get",
        lambda *args, **kwargs: response,
    )
    offer = JobOffer(
        job_title="Data Analyst",
        company_name="Exemple",
        responsibilities="Aperçu de la mission de pl...",
        source_name="Apec",
        source_url=(
            "https://www.apec.fr/candidat/recherche-emploi.html/emploi/"
            "detail-offre/179243309W"
        ),
        external_id="179243309W",
    )
    hydration = hydrate_job_offer(offer)
    assert hydration.is_complete is True
    assert hydration.method == "API détail Apec"
    assert "gestion de projet" in hydration.offer.responsibilities
    assert hydration.offer.description_is_full is True
