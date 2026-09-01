import json
import pytest
from types import SimpleNamespace

from dashboard.rocky.config import Settings
from dashboard.rocky.errors import RockyError
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.models import CandidateProfile
from dashboard.rocky.models import JobOffer, ProfileProject


def test_current_mistral_sdk_client_can_be_created_without_calling_api():
    rocky = RockyLLM(Settings(mistral_api_key="test-only"))
    client = rocky._client()
    assert hasattr(client.chat, "complete")


def test_mistral_errors_never_expose_credentials(monkeypatch):
    class FailingCompletions:
        @staticmethod
        def complete(**kwargs):
            raise RuntimeError("request failed with api_key=SUPER_SECRET")

    class FailingClient:
        class chat:
            complete = FailingCompletions.complete

    rocky = RockyLLM(Settings(mistral_api_key="SUPER_SECRET"))
    monkeypatch.setattr(rocky, "_client", lambda: FailingClient())

    with pytest.raises(RockyError) as captured:
        rocky.complete_text("système", "utilisateur")
    assert "SUPER_SECRET" not in str(captured.value)


def test_chat_receives_bounded_job_and_application_context(monkeypatch):
    profile = CandidateProfile(id=1, profile_name="Nico", summary="Data scientist")
    rocky = RockyLLM(Settings(mistral_api_key="test-only"))
    captured = {}

    def fake_complete_text(system, user, temperature=0.2):
        captured["system"] = system
        captured["user"] = user
        return "Analyse courte"

    monkeypatch.setattr(rocky, "complete_text", fake_complete_text)
    answer = rocky.chat(
        "Quelles offres sont les plus pertinentes ?",
        profile,
        jobs=[
            {
                "id": 42,
                "job_title": "Data Analyst",
                "company_name": "Acme",
                "match_score": 88,
            }
        ],
        applications=[{"id": 9, "status": "CANDIDATURE ENVOYÉE"}],
        skills=[{"skill_name": "Python", "skill_category": "technical"}],
    )
    assert answer == "Analyse courte"
    assert '"id": 42' in captured["user"]
    assert "Data Analyst" in captured["user"]
    assert "database.jobs" in captured["system"]


def test_stream_chat_yields_mistral_fragments(monkeypatch):
    profile = CandidateProfile(id=1, profile_name="Nico")
    rocky = RockyLLM(Settings(mistral_api_key="test-only"))
    events = [
        SimpleNamespace(
            data=SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Bonjour "))]
            )
        ),
        SimpleNamespace(
            data=SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Nicolas"))]
            )
        ),
    ]

    class FakeChat:
        def stream(self, **_kwargs):
            return iter(events)

    monkeypatch.setattr(rocky, "_client", lambda: SimpleNamespace(chat=FakeChat()))
    assert "".join(rocky.stream_chat("Salut", profile)) == "Bonjour Nicolas"


def test_translate_blocks_retries_one_structured_batch_when_invalid(monkeypatch):
    """Une réponse incomplète ne doit jamais déclencher une rafale d'appels LLM."""
    rocky = RockyLLM(Settings(mistral_api_key="test-only"))
    batch_sizes = []

    def fake_complete_json(_system, user, temperature=0.1):
        values = json.loads(user)["blocks"]
        batch_sizes.append(len(values))
        if len(batch_sizes) == 1:
            return {"blocks": {"0": values["0"]}}
        return {"blocks": {index: f"EN: {value}" for index, value in values.items()}}

    monkeypatch.setattr(rocky, "complete_json", fake_complete_json)
    assert rocky.translate_blocks(["Premier bloc", "Second bloc"]) == [
        "EN: Premier bloc",
        "EN: Second bloc",
    ]
    assert batch_sizes == [2, 2]


def test_application_message_uses_validated_profile_evidence(monkeypatch):
    """Le champ libre est court et ne constitue pas une troisième lettre."""
    profile = CandidateProfile(id=1, profile_name="Nico", summary="Data scientist")
    offer = JobOffer("Data Analyst", "Acme", "Python et SQL", description_is_full=True)
    rocky = RockyLLM(Settings(mistral_api_key="test-only"))
    captured = {}

    def fake_complete_json(system, user, temperature=0.1):
        captured["system"] = system
        captured["user"] = user
        return {
            "application_message": (
                "Bonjour, je vous adresse ma candidature au poste de Data Analyst "
                "chez Acme. Mon expérience Python me donne envie d'échanger sur vos missions."
            )
        }

    monkeypatch.setattr(rocky, "complete_json", fake_complete_json)
    message = rocky.application_accompanying_message(
        offer,
        profile,
        [{"skill_name": "Python"}],
        [
            ProfileProject(
                "analyse",
                "Analyse",
                "Comprendre des données.",
                ("Python",),
                "Analyse livrée.",
            )
        ],
    )
    assert "Data Analyst" in message
    assert "Python" in captured["user"]
    assert "différent d'une lettre" in captured["system"]
