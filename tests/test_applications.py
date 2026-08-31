"""Régression sur le contenu réel de la lettre d'une candidature générée."""

from pathlib import Path
from types import SimpleNamespace

from dashboard.rocky import applications
from dashboard.rocky.config import Settings
from dashboard.rocky.models import CandidateProfile, JobOffer


class _Repository:
    """Double minimal évitant une base pour ce contrat de génération ciblé."""

    def __init__(self, documents):
        self.documents = documents
        self.created: tuple[object, ...] | None = None

    def fetch_profile_documents(self, _profile_id, _locale):
        return self.documents

    def fetch_latest_application_for_job(self, _job_id, _profile_id):
        return None

    def create_application(self, *values):
        self.created = values
        return 17

    def add_application_document(self, *_values):
        return 1


def test_generated_letter_uses_the_validated_editor_text(tmp_path, monkeypatch):
    """Un template DOCX ne doit jamais écraser la lettre adaptée validée."""
    settings = Settings(
        project_dir=tmp_path, storage_dir_override=str(tmp_path / "data")
    )
    cv_path = tmp_path / "cv_en.pdf"
    cv_path.write_bytes(b"%PDF-1.4\nsource")
    repository = _Repository(
        [
            SimpleNamespace(kind="cv", source_path=str(cv_path), status="ready"),
            SimpleNamespace(kind="letter", source_path="template.docx", status="ready"),
        ]
    )
    captured: list[str] = []

    def fake_create_docx(path: Path, _variables, text: str) -> None:
        captured.append(text)
        path.write_text("edited letter", encoding="utf-8")

    def fake_convert(_source: Path, target: Path) -> None:
        target.write_bytes(b"%PDF-1.4\nletter")

    monkeypatch.setattr(applications, "create_docx", fake_create_docx)
    monkeypatch.setattr(applications, "convert_docx_to_pdf", fake_convert)
    monkeypatch.setattr(
        applications,
        "fill_letter_template",
        lambda *_args: (_ for _ in ()).throw(AssertionError("template used")),
    )

    edited_text = "Nicolas\n\nAcme\n\nParis\n\nSubject\n\nDear team,\n\nAdapted body.\n\nKind regards"
    package = applications.generate_application(
        1,
        CandidateProfile(id=1, profile_name="Nicolas", user_id=1, locale="en"),
        JobOffer("Data Analyst", "Acme", "Responsibilities"),
        edited_text,
        settings,
        repository,  # type: ignore[arg-type]
    )

    assert captured == [edited_text]
    assert Path(package.letter_pdf_path).read_bytes().startswith(b"%PDF-")
