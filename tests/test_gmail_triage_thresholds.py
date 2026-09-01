"""Régressions ciblées des seuils de décision Gmail.

Ces tests unitaires évitent de dépendre de Gmail : ils vérifient seulement les
frontières métier qui séparent un classement automatique d'une revue humaine.
"""

from types import SimpleNamespace

from dashboard.rocky.config import Settings
from dashboard.rocky.gmail_service import GmailService
from dashboard.rocky.models import EmailDecision


class _Repository:
    """Double minimal qui enregistre les effets locaux du triage."""

    user_id = 1

    def __init__(self) -> None:
        self.status_updates: list[dict[str, object]] = []
        self.email_updates: list[dict[str, object]] = []

    def fetch_application(self, application_id: int) -> dict[str, str]:
        assert application_id == 7
        return {"status": "CANDIDATURE ENVOYÉE"}

    def update_application_status(
        self, application_id: int, status: str, **details
    ) -> None:
        self.status_updates.append(
            {"application_id": application_id, "status": status, **details}
        )

    def update_email_triage(self, email_id: int, **details) -> None:
        self.email_updates.append({"email_id": email_id, **details})


def _service(tmp_path, repository: _Repository) -> GmailService:
    """Construit le service sans jeton ni appel réseau Gmail."""
    settings = Settings(project_dir=tmp_path, gmail_accounts=("rocky@example.test",))
    return GmailService(
        settings,
        repository,  # type: ignore[arg-type] - double volontairement minimal.
        SimpleNamespace(id=1),
        "rocky@example.test",
    )


def test_application_status_requires_strictly_more_than_95_percent(tmp_path):
    """Un accusé à 94 % reste vérifiable, un refus à 98 % est appliqué."""
    repository = _Repository()
    service = _service(tmp_path, repository)

    state, _ = service._triage_decision(
        email_id=10,
        decision=EmailDecision("ACKNOWLEDGEMENT", 0.94, "ACCUSÉ DE RÉCEPTION", "Test"),
        application_id=7,
        link_confidence=0.99,
        match_reason="Employeur reconnu",
        links=[],
        import_links=False,
    )
    assert state == "REVIEW"
    assert not repository.status_updates

    state, _ = service._triage_decision(
        email_id=11,
        decision=EmailDecision("REFUSAL", 0.98, "REFUS", "Test"),
        application_id=7,
        link_confidence=0.99,
        match_reason="Employeur reconnu",
        links=[],
        import_links=False,
    )
    assert state == "AUTO_APPLIED"
    assert repository.status_updates[0]["status"] == "REFUS"


def test_only_high_confidence_noise_is_automatically_ignored(tmp_path):
    """Un message sans emploi certain est écarté ; un cas faible reste visible."""
    repository = _Repository()
    service = _service(tmp_path, repository)

    state, _ = service._triage_decision(
        email_id=12,
        decision=EmailDecision("NOISE", 0.96, None, "Facture reconnue"),
        application_id=None,
        link_confidence=0.0,
        match_reason="Aucune candidature",
        links=[],
        import_links=False,
    )
    assert state == "AUTO_IGNORED"

    state, _ = service._triage_decision(
        email_id=13,
        decision=EmailDecision("NOISE", 0.80, None, "Contenu insuffisant"),
        application_id=None,
        link_confidence=0.0,
        match_reason="Aucune candidature",
        links=[],
        import_links=False,
    )
    assert state == "REVIEW"
