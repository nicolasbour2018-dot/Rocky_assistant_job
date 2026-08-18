from dataclasses import replace

import pytest
import requests

from dashboard.rocky import enrichment
from dashboard.rocky.config import Settings
from dashboard.rocky.errors import SourceError
from dashboard.rocky.job_importer import DescriptionHydration
from dashboard.rocky.models import CandidateProfile, JobOffer, MatchResult
from dashboard.rocky.statuses import INCOMPLETE_STATUS
from dashboard.rocky.theirstack import TheirStackClient


def incomplete_offer() -> JobOffer:
    return JobOffer(
        job_title="Data Analyst",
        company_name="Rocky Data",
        responsibilities="Bref aperçu de la mission...",
        short_description="Bref aperçu",
        source_name="Apec",
        source_url="https://www.apec.fr/offre/42",
        application_url="https://www.apec.fr/offre/42",
        external_id="APEC-42",
        city="Paris",
        publication_date="2026-08-01",
        status=INCOMPLETE_STATUS,
    )


class FakeRepository:
    def __init__(self, offer):
        self.offer = offer
        self.updated = []
        self.statuses = []
        self.matches = []

    def fetch_job_offer(self, job_id):
        return self.offer

    def update_job(self, job_id, offer):
        self.updated.append((job_id, offer))
        self.offer = offer

    def update_job_status(self, job_id, status):
        self.statuses.append((job_id, status))

    def fetch_skills(self, profile_id):
        return []

    def save_match(self, job_id, profile_id, result):
        self.matches.append((job_id, profile_id, result))


def test_complete_offer_never_calls_theirstack():
    offer = replace(
        incomplete_offer(),
        responsibilities="Description complète avec Python et SQL.",
        description_is_full=True,
        status="NOUVELLE",
    )

    class ForbiddenClient:
        def hydrate(self, candidate):
            raise AssertionError("TheirStack ne doit pas être appelé")

    result = enrichment.reenrich_job_offer(
        offer,
        Settings(theirstack_api_key="secret"),
        ForbiddenClient(),
    )
    assert result.is_complete is True


def test_theirstack_match_preserves_original_provenance(monkeypatch):
    offer = incomplete_offer()
    description = " ".join(["Mission complète Python SQL Power BI"] * 30)

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "id": 987,
                        "job_title": "Data Analyst",
                        "company": "Rocky Data",
                        "description": description,
                        "location": "Paris, France",
                        "date_posted": "2026-08-02",
                        "source_url": offer.source_url,
                    }
                ]
            }

    monkeypatch.setattr(
        "dashboard.rocky.theirstack.requests.post",
        lambda *args, **kwargs: Response(),
    )
    result = TheirStackClient("secret").hydrate(offer)
    assert result.is_complete is True
    assert result.offer.source_name == "Apec"
    assert result.offer.source_url == offer.source_url
    assert result.offer.external_id == "APEC-42"
    assert result.offer.description_enrichment_source == "TheirStack"
    assert result.offer.description_enrichment_external_id == "987"


def test_successful_reenrichment_restores_matching(monkeypatch):
    offer = incomplete_offer()
    enriched_offer = replace(
        offer,
        responsibilities="Description complète " * 40,
        description_is_full=True,
        description_enrichment_source="TheirStack",
        description_enrichment_external_id="987",
    )

    class SuccessfulClient:
        def hydrate(self, candidate):
            return DescriptionHydration(
                enriched_offer,
                True,
                method="TheirStack Job Search",
            )

    monkeypatch.setattr(
        enrichment,
        "hydrate_job_offer",
        lambda candidate: DescriptionHydration(
            candidate, False, warning="Détail source indisponible."
        ),
    )
    monkeypatch.setattr(
        enrichment,
        "calculate_match",
        lambda candidate, profile, skills: MatchResult(88, {}),
    )
    repository = FakeRepository(offer)
    profile = CandidateProfile(id=4, profile_name="Data")
    result = enrichment.reenrich_saved_job(
        42,
        Settings(theirstack_api_key="secret"),
        repository,
        profile,
        SuccessfulClient(),
    )
    assert result.is_complete is True
    assert repository.updated[0][1].source_name == "Apec"
    assert repository.statuses == [(42, "NOUVELLE")]
    assert repository.matches[0][2].score == 88


def test_failed_reenrichment_keeps_the_offer(monkeypatch):
    offer = incomplete_offer()

    class EmptyClient:
        def hydrate(self, candidate):
            return DescriptionHydration(
                candidate,
                False,
                method="TheirStack Job Search",
                warning="Aucune correspondance.",
            )

    monkeypatch.setattr(
        enrichment,
        "hydrate_job_offer",
        lambda candidate: DescriptionHydration(
            candidate, False, warning="Source indisponible."
        ),
    )
    repository = FakeRepository(offer)
    result = enrichment.reenrich_saved_job(
        42,
        Settings(theirstack_api_key="secret"),
        repository,
        theirstack_client=EmptyClient(),
    )
    assert result.is_complete is False
    assert repository.offer is offer
    assert repository.updated == []
    assert repository.matches == []


def test_theirstack_error_never_exposes_credentials(monkeypatch):
    secret = "TOP_SECRET_THEIRSTACK"

    def fail(*args, **kwargs):
        raise requests.ConnectionError(secret)

    monkeypatch.setattr("dashboard.rocky.theirstack.requests.post", fail)
    with pytest.raises(SourceError) as captured:
        TheirStackClient(secret).search_candidates(incomplete_offer())
    assert secret not in str(captured.value)


def test_bulk_reenrichment_continues_after_failures_and_reports_progress(
    monkeypatch,
):
    calls = []
    clients = []
    progress = []

    def fake_reenrich(
        job_id,
        settings,
        repository,
        profile,
        theirstack_client,
    ):
        calls.append(job_id)
        clients.append(theirstack_client)
        if job_id == 3:
            raise SourceError("Erreur isolée")
        return DescriptionHydration(
            incomplete_offer(),
            is_complete=job_id == 1,
            method="Test",
        )

    monkeypatch.setattr(enrichment, "reenrich_saved_job", fake_reenrich)
    summary = enrichment.reenrich_saved_jobs(
        [1, 2, 3],
        Settings(theirstack_api_key="secret"),
        object(),
        CandidateProfile(id=4, profile_name="Data"),
        on_progress=lambda current, total: progress.append((current, total)),
    )

    assert calls == [1, 2, 3]
    assert clients[0] is clients[1] is clients[2]
    assert summary == {
        "attempted": 3,
        "enriched": 1,
        "still_incomplete": 1,
        "errors": 1,
    }
    assert progress == [(1, 3), (2, 3), (3, 3)]
