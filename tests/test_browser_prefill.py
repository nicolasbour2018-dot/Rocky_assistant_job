"""Contrats du préremplissage Playwright supervisé."""

from playwright.sync_api import sync_playwright

from dashboard.rocky import browser_apply
from dashboard.rocky.config import Settings
from scripts.prefill_application import FIELD_SELECTORS, _fill_first, _upload_documents


def test_prefill_process_uses_module_mode(tmp_path, monkeypatch):
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeRepository:
        user_id = 7

        def fetch_application(self, application_id: int):
            assert application_id == 22
            return {
                "application_url": "https://jobs.example/apply/22",
                "full_name": "Camille Test",
                "email": "camille@example.test",
                "phone": "0102030405",
                "cv_path": "cv.pdf",
                "letter_pdf_path": "lettre.pdf",
            }

        def create_browser_session(self, application_id: int, target_url: str):
            assert (application_id, target_url) == (22, "https://jobs.example/apply/22")
            return 73

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr(browser_apply.subprocess, "Popen", fake_popen)
    report = browser_apply.start_prefill(
        22,
        Settings(project_dir=tmp_path),
        FakeRepository(),
        confirmed=True,
    )

    assert report.status == "STARTING"
    assert calls[0][0][1:3] == ["-m", "scripts.prefill_application"]
    assert calls[0][0][-2:] == ["--user-id", "7"]
    assert calls[0][1]["cwd"] == tmp_path


def test_prefill_fixture_never_submits(tmp_path):
    cv = tmp_path / "cv.pdf"
    letter = tmp_path / "letter.pdf"
    cv.write_bytes(b"%PDF-test-cv")
    letter.write_bytes(b"%PDF-test-letter")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(
            """
            <form onsubmit="window.submitted=true; return false">
              <input type="text" autocomplete="name">
              <input type="email">
              <input type="file" name="resume">
              <input type="file" name="cover_letter">
              <button type="submit">Envoyer</button>
            </form>
            """
        )
        assert _fill_first(page, FIELD_SELECTORS["Nom complet"], "Camille Test")
        assert _fill_first(page, FIELD_SELECTORS["E-mail"], "camille@example.test")
        filled, missing = _upload_documents(page, cv, letter)
        assert filled == ["CV", "Lettre"]
        assert missing == []
        assert page.evaluate("window.submitted === true") is False
        browser.close()
