import pytest

from dashboard.rocky.config import Settings
from dashboard.rocky.errors import RockyError
from dashboard.rocky.llm import RockyLLM


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
