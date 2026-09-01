"""Tests de non-régression pour l'isolation des boîtes Gmail."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine

from dashboard.rocky.config import Settings
from dashboard.rocky.database import initialize_database
from dashboard.rocky.errors import ConfigurationError
from dashboard.rocky.gmail_service import GmailService
from dashboard.rocky.repository import RockyRepository

PROJECT_DIR = Path(__file__).resolve().parents[1]
FIRST_ACCOUNT = "first@example.test"
SECOND_ACCOUNT = "second@example.test"


def _message(account: str, message_id: str) -> dict[str, object]:
    """Construit le minimum requis sans partager un dictionnaire mutable."""
    return {
        "gmail_account": account,
        "gmail_message_id": message_id,
        "gmail_thread_id": None,
        "sender": "recruteur@example.com",
        "subject": "Votre candidature",
        "received_at": None,
        "snippet": "Message de test",
        "classification": "APPLICATION_UPDATE",
        "confidence": 0.8,
        "matched_application_id": None,
        "processing_state": "REVIEW",
        "reason": "Test",
        "extracted_links": [],
    }


def test_each_account_has_an_independent_token(tmp_path):
    settings = Settings(
        project_dir=tmp_path,
        gmail_accounts=(FIRST_ACCOUNT, SECOND_ACCOUNT),
    )

    class Repository:
        user_id = 7

    first = GmailService(settings, Repository(), object(), FIRST_ACCOUNT)
    second = GmailService(settings, Repository(), object(), SECOND_ACCOUNT)

    first.token_path.parent.mkdir(parents=True)
    first.token_path.write_text("{}", encoding="utf-8")
    assert first.is_authorized is True
    assert second.is_authorized is False
    assert first.token_path != second.token_path
    assert first.token_path.name == "first_example_test.json"
    assert second.token_path.name == "second_example_test.json"


def test_browser_authorization_persists_state_for_streamlit_callback(tmp_path):
    """L'autorisation OAuth survit à une nouvelle session Streamlit."""
    settings = Settings(
        project_dir=tmp_path,
        gmail_accounts=(FIRST_ACCOUNT, SECOND_ACCOUNT),
        gmail_oauth_redirect_uri="http://localhost:8501/",
    )
    settings.gmail_credentials_path.parent.mkdir(parents=True)
    settings.gmail_credentials_path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client.apps.googleusercontent.com",
                    "project_id": "rocky-test",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": (
                        "https://www.googleapis.com/oauth2/v1/certs"
                    ),
                    "client_secret": "test-only",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )

    class Repository:
        user_id = 7

    service = GmailService(settings, Repository(), object(), SECOND_ACCOUNT)

    authorization_url = service.begin_browser_authorization(
        settings.gmail_oauth_redirect_uri
    )
    query = parse_qs(urlsplit(authorization_url).query)
    state = query["state"][0]

    assert query["login_hint"] == [SECOND_ACCOUNT]
    assert query["redirect_uri"] == [settings.gmail_oauth_redirect_uri]
    assert GmailService.account_for_pending_authorization(settings, state, 7) == (
        SECOND_ACCOUNT
    )
    with pytest.raises(ConfigurationError):
        GmailService.account_for_pending_authorization(settings, "invalid-state", 7)


def test_same_gmail_message_id_is_unique_per_account(tmp_path):
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{tmp_path / 'multi-account.db'}",
        gmail_accounts=(FIRST_ACCOUNT, SECOND_ACCOUNT),
    )
    engine = create_engine(settings.database_url)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)

    assert repository.save_email_message(_message(FIRST_ACCOUNT, "same-id"))
    assert repository.save_email_message(_message(SECOND_ACCOUNT, "same-id"))
    assert repository.save_email_message(_message(FIRST_ACCOUNT, "same-id")) is None
    assert repository.email_message_exists(FIRST_ACCOUNT, "same-id")
    assert repository.email_message_exists(SECOND_ACCOUNT, "same-id")
    assert len(repository.fetch_email_messages()) == 2


