"""The step « Envoi » through HTTP (decision D5): the PDFs generated and kept as they are, the sending linked to the
exact revision, the form handed to a fake workstation.

Exit criterion of D5: « Deux générations → deux PDF distincts récupérables ; l'envoi est lié à la révision exacte ».
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from rocky.candidatures.model import Prefill, Revision, RevisionKind, Sending
from rocky.candidatures.sql import SqlApplicationStore
from rocky.system.workstation import (
    NOT_RUNNING,
    PrefillJob,
    PrefillReport,
    WorkstationUnavailableError,
)
from tests.candidatures.test_letter_web import (
    LETTER,
    LetterModel,
    base,
    form_of,
    letter_desk,
    page,
    sent_form,
)
from tests.candidatures.test_web import Desk, desk_with
from tests.offres.fakes import NOW, TODAY
from tests.system.web_support import make_app, use_model

REPORT = PrefillReport(
    ("Nom complet", "CV", "Lettre"), ("Téléphone : champ introuvable",)
)


class FakeWorkstation:
    """Takes every form, or none when ``error`` is set; keeps what it was handed."""

    def __init__(self) -> None:
        self.jobs: list[PrefillJob] = []
        self.error: str | None = None

    def prefill(self, job: PrefillJob) -> PrefillReport:
        if self.error is not None:
            raise WorkstationUnavailableError(self.error)
        self.jobs.append(job)
        return REPORT


@pytest.fixture
def app(migrated_engine: Engine, tmp_path: Path) -> FastAPI:
    app = make_app(migrated_engine, storage_root=tmp_path)
    app.state.auth.clock.now = NOW
    use_model(app, LetterModel())
    app.state.workstation = FakeWorkstation()
    return app


@pytest.fixture
def desk(app: FastAPI, migrated_engine: Engine) -> Desk:
    """The application of ``test_letter_web``, its letter validated, « Prête à envoyer »."""
    desk = letter_desk(app, migrated_engine)
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk, LETTER)))
    assert desk.client.post(f"{base(desk)}/lettre/prete").status_code == 303
    return desk


def stored(desk: Desk) -> tuple[list[Revision], list[Sending], list[Prefill]]:
    with desk.engine.connect() as connection:
        store = SqlApplicationStore(connection)
        application_id = desk.application_id()
        return (
            store.revisions(application_id),
            store.sendings(application_id),
            store.prefills(application_id),
        )


def generate(desk: Desk) -> None:
    response = desk.client.post(f"{base(desk)}/documents")
    assert response.headers["location"] == f"{base(desk)}?etape=envoi"


def change_the_letter(desk: Desk, app: FastAPI) -> None:
    app.state.auth.clock.advance(timedelta(hours=1))
    fields = form_of(page(desk, f"{LETTER}&modifier=1"))
    fields["texte_1"] = "J'ai conduit des projets pendant huit ans."
    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)


def download(desk: Desk, revision: Revision) -> bytes:
    response = desk.client.get(f"{base(desk)}/documents/{revision.id}.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    return response.content


def letters(revisions: list[Revision]) -> list[Revision]:
    return [r for r in revisions if r.kind is RevisionKind.LETTER]


# Exit criterion of D5.


def test_two_generations_give_two_distinct_pdfs_both_retrievable(
    desk: Desk, app: FastAPI, tmp_path: Path
) -> None:
    generate(desk)
    assert "a changé depuis" not in page(desk)
    change_the_letter(desk, app)
    # The letter in force is no longer the one generated: said, never hidden.
    assert "a changé depuis" in page(desk)

    generate(desk)

    revisions, _, _ = stored(desk)
    assert [r.kind for r in revisions] == [
        RevisionKind.CV,
        RevisionKind.LETTER,
        RevisionKind.CV,
        RevisionKind.LETTER,
    ]
    first, second = letters(revisions)
    assert first.sha256 != second.sha256 and first.path != second.path
    for revision in revisions:
        content = download(desk, revision)
        assert hashlib.sha256(content).hexdigest() == revision.sha256
        assert content == (tmp_path / revision.path).read_bytes()
    # Paths relative to the storage root, under the account (decision A1 → D5).
    assert first.path.startswith(f"comptes/{desk.seeker.account_id}/candidatures/")
    response = desk.client.get(f"{base(desk)}/documents/{second.id}.pdf")
    assert (
        'filename="Lettre_Camille_Martin_FR.pdf"'
        in response.headers["content-disposition"]
    )
    html = page(desk)
    assert "Versions précédentes (2)" in html
    assert "a changé depuis" not in html


def test_the_sending_is_linked_to_the_exact_revision_even_an_older_one(
    desk: Desk, app: FastAPI
) -> None:
    generate(desk)
    change_the_letter(desk, app)
    generate(desk)
    revisions, _, _ = stored(desk)
    older, newer = letters(revisions)
    fields = sent_form(page(desk, "/envoi"))
    assert fields["lettre"] == str(newer.id)  # the latest, checked by default (Q5)
    fields.update(lettre=str(older.id), canal="linkedin")

    response = desk.client.post(f"{base(desk)}/envoi", data=fields)

    assert response.headers["location"] == f"{base(desk)}?etape=suivi"
    _, (sending,), _ = stored(desk)
    assert sending.letter_revision_id == older.id
    assert (sending.sent_on, sending.channel.value) == (TODAY, "linkedin")
    day = TODAY.strftime("%d/%m/%Y")
    assert f"Envoyée le {day} via LinkedIn" in page(desk)  # the step « Suivi »
    html = page(desk, "?etape=envoi")
    assert f"envoyée le {day} via LinkedIn." in html
    sent_part = html[html.index("envoyée le") :]
    assert f'href="{base(desk)}/documents/{older.id}.pdf"' in sent_part
    assert download(desk, older) != download(desk, newer)
    # The letter step names the version of the revision sent, not the latest one.
    letter = page(desk, LETTER)
    assert "Envoyée avec la version du" in letter
    assert "la lettre a été modifiée depuis" in letter


def test_an_altered_file_is_refused_with_its_reason(desk: Desk, tmp_path: Path) -> None:
    generate(desk)
    revisions, _, _ = stored(desk)
    (tmp_path / revisions[0].path).write_bytes(b"%PDF-altered")

    response = desk.client.get(f"{base(desk)}/documents/{revisions[0].id}.pdf")

    assert response.status_code == 409
    assert "a été modifié depuis son enregistrement" in response.text


# The confirmation of a sending (Q3, Q5).


def test_a_sending_is_refused_with_its_reason_and_nothing_written(desk: Desk) -> None:
    html = page(desk, "/envoi")
    assert "Aucun PDF généré" in html
    assert 'value="company_site" selected' in html  # apec.example is not apec.fr
    fields = sent_form(html)
    assert "cv" not in fields  # nothing checked without revision: the user chooses

    refused = desk.client.post(f"{base(desk)}/envoi", data=fields)
    future = desk.client.post(
        f"{base(desk)}/envoi",
        data={**fields, "cv": "aucun", "date": (TODAY + timedelta(days=1)).isoformat()},
    )

    assert "Choisis le CV envoyé" in refused.text
    assert "ne peut pas être dans le futur" in future.text
    assert stored(desk)[1] == []
    assert '<span class="badge badge-accent">Prête à envoyer</span>' in page(desk)


# The form prefilled by the workstation (Q1, Q4, Q6). DORMANT since the acceptance of 04/10: off by default
# (``web.PREFILL_ENABLED``); the tests below switch it on to keep the dormant code working.


@pytest.fixture
def prefill_on(app: FastAPI) -> None:
    app.state.prefill_enabled = True


def test_the_prefilling_is_dormant_no_button_no_route(desk: Desk, app: FastAPI) -> None:
    generate(desk)
    html = page(desk)

    assert "Préremplir" not in html
    assert "Ouvrir le site de candidature" in html
    assert "J'ai envoyé ma candidature</summary>" in html
    assert desk.client.get(f"{base(desk)}/preremplir").status_code == 404
    response = desk.client.post(f"{base(desk)}/preremplir", data={"consentement": "1"})
    assert response.status_code == 404
    assert app.state.workstation.jobs == []


def panel_ids(html: str) -> dict[str, str]:
    form = html[html.index('id="preremplir"') :]
    return dict(re.findall(r'type="hidden" name="(cv|lettre)" value="(\w+)"', form))


def test_the_workstation_gets_the_exact_revisions_after_confirmation(
    desk: Desk, app: FastAPI, tmp_path: Path, prefill_on: None
) -> None:
    generate(desk)
    panel = page(desk, "/preremplir")
    assert "Camille Martin" in panel
    assert "CV_Camille_Martin_FR.pdf" in panel
    shown = panel_ids(panel)

    without = desk.client.post(f"{base(desk)}/preremplir", data=shown)
    assert "Coche la confirmation" in without.text
    assert app.state.workstation.jobs == []

    response = desk.client.post(
        f"{base(desk)}/preremplir",
        data={"consentement": "1", **shown},
    )

    assert response.headers["location"] == f"{base(desk)}?etape=envoi"
    (job,) = app.state.workstation.jobs
    revisions, _, (prefill,) = stored(desk)
    assert job.target_url == "https://apec.example/offres/d1"
    assert ("full_name", "Camille Martin") in job.fields
    assert [(f.kind, f.name) for f in job.files] == [
        ("cv", "CV_Camille_Martin_FR.pdf"),
        ("letter", "Lettre_Camille_Martin_FR.pdf"),
    ]
    assert [f.content for f in job.files] == [
        (tmp_path / r.path).read_bytes() for r in revisions
    ]
    assert (prefill.cv_revision_id, prefill.letter_revision_id) == tuple(
        r.id for r in revisions
    )
    html = page(desk)
    assert '<span class="badge badge-accent">Préremplie</span>' in html
    assert "À faire toi-même : Téléphone : champ introuvable." in html


def test_a_workstation_that_does_not_take_the_form_writes_nothing(
    desk: Desk, app: FastAPI, prefill_on: None
) -> None:
    generate(desk)
    shown = panel_ids(page(desk, "/preremplir"))
    app.state.workstation.error = NOT_RUNNING

    response = desk.client.post(
        f"{base(desk)}/preremplir",
        data={"consentement": "1", **shown},
    )

    assert "uv run rocky-poste" in response.text
    assert stored(desk)[2] == []
    assert '<span class="badge badge-accent">Prête à envoyer</span>' in page(desk)


def test_revisions_generated_after_the_confirmation_are_not_handed_over(
    desk: Desk, app: FastAPI, prefill_on: None
) -> None:
    generate(desk)
    shown = panel_ids(page(desk, "/preremplir"))
    generate(desk)

    response = desk.client.post(
        f"{base(desk)}/preremplir",
        data={"consentement": "1", **shown},
    )

    assert "ont changé depuis l&#39;affichage" in response.text
    assert app.state.workstation.jobs == []


def test_the_revisions_of_another_account_are_not_found(
    app: FastAPI, migrated_engine: Engine, desk: Desk
) -> None:
    generate(desk)
    revisions, _, _ = stored(desk)
    other = desk_with(app, migrated_engine)

    assert (
        other.client.get(f"{base(desk)}/documents/{revisions[0].id}.pdf").status_code
        == 404
    )
    assert other.client.post(f"{base(desk)}/documents", data={}).status_code == 404
    assert other.client.post(f"{base(desk)}/envoi", data={}).status_code == 404
    assert other.client.post(f"{base(desk)}/preremplir", data={}).status_code == 404
    # Nor a revision through another application of one's own.
    assert desk.client.get(f"{base(desk)}/documents/{10**9}.pdf").status_code == 404
