from dashboard.rocky.config import Settings
from dashboard.rocky.models import CandidateProfile, JobOffer, MatchResult
from dashboard.rocky.statuses import INCOMPLETE_STATUS
from dashboard.rocky.watch import WatchService


class FakeSource:
    name = "Test"

    def search(self, profile, results_per_query):
        return [
            JobOffer("69.9", "A", "Python", description_is_full=True),
            JobOffer("70.0", "B", "Python", description_is_full=True),
        ]


class CapturingSource:
    name = "Capture"

    def __init__(self):
        self.queries = None

    def search(self, profile, results_per_query):
        self.queries = list(profile.target_job_titles)
        return []


class BrokenSource:
    name = "Cassée"

    def search(self, profile, results_per_query):
        raise ValueError("détail interne à ne pas afficher")


class PreviewOnlySource:
    name = "Aperçu"

    def search(self, profile, results_per_query):
        return [JobOffer("Data Analyst", "A", "Bref aperçu")]


class TheirStackIndeedSource:
    name = "Indeed"
    collector_name = "TheirStack"

    def search(self, profile, results_per_query):
        return [
            JobOffer(
                "Data Analyst",
                "Indeed Company",
                "Description complète avec Python et SQL.",
                source_name="Indeed",
                collector_name="TheirStack",
                source_url="https://fr.indeed.com/viewjob?jk=42",
                description_is_full=True,
            )
        ]


class BrokenTheirStackIndeedSource(TheirStackIndeedSource):
    def search(self, profile, results_per_query):
        from dashboard.rocky.errors import SourceError

        raise SourceError("TheirStack n’a pas pu répondre (HTTP 503).")


class FakeRepository:
    def __init__(self):
        self.inserted = []
        self.inserted_offers = []
        self.linked = []
        self.saved_matches = []
        self.matched_jobs = set()
        self.summary = None

    def fetch_active_profile(self):
        return CandidateProfile(id=1, profile_name="Data")

    def fetch_skills(self, profile_id):
        return []

    def start_watch_run(self, profile_id, searched_job_titles=()):
        self.searched_job_titles = list(searched_job_titles)
        return 7

    def find_duplicate(self, offer):
        return None

    def insert_job(self, offer, profile_id=None):
        self.inserted.append(offer.job_title)
        self.inserted_offers.append(offer)
        if profile_id is not None:
            self.link_job_to_profile(10, profile_id)
        return 10, True

    def link_job_to_profile(self, job_id, profile_id):
        relation = (job_id, profile_id)
        if relation in self.linked:
            return False
        self.linked.append(relation)
        return True

    def has_job_match(self, job_id, profile_id):
        return (job_id, profile_id) in self.matched_jobs

    def fetch_job_offer(self, job_id):
        return None

    def update_job_if_changed(self, job_id, offer):
        return False

    def save_match(self, job_id, profile_id, result):
        self.saved_matches.append(result.score)
        self.matched_jobs.add((job_id, profile_id))

    def finish_watch_run(self, run_id, summary):
        self.summary = summary


def test_watch_inserts_score_equal_to_70(monkeypatch):
    def fake_match(offer, profile, skills):
        return MatchResult(float(offer.job_title), {})

    monkeypatch.setattr("dashboard.rocky.watch.calculate_match", fake_match)
    repository = FakeRepository()
    service = WatchService(
        Settings(match_threshold=70),
        repository,
        [FakeSource()],
    )
    summary = service.run()
    assert repository.inserted == ["70.0"]
    assert summary["rejected_count"] == 1
    assert summary["inserted_count"] == 1
    assert repository.linked == [(10, 1)]
    assert summary["sources"] == [
        {
            "source": "Test",
            "status": "OK",
            "fetched_count": 2,
            "inserted_count": 1,
            "duplicate_count": 0,
            "updated_count": 0,
            "rejected_count": 1,
            "incomplete_count": 0,
        }
    ]


def test_watch_accepts_ephemeral_query_without_persisting_profile():
    repository = FakeRepository()
    repository.fetch_active_profile = lambda: CandidateProfile(
        id=1, profile_name="Data", target_job_titles=["Profil historique"]
    )
    source = CapturingSource()
    override = CandidateProfile(
        id=1, profile_name="Data", target_job_titles=["Data Product"]
    )
    WatchService(Settings(), repository, [source]).run(profile_override=override)
    assert source.queries == ["Data Product"]
    assert repository.searched_job_titles == ["Data Product"]