def test_classifying_a_job_alert_removes_it_from_the_review_queue(tmp_path):
    """Le reclassement manuel termine la revue sans supprimer l'historique."""
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{tmp_path / 'classified-alert.db'}",
        gmail_accounts=(FIRST_ACCOUNT,),
    )
    engine = create_engine(settings.database_url)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    email_id = repository.save_email_message(_message(FIRST_ACCOUNT, "job-alert"))
    assert email_id is not None

    repository.reclassify_email_as_job_alert(int(email_id), "Classement de test")

    assert repository.fetch_pending_email_messages().empty
    history = repository.fetch_email_messages()
    assert history.iloc[0]["classification"] == "JOB_ALERT"
    assert history.iloc[0]["processing_state"] == "CLASSIFIED"
    assert bool(history.iloc[0]["classification_manual"]) is True


def test_manual_email_classification_keeps_only_candidate_returns_in_review(tmp_path):
    """Ignorer termine la revue, tandis qu'un retour reste à qualifier."""
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{tmp_path / 'manual-classification.db'}",
        gmail_accounts=(FIRST_ACCOUNT,),
    )
    engine = create_engine(settings.database_url)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    ignored_id = repository.save_email_message(_message(FIRST_ACCOUNT, "ignored"))
    returned_id = repository.save_email_message(_message(FIRST_ACCOUNT, "return"))
    assert ignored_id is not None and returned_id is not None

    repository.manually_classify_email(
        int(ignored_id),
        classification="NOISE",
        confidence=0.99,
        processing_state="IGNORED",
        reason="Test : hors emploi",
        clear_application=True,
    )
    repository.manually_classify_email(
        int(returned_id),
        classification="APPLICATION_UPDATE",
        confidence=0.78,
        processing_state="REVIEW",
        reason="Test : retour à traiter",
        clear_application=False,
    )

    pending = repository.fetch_pending_email_messages()
    assert list(pending["gmail_message_id"]) == ["return"]
    history = repository.fetch_email_messages()
    assert all(bool(value) for value in history["classification_manual"])

    # Une synchronisation ultérieure ne doit pas faire disparaître une
    # correction humaine, même si le moteur automatique proposerait autre chose.
    repository.update_email_triage(
        int(returned_id),
        classification="NOISE",
        confidence=0.99,
        processing_state="AUTO_IGNORED",
        reason="Ne doit pas remplacer la décision humaine",
    )
    returned = (
        repository.fetch_email_messages().query("gmail_message_id == 'return'").iloc[0]
    )
    assert returned["classification"] == "APPLICATION_UPDATE"
    assert bool(returned["classification_manual"]) is True


def test_reopening_auto_ignored_email_returns_it_to_review(tmp_path):
    """Une correction humaine restaure la revue et résiste au triage suivant."""
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{tmp_path / 'reopened-email.db'}",
        gmail_accounts=(FIRST_ACCOUNT,),
    )
    engine = create_engine(settings.database_url)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    email_id = repository.save_email_message(_message(FIRST_ACCOUNT, "reopened"))
    assert email_id is not None
    repository.update_email_triage(
        int(email_id),
        classification="NOISE",
        confidence=0.96,
        processing_state="AUTO_IGNORED",
        reason="Facture reconnue",
    )

    repository.reopen_auto_ignored_email(
        int(email_id), "Réouverture manuelle : message à requalifier"
    )

    pending = repository.fetch_pending_email_messages()
    assert list(pending["gmail_message_id"]) == ["reopened"]
    reopened = pending.iloc[0]
    assert reopened["processing_state"] == "REVIEW"
    assert bool(reopened["classification_manual"]) is True
    repository.update_email_triage(
        int(email_id),
        classification="NOISE",
        confidence=0.99,
        processing_state="AUTO_IGNORED",
        reason="Nouveau triage automatique",
    )
    updated = repository.fetch_pending_email_messages().iloc[0]
    assert updated["processing_state"] == "REVIEW"


def test_incompatible_existing_schema_is_rejected(tmp_path):
    database_path = tmp_path / "incompatible.db"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE email_messages (id INTEGER PRIMARY KEY)"
        )
    settings = Settings(
        project_dir=PROJECT_DIR,
        database_url_override=f"sqlite:///{database_path}",
        gmail_accounts=(FIRST_ACCOUNT, SECOND_ACCOUNT),
    )
    with pytest.raises(ConfigurationError, match="schéma de la base est incompatible"):
        initialize_database(engine, settings)
