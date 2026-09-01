"""Contrats de sécurité et de bilinguisme des espaces personnels Rocky."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text

from dashboard.rocky.auth import AuthService
from dashboard.rocky.config import Settings
from dashboard.rocky.database import create_db_engine, initialize_database
from dashboard.rocky.errors import ConfigurationError, DocumentError, RockyError
from dashboard.rocky.language import detect_language, effective_language
from dashboard.rocky.models import JobOffer
from dashboard.rocky.profile_documents import ROCKY_MARKER, validate_letter_template
from dashboard.rocky.repository import RockyRepository


class RecordingMailer:
    """Capture uniquement les liens afin de tester les jetons sans SMTP réel."""

    def __init__(self):
        self.messages: list[tuple[str, str, str]] = []

    def send(self, recipient: str, subject: str, body: str) -> None:
        self.messages.append((recipient, subject, body))


def _stack(tmp_path: Path):
    settings = Settings(
        project_dir=Path.cwd(),
        database_url_override=f"sqlite:///{tmp_path / 'accounts.db'}",
        storage_dir_override=str(tmp_path / "data"),
        rocky_public_url="https://rocky.test",
    )
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    return settings, engine, RockyRepository(engine)


def _token_from_last_mail(mailer: RecordingMailer, query_name: str) -> str:
    body = mailer.messages[-1][2]
    url = next(line for line in body.splitlines() if line.startswith("https://"))
    return parse_qs(urlsplit(url).query)[query_name][0]


def _active_user(service: AuthService, mailer: RecordingMailer, email: str):
    service.register(email)
    token = _token_from_last_mail(mailer, "verify")
    return service.activate_account(token, "une phrase de passe très sûre")


def test_full_account_lifecycle_uses_one_time_tokens(tmp_path):
    settings, engine, _ = _stack(tmp_path)
    mailer = RecordingMailer()
    service = AuthService(engine, settings, mailer)
    user = _active_user(service, mailer, "USER@Example.test")
    assert user.email == "user@example.test"

    authenticated, raw_session = service.authenticate(
        "user@example.test", "une phrase de passe très sûre"
    )
    assert authenticated.id == user.id
    assert service.user_from_session(raw_session).id == user.id

    service.request_password_reset("user@example.test")
    reset_token = _token_from_last_mail(mailer, "reset")
    service.reset_password(reset_token, "une nouvelle phrase très sûre")
    assert service.user_from_session(raw_session) is None
    with pytest.raises(RockyError):
        service.reset_password(reset_token, "encore une phrase très sûre")
    for _ in range(5):
        with pytest.raises(RockyError):
            service.authenticate("user@example.test", "mot de passe incorrect")
    with pytest.raises(RockyError, match="Adresse ou mot de passe incorrect"):
        service.authenticate("user@example.test", "une nouvelle phrase très sûre")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT locked_until FROM users WHERE id = :id"),
                {"id": user.id},
            ).scalar_one()
            is not None
        )


def test_repository_never_crosses_account_boundaries(tmp_path):
    settings, engine, base = _stack(tmp_path)
    mailer = RecordingMailer()
    service = AuthService(engine, settings, mailer)
    first = _active_user(service, mailer, "first@example.test")
    second = _active_user(service, mailer, "second@example.test")
    first_repository = base.for_user(first.id)
    second_repository = base.for_user(second.id)

    first_profile = first_repository.create_profile("Data")
    second_profile = second_repository.create_profile("Product")
    first_repository.set_active_profile(first_profile)
    second_repository.set_active_profile(second_profile)
    job_id, _ = first_repository.insert_job(
        JobOffer("Data Analyst", "Acme", "The role requires SQL and teamwork."),
        first_profile,
    )
    application_id = first_repository.create_application(
        job_id, first_profile, "cv.pdf", None, "letter.pdf"
    )

    assert first_repository.fetch_profile(first_profile) is not None
    assert second_repository.fetch_profile(first_profile) is None
    assert second_repository.fetch_job(job_id) is None
    assert first_repository.fetch_active_profile().id == first_profile
    assert second_repository.fetch_active_profile().id == second_profile
    with pytest.raises(PermissionError):
        second_repository.link_job_to_profile(job_id, second_profile)
    with pytest.raises(PermissionError):
        second_repository.update_application_status(application_id, "ENTRETIEN")
    with pytest.raises(PermissionError):
        second_repository.fetch_application_documents(application_id)

    first_repository.save_profile_document(
        first_profile,
        "en",
        "cv",
        "manual-en.pdf",
        "manual-v1",
        origin="uploaded",
    )
    first_repository.save_profile_document(
        first_profile,
        "en",
        "letter",
        "manual-en.docx",
        "manual-v1",
        origin="uploaded",
    )
    first_repository.save_profile_document(
        first_profile,
        "fr",
        "cv",
        "french-v1.pdf",
        "french-v1",
        origin="uploaded",
    )
    english_documents = {
        document.kind: document
        for document in first_repository.fetch_profile_documents(first_profile, "en")
    }
    assert english_documents["cv"].status == "ready"
    assert english_documents["letter"].status == "ready"
    first_repository.save_profile_document(
        first_profile,
        "fr",
        "cv",
        "french-v2.pdf",
        "french-v2",
        origin="uploaded",
    )
    english_documents = {
        document.kind: document
        for document in first_repository.fetch_profile_documents(first_profile, "en")
    }
    assert english_documents["cv"].status == "ready"
    assert english_documents["letter"].status == "ready"
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM profile_documents "
                    "WHERE profile_id = :profile_id AND locale = 'fr' AND kind = 'cv'"
                ),
                {"profile_id": first_profile},
            ).scalar_one()
            == 2
        )


def test_existing_incompatible_schema_fails_clearly(tmp_path):
    settings = Settings(
        project_dir=Path.cwd(),
        database_url_override=f"sqlite:///{tmp_path / 'incompatible.db'}",
    )
    engine = create_db_engine(settings)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))

    with pytest.raises(ConfigurationError, match="schéma de la base est incompatible"):
        initialize_database(engine, settings)


def test_docx_marker_is_found_even_when_split_between_runs(tmp_path):
    Document = pytest.importorskip("docx").Document
    valid = tmp_path / "valid.docx"
    document = Document()
    paragraph = document.add_paragraph("Mon introduction. ")
    paragraph.add_run("[paragraphe ")
    paragraph.add_run("Rocky]")
    document.save(valid)
    validate_letter_template(valid)

    invalid = tmp_path / "invalid.docx"
    document = Document()
    document.add_paragraph(f"{ROCKY_MARKER} puis {ROCKY_MARKER}")
    document.save(invalid)
    with pytest.raises(DocumentError):
        validate_letter_template(invalid)


def test_language_detection_and_override_are_deterministic():
    english = detect_language(
        "The role requires experience with the team and your responsibilities."
    )
    french = detect_language(
        "Le poste propose des missions avec une équipe et votre expérience."
    )
    assert english.locale == "en"
    assert french.locale == "fr"
    assert effective_language("en", "fr") == "fr"