def test_watch_isolates_an_unexpected_source_failure(monkeypatch):
    def fake_match(offer, profile, skills):
        return MatchResult(100, {})

    monkeypatch.setattr("dashboard.rocky.watch.calculate_match", fake_match)
    repository = FakeRepository()
    service = WatchService(
        Settings(match_threshold=70),
        repository,
        [BrokenSource(), FakeSource()],
    )
    summary = service.run()
    assert summary["status"] == "PARTIAL"
    assert summary["fetched_count"] == 2
    assert summary["errors"] == [
        {
            "source": "Cassée",
            "message": "Erreur technique isolée dans ce connecteur.",
        }
    ]


def test_watch_combines_indeed_theirstack_with_another_source(monkeypatch):
    monkeypatch.setattr(
        "dashboard.rocky.watch.calculate_match",
        lambda offer, profile, skills: MatchResult(100, {}),
    )
    repository = FakeRepository()

    summary = WatchService(
        Settings(match_threshold=70),
        repository,
        [TheirStackIndeedSource(), FakeSource()],
    ).run()

    assert summary["status"] == "SUCCESS"
    assert summary["fetched_count"] == 3
    assert summary["sources"][0]["source"] == "Indeed"
    assert summary["sources"][0]["collector"] == "TheirStack"
    assert summary["sources"][1]["source"] == "Test"


def test_theirstack_failure_does_not_stop_other_watch_sources(monkeypatch):
    monkeypatch.setattr(
        "dashboard.rocky.watch.calculate_match",
        lambda offer, profile, skills: MatchResult(100, {}),
    )
    repository = FakeRepository()

    summary = WatchService(
        Settings(match_threshold=70),
        repository,
        [BrokenTheirStackIndeedSource(), FakeSource()],
    ).run()

    assert summary["status"] == "PARTIAL"
    assert summary["fetched_count"] == 2
    assert summary["sources"][0] == {
        "source": "Indeed",
        "status": "ERREUR",
        "fetched_count": 0,
        "collector": "TheirStack",
    }
    assert summary["sources"][1]["status"] == "OK"


def test_watch_never_scores_a_preview_only_offer(monkeypatch):
    def forbidden_match(offer, profile, skills):
        raise AssertionError("Le matching ne doit pas analyser un aperçu")

    monkeypatch.setattr("dashboard.rocky.watch.calculate_match", forbidden_match)
    repository = FakeRepository()
    service = WatchService(
        Settings(match_threshold=70),
        repository,
        [PreviewOnlySource()],
    )
    summary = service.run()
    assert repository.inserted == ["Data Analyst"]
    assert repository.inserted_offers[0].status == INCOMPLETE_STATUS
    assert repository.inserted_offers[0].description_is_full is False
    assert repository.saved_matches == []
    assert summary["incomplete_description_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["inserted_count"] == 1


def test_watch_does_not_rehydrate_a_known_incomplete_offer(monkeypatch):
    existing = JobOffer(
        "Data Analyst",
        "A",
        "Bref aperçu",
        source_name="Test",
        source_url="https://jobs.example/42",
        external_id="42",
        status=INCOMPLETE_STATUS,
    )

    class KnownSource:
        name = "Test"

        def search(self, profile, results_per_query):
            return [existing]

    class KnownRepository(FakeRepository):
        def find_duplicate(self, offer):
            return 42

        def fetch_job_offer(self, job_id):
            return existing

    monkeypatch.setattr(
        "dashboard.rocky.watch.hydrate_job_offer",
        lambda offer: (_ for _ in ()).throw(
            AssertionError("Une annonce connue ne doit pas être réhydratée")
        ),
    )
    repository = KnownRepository()
    summary = WatchService(Settings(), repository, [KnownSource()]).run()
    assert summary["duplicate_count"] == 1
    assert summary["inserted_count"] == 0
    assert repository.saved_matches == []
    assert repository.linked == [(42, 1)]


def test_watch_links_and_matches_a_known_complete_job_for_a_new_profile(monkeypatch):
    existing = JobOffer(
        "Data Analyst",
        "A",
        "Description complète avec Python et SQL",
        source_name="Test",
        source_url="https://jobs.example/complete",
        external_id="complete",
        description_is_full=True,
    )

    class KnownSource:
        name = "Test"

        def search(self, profile, results_per_query):
            return [existing]

    class KnownRepository(FakeRepository):
        def find_duplicate(self, offer):
            return 42

        def fetch_job_offer(self, job_id):
            return existing

    monkeypatch.setattr(
        "dashboard.rocky.watch.calculate_match",
        lambda offer, profile, skills: MatchResult(82, {}),
    )
    repository = KnownRepository()

    summary = WatchService(Settings(), repository, [KnownSource()]).run()

    assert summary["duplicate_count"] == 1
    assert repository.linked == [(42, 1)]
    assert repository.saved_matches == [82]
