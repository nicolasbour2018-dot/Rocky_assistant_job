"""The profile screen and the onboarding through HTTP, as HTMX drives them and without JavaScript."""

from __future__ import annotations

import io
import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine

from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import record_offer
from rocky.profil.rules import make_project
from rocky.profil.web import cv_drawing
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.pdf_read import read_pdf
from tests.offres.fakes import NOW, TODAY, Seeker, posting
from tests.profil.cv.fixtures import ReaderModel, designed_cv, image_only_cv
from tests.system.web_support import HTMX, logged_in, make_app

TRACK = {
    "name": "Data analyst",
    "titles": "Data Analyst\nBI Analyst",
    "locations": "Paris",
    "keywords": "SQL",
    "excluded_keywords": "stage",
}


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    return make_app(migrated_engine)


@pytest.fixture
def client(app: FastAPI, migrated_engine: Engine) -> TestClient:
    return logged_in(app, migrated_engine)[0]


@pytest.fixture
def newcomer(app: FastAPI, migrated_engine: Engine) -> TestClient:
    """A just activated account, onboarding not done nor put off."""
    return logged_in(app, migrated_engine, onboarding=True)[0]


def section(html: str, key: str) -> str:
    match = re.search(rf'<section id="section-{key}".*?</section>', html, re.DOTALL)
    assert match, f"no section {key}"
    return match.group(0)


# Onboarding


@pytest.mark.parametrize("path", ["/", "/offres", "/candidatures", "/systeme"])
def test_main_pages_lead_a_newcomer_to_the_onboarding(
    newcomer: TestClient, path: str
) -> None:
    response = newcomer.get(path)

    assert response.status_code == 303
    assert response.headers["location"] == "/profil/demarrage"


def test_the_profile_and_fragments_are_never_redirected(newcomer: TestClient) -> None:
    assert newcomer.get("/profil").status_code == 200
    assert newcomer.get("/profil/demarrage").status_code == 200
    assert newcomer.get("/offres/liste", headers=HTMX).status_code == 200


def test_the_drawer_of_the_profile_asks_for_a_track_first(client: TestClient) -> None:
    """Decision F1, Q12: without an active track the watch finds nothing."""
    before = client.get("/tiroir?ecran=profile", headers=HTMX).text
    client.post("/profil/pistes", data=TRACK)
    after = client.get("/tiroir?ecran=profile", headers=HTMX).text

    assert 'href="/profil/pistes">Définir une piste</a>' in before
    assert 'href="/profil/kit">Voir le CV et le kit</a>' in after


def test_the_guided_onboarding_ends_when_a_track_can_run(newcomer: TestClient) -> None:
    step1 = newcomer.post(
        "/profil/demarrage/identite",
        data={"full_name": "Nicolas Exemple", "city": "Paris", "contact_email": ""},
    )
    assert step1.headers["location"] == "/profil/demarrage?etape=2"

    step2 = newcomer.post(
        "/profil/demarrage/competences",
        data={"technical": "Python\nSQL\n", "business": "", "soft": "Curiosité"},
    )
    assert step2.headers["location"] == "/profil/demarrage?etape=3"

    incomplete = newcomer.post(
        "/profil/demarrage/piste",
        data={"name": "Data analyst", "titles": "Data Analyst"},
    )
    assert incomplete.status_code == 400
    assert "au moins un intitulé et un lieu" in incomplete.text
    assert "Data Analyst" in incomplete.text  # what was typed is kept

    done = newcomer.post("/profil/demarrage/piste", data=TRACK)
    assert done.headers["location"] == "/profil"

    assert newcomer.get("/").status_code == 200
    profile = newcomer.get("/profil").text
    assert "Nicolas Exemple" in profile
    assert "il manque" not in profile
    assert "Curiosité" in section(profile, "competences")


def test_a_boosted_onboarding_error_keeps_a_reloadable_address(
    newcomer: TestClient,
) -> None:
    refused = newcomer.post(
        "/profil/demarrage/piste",
        data={"name": "IA"},
        headers={**HTMX, "HX-Boosted": "true"},
    )

    assert refused.status_code == 200
    assert refused.headers["HX-Replace-Url"] == "/profil/demarrage?etape=3"


def test_onboarding_reports_skills_already_there(newcomer: TestClient) -> None:
    newcomer.post("/profil/demarrage/competences", data={"technical": "Python"})

    again = newcomer.post("/profil/demarrage/competences", data={"technical": "python"})

    assert again.status_code == 200
    assert "Déjà dans ton profil, non ajoutées : python." in again.text


def test_onboarding_keeps_a_name_like_a_skill_as_its_other_name(
    newcomer: TestClient,
) -> None:
    newcomer.post("/profil/demarrage/competences", data={"technical": "MLFlow"})

    again = newcomer.post(
        "/profil/demarrage/competences", data={"technical": "ML Flow"}
    )

    assert (
        "Ajoutées comme autre nom d&#39;une compétence : ML Flow → MLFlow."
        in again.text
    )


def test_onboarding_skips_the_empty_lines_of_a_list(newcomer: TestClient) -> None:
    response = newcomer.post(
        "/profil/demarrage/competences", data={"technical": "Python\n\n  \nSQL\n"}
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("etape=3")


def test_putting_off_leaves_a_reminder_on_the_profile(newcomer: TestClient) -> None:
    later = newcomer.post("/profil/demarrage/plus-tard")

    assert later.headers["location"] == "/profil"
    assert newcomer.get("/").status_code == 200
    profile = newcomer.get("/profil").text
    assert (
        "Pour que la veille puisse tourner, il manque : ton nom, tes compétences"
        in (profile)
    )
    assert 'href="/profil/demarrage"' in profile


# Sections, with HTMX


def test_the_page_shows_every_section(client: TestClient) -> None:
    page = client.get("/profil")

    assert page.status_code == 200
    for key in ("pistes", "competences", "langues", "parcours", "projets", "identite"):
        assert f'id="section-{key}"' in page.text
    assert "CV maître" in section(page.text, "kit")
    assert "Facultatif" in section(page.text, "projets")


def test_a_track_is_added_in_place(client: TestClient) -> None:
    form = client.get("/profil/pistes?modifier=nouveau", headers=HTMX)
    assert form.status_code == 200
    assert form.text.lstrip().startswith('<section id="section-pistes"')
    assert 'hx-post="/profil/pistes"' in form.text

    saved = client.post("/profil/pistes", data=TRACK, headers=HTMX)

    assert saved.status_code == 200
    assert "<h3>Data analyst</h3>" in saved.text
    assert "Data Analyst · BI Analyst" in saved.text
    assert "<form" not in saved.text.split("Data analyst")[1].split("Modifier")[0]


def test_a_track_location_the_reference_does_not_know_is_reported(
    client: TestClient,
) -> None:
    track = {**TRACK, "locations": "Ile de France\nEure et Loire\nTélétravail complet"}

    saved = client.post("/profil/pistes", data=track, headers=HTMX)

    assert "Lieu non reconnu : « Eure et Loire »" in saved.text
    assert "« Ile de France » ;" not in saved.text
    assert "« Télétravail complet » ;" not in saved.text
    track_id = re.search(r"/profil/pistes/(\d+)/pause", saved.text)
    assert track_id
    fixed = client.post(
        f"/profil/pistes/{track_id.group(1)}",
        data={**track, "locations": "Eure-et-Loir"},
        headers=HTMX,
    )
    assert "Lieu non reconnu" not in fixed.text


def test_a_refused_track_keeps_what_was_typed(client: TestClient) -> None:
    refused = client.post(
        "/profil/pistes",
        data={**TRACK, "keywords": "Stage", "excluded_keywords": "stage"},
        headers=HTMX,
    )

    assert refused.status_code == 200  # HTMX only swaps 2xx answers
    assert "à la fois un mot-clé et un mot exclu" in refused.text
    assert "BI Analyst" in refused.text


def test_without_javascript_forms_redirect_or_show_the_whole_page(
    client: TestClient,
) -> None:
    saved = client.post("/profil/pistes", data=TRACK)
    assert saved.status_code == 303
    assert saved.headers["location"] == "/profil#section-pistes"

    refused = client.post("/profil/pistes", data=TRACK)
    assert refused.status_code == 400
    assert "Une piste s&#39;appelle déjà « Data analyst »" in refused.text
    assert 'class="sidebar"' in refused.text

    whole = client.get("/profil/pistes?modifier=nouveau")
    assert 'class="sidebar"' in whole.text
    assert 'hx-post="/profil/pistes"' in whole.text


def test_a_boosted_navigation_gets_a_whole_page(client: TestClient) -> None:
    boosted = client.get("/profil/pistes", headers={**HTMX, "HX-Boosted": "true"})

    assert 'class="sidebar"' in boosted.text


def test_track_life_cycle_on_screen(client: TestClient) -> None:
    client.post("/profil/pistes", data=TRACK)
    track_id = re.search(r"/profil/pistes/(\d+)/pause", client.get("/profil").text)
    assert track_id
    base = f"/profil/pistes/{track_id.group(1)}"

    paused = client.post(f"{base}/pause", headers=HTMX)
    assert "En pause" in paused.text
    assert f"{base}/reprendre" in paused.text

    archived = client.post(f"{base}/archiver", headers=HTMX)
    assert "Pistes archivées (1)" in archived.text
    assert "Supprimer définitivement" in archived.text

    deleted = client.post(f"{base}/supprimer", headers=HTMX)
    assert "Data analyst" not in deleted.text
    assert client.post(f"{base}/supprimer", headers=HTMX).status_code == 404


def test_a_skill_known_under_another_name_is_refused_on_screen(
    client: TestClient,
) -> None:
    client.post(
        "/profil/competences",
        data={
            "label_fr": "NLP",
            "label_en": "Natural Language Processing (NLP)",
            "aliases": "Traitement du langage naturel (NLP)",
            "category": "technical",
            "level": "advanced",
            "is_key": "1",
        },
    )

    refused = client.post(
        "/profil/competences",
        data={
            "label_fr": "traitement du langage naturel (NLP)",
            "category": "technical",
        },
        headers=HTMX,
    )

    assert "est déjà présent sous « NLP »" in refused.text
    page = section(client.get("/profil").text, "competences")
    assert page.count('class="skill"') == 1
    assert "Avancé" in page
    # Aliases are an inner working: never shown in the list, folded in the edit form.
    assert "Traitement du langage naturel" not in page
    skill_id = re.search(r"/profil/competences\?modifier=(\d+)", page)
    assert skill_id
    form = client.get(f"/profil/competences?modifier={skill_id.group(1)}").text
    assert '<details class="field-more">' in form
    assert "Autres noms (alias) · 1" in form


def test_each_category_shows_five_skills_and_folds_the_rest(
    client: TestClient,
) -> None:
    for name in ("Airflow", "BigQuery", "Docker", "Excel", "FastAPI", "Git"):
        client.post(
            "/profil/competences", data={"label_fr": name, "category": "technical"}
        )
    client.post(
        "/profil/competences",
        data={"label_fr": "Python", "category": "technical", "is_key": "1"},
    )
    client.post(
        "/profil/competences", data={"label_fr": "Curiosité", "category": "soft"}
    )

    page = section(client.get("/profil").text, "competences")

    technical, soft = page.split('class="skill-group"')[1:3]
    shown, folded = technical.split('<details class="skill-more">')
    assert shown.count('class="skill"') == 5
    assert shown.index("Python") < shown.index("Airflow")  # key skills first
    assert "Tout afficher (+2)" in folded
    assert folded.count('class="skill"') == 2
    assert "Tout afficher" not in soft

    git_id = re.search(r"modifier=(\d+)\"[^>]*>\s*Git</a>", page)
    assert git_id
    editing = client.get(
        f"/profil/competences?modifier={git_id.group(1)}", headers=HTMX
    )
    assert '<details class="skill-more" open>' in editing.text
    assert 'class="item skill-editing"' in editing.text


def test_the_language_switch_shows_english_or_marks_what_is_missing(
    client: TestClient,
) -> None:
    client.post(
        "/profil/competences",
        data={
            "label_fr": "Visualisation de données",
            "label_en": "Data visualization",
            "category": "technical",
        },
    )
    client.post(
        "/profil/competences", data={"label_fr": "Curiosité", "category": "soft"}
    )

    english = client.get("/profil/competences?langue=en", headers=HTMX).text

    assert "Data visualization" in english
    assert "Visualisation de données" not in english
    assert re.search(
        r'untranslated">Curiosité</span> <span class="badge badge-muted"', english
    )
    assert re.search(r'langue=en"[^>]*aria-current="page"', english)


def test_projects_read_as_prose(client: TestClient) -> None:
    client.post(
        "/profil/projets",
        data={
            "name_fr": "Finance connectée",
            "problem_fr": "Suivre ses dépenses sans tableur.",
            "stack": "Python\nFastAPI",
        },
    )

    projects = section(client.get("/profil").text, "projets")

    assert "Finance connectée" in projects
    assert "<dt>Problème</dt>" in projects
    assert "Réalisation" not in projects.split("Supprimer")[0].split("</dl>")[0]
    assert "{&#39;" not in projects  # never a raw dictionary (v1 bug)


def test_an_experience_links_skills_of_the_profile(client: TestClient) -> None:
    client.post(
        "/profil/competences", data={"label_fr": "SQL", "category": "technical"}
    )
    skill_id = re.search(
        r"/profil/competences\?modifier=(\d+)", client.get("/profil").text
    )
    assert skill_id

    saved = client.post(
        "/profil/parcours",
        data={
            "kind": "job",
            "title_fr": "Analyste de données",
            "organisation": "Exemple SA",
            "start": "2022-03",
            "end": "",
            "bullets_fr": "Tableaux de bord\nRequêtes SQL",
            "skills": skill_id.group(1),
        },
        headers=HTMX,
    )

    assert "mars 2022 – aujourd&#39;hui" in saved.text
    assert "<li>Requêtes SQL</li>" in saved.text
    assert 'badge badge-accent">SQL' in saved.text


def test_identity_and_preferences_are_saved_separately(client: TestClient) -> None:
    client.post(
        "/profil/identite",
        data={"full_name": "Nicolas", "city": "Paris", "headline_fr": "Data scientist"},
    )
    saved = client.post(
        "/profil/preferences",
        data={
            "contracts": ["permanent", "freelance"],
            "min_salary_eur": "45000",
            "min_daily_rate_eur": "450",
        },
        headers=HTMX,
    )

    assert "CDI · Freelance" in saved.text
    assert "45 000 € brut / an" in saved.text
    assert "450 € HT / jour" in saved.text
    assert "Nicolas" in saved.text


def test_items_of_another_account_are_out_of_reach(
    app: FastAPI, migrated_engine: Engine, client: TestClient
) -> None:
    client.post("/profil/pistes", data=TRACK)
    track_id = re.search(r"/profil/pistes/(\d+)/pause", client.get("/profil").text)
    assert track_id
    other, _ = logged_in(app, migrated_engine)

    assert (
        other.get(
            f"/profil/pistes?modifier={track_id.group(1)}", headers=HTMX
        ).status_code
        == 404
    )
    assert (
        other.post(
            f"/profil/pistes/{track_id.group(1)}/archiver", headers=HTMX
        ).status_code
        == 404
    )


def test_unknown_sections_and_actions_are_not_found(client: TestClient) -> None:
    assert client.get("/profil/inconnue").status_code == 404
    assert client.post("/profil/pistes/1/voler").status_code == 404


def test_a_track_with_offers_is_archived_not_deleted_on_screen(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, email = logged_in(app, migrated_engine)
    client.post("/profil/pistes", data=TRACK)
    with migrated_engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        seeker = Seeker(account.id, email)
        profile = seeker.profile(connection)
        record_offer(
            SqlStore(connection),
            account_id=account.id,
            offer=posting("p1"),
            inputs=scoring_inputs(profile),
            origin=Origin.WATCH,
            track_ids=[profile.tracks[0].id],
            now=NOW,
            today=TODAY,
        )
    base = f"/profil/pistes/{profile.tracks[0].id}"

    refused = client.post(f"{base}/supprimer", headers=HTMX)

    assert refused.status_code == 200
    assert "Des offres sont rattachées à cette piste : archive-la plutôt." in (
        refused.text.replace("&#39;", "'")
    )
    assert "Data analyst" in section(client.get("/profil").text, "pistes")


# Master CV (section « kit », decision D2)


def png(side: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (side, side), "teal").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def files_client(migrated_engine: Engine, tmp_path: Path) -> TestClient:
    return logged_in(make_app(migrated_engine, storage_root=tmp_path), migrated_engine)[
        0
    ]


def test_a_group_is_created_filled_and_ordered_in_place(client: TestClient) -> None:
    for name in ("Python", "SQL"):
        client.post(
            "/profil/competences",
            data={"label_fr": name, "category": "technical"},
            headers=HTMX,
        )
    created = client.post(
        "/profil/cv/groupe-ajouter",
        data={"name_fr": "Langages et Data", "name_en": "Languages and data"},
        headers=HTMX,
    )
    assert created.status_code == 200
    kit = section(created.text, "kit")
    assert "Langages et Data" in kit
    options = {
        label: value
        for value, label in re.findall(r'<option value="(\d+)">([^<]+)</option>', kit)
    }

    for name in ("Python", "SQL"):
        client.post(
            "/profil/cv/competence-placer",
            data={"id": options[name], "group": "0"},
            headers=HTMX,
        )
    moved = client.post(
        "/profil/cv/competence-monter", data={"id": options["SQL"]}, headers=HTMX
    )

    kit = section(moved.text, "kit")
    assert kit.index("SQL") < kit.index("Python")


def test_a_refused_gesture_says_why_in_the_section(client: TestClient) -> None:
    client.post("/profil/cv/groupe-ajouter", data={"name_fr": "Data"}, headers=HTMX)

    refused = client.post(
        "/profil/cv/groupe-ajouter", data={"name_fr": "DATA"}, headers=HTMX
    )

    assert refused.status_code == 200
    assert "existe déjà" in section(refused.text, "kit")
    assert client.post("/profil/cv/inconnu", data={}, headers=HTMX).status_code == 404


def test_a_photo_is_uploaded_served_and_removed(files_client: TestClient) -> None:
    content = png(300)

    uploaded = files_client.post(
        "/profil/photo",
        files={"photo": ("moi.png", content, "image/png")},
        headers=HTMX,
    )

    assert uploaded.status_code == 200
    assert 'class="cv-photo"' in section(uploaded.text, "kit")
    served = files_client.get("/profil/cv/photo")
    assert served.content == content
    assert served.headers["content-type"] == "image/png"
    files_client.post("/profil/photo/retirer", headers=HTMX)
    assert files_client.get("/profil/cv/photo").status_code == 404


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"not an image", "pas une image"), (png(40), "trop petite")],
)
def test_a_wrong_photo_is_refused(
    files_client: TestClient, content: bytes, message: str
) -> None:
    refused = files_client.post(
        "/profil/photo", files={"photo": ("x.png", content, "image/png")}, headers=HTMX
    )

    assert message in section(refused.text, "kit")
    assert files_client.get("/profil/cv/photo").status_code == 404


def test_without_storage_the_photo_says_it_is_not_configured(
    client: TestClient,
) -> None:
    refused = client.post(
        "/profil/photo", files={"photo": ("x.png", png(300), "image/png")}, headers=HTMX
    )

    assert "ROCKY_STORAGE_ROOT" in section(refused.text, "kit")


def test_the_cv_is_downloaded_as_one_pdf_page(client: TestClient) -> None:
    client.post(
        "/profil/identite",
        data={"full_name": "Camille Martin", "title_fr": "Data Scientist"},
        headers=HTMX,
    )

    response = client.get("/profil/cv/pdf?langue=fr")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="CV_Camille_Martin_FR.pdf"; '
        "filename*=UTF-8''CV_Camille_Martin_FR.pdf"
    )
    assert response.content.startswith(b"%PDF")


def test_a_name_outside_latin_1_downloads_its_cv(client: TestClient) -> None:
    """Step H1: the raw name in ``Content-Disposition`` was a UnicodeEncodeError."""
    client.post("/profil/identite", data={"full_name": "Łukasz Ñandú"}, headers=HTMX)

    response = client.get("/profil/cv/pdf?langue=fr")

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(
        "filename*=UTF-8''CV_%C5%81ukasz_%C3%91and%C3%BA_FR.pdf"
    )


def test_a_superscript_digit_is_no_number(client: TestClient) -> None:
    """Step H1: ``"²".isdigit()`` is true, ``int("²")`` fails: it was a 500."""
    assert client.get("/profil/competences?modifier=²").status_code == 404
    assert client.get("/profil/kit?modifier=groupe-²").status_code == 404
    removed = client.post(
        "/profil/cv/groupe-retirer", data={"index": "²"}, headers=HTMX
    )
    assert removed.status_code == 200


def test_a_cv_download_link_is_a_plain_navigation(client: TestClient) -> None:
    # The layout boosts every link: a boosted download swaps the PDF bytes into the page and freezes the tab.
    kit = section(client.get("/profil").text, "kit")

    links = re.findall(r'<a [^>]*href="/profil/cv/pdf[^"]*"[^>]*>', kit)

    assert links
    for link in links:
        assert 'target="_blank"' in link or 'hx-boost="false"' in link, link


def test_an_english_cv_waits_for_its_english_texts(client: TestClient) -> None:
    client.post(
        "/profil/identite",
        data={"full_name": "Camille Martin", "title_fr": "Data Scientiste"},
        headers=HTMX,
    )

    page = client.get("/profil")
    refused = client.get("/profil/cv/pdf?langue=en")

    assert "Identité : titre du CV" in section(page.text, "kit")
    assert refused.status_code == 400
    assert "attend encore" in section(refused.text, "kit")


def test_checking_the_cv_shows_what_each_reader_finds(client: TestClient) -> None:
    client.post(
        "/profil/identite",
        data={"full_name": "Camille Martin", "contact_email": "c@example.org"},
        headers=HTMX,
    )

    checked = client.post("/profil/cv/verifier", data={"langue": "fr"}, headers=HTMX)

    kit = section(checked.text, "kit")
    assert 'class="cv-check"' in kit
    assert "pdfminer.six :" in kit
    assert "accord entre lecteurs" in kit


# Import of a CV PDF (decision D2, Q2, Q14, Q16)


@pytest.fixture
def importer(migrated_engine: Engine, tmp_path: Path) -> TestClient:
    app = make_app(migrated_engine, storage_root=tmp_path)
    app.state.llm_model = ReaderModel()
    return logged_in(app, migrated_engine)[0]


def test_importing_needs_the_consent_to_send_the_text(importer: TestClient) -> None:
    refused = importer.post(
        "/profil/import-cv",
        files={"fichier": ("cv.pdf", b"%PDF-1.7", "application/pdf")},
        headers=HTMX,
    )

    assert "Coche l&#39;accord" in section(refused.text, "kit")


def test_an_imported_cv_proposes_its_content_and_its_template(
    importer: TestClient,
) -> None:
    importer.post(
        "/profil/identite",
        data={
            "full_name": "Camille Martin",
            "contact_email": "camille.martin@example.org",
        },
        headers=HTMX,
    )
    page = importer.post(
        "/profil/import-cv",
        data={"consentement": "1"},
        files={"fichier": ("cv.pdf", designed_cv(), "application/pdf")},
    )

    assert page.status_code == 200
    assert "Rendu par Rocky" in page.text
    assert "Tri des messages clients" in page.text
    address = re.search(r'action="(/profil/import-cv/\w+)/identite"', page.text)
    assert address
    added = importer.post(
        f"{address.group(1)}/identite", data={"choix": ["0", "1", "4"]}
    )
    assert "Identité : 2 éléments ajoutés." in added.text  # the name was there already
    template = re.search(r'action="(/profil/gabarit/\d+/activer)"', page.text)
    assert template

    kit = section(importer.post(template.group(1), headers=HTMX).text, "kit")

    assert "CV français : CV français importé le" in " ".join(kit.split())
    cv = importer.get("/profil/cv/pdf?langue=fr")
    assert cv.headers["content-type"] == "application/pdf"
    assert "Camille Martin" in " ".join(read_pdf(cv.content)[0].text.split()).title()


def test_an_altered_template_refuses_a_cv_gesture_with_its_reason(
    importer: TestClient, tmp_path: Path
) -> None:
    """Step H1: the room of an altered template (``_slots``) was a FileError, then a 500."""
    page = importer.post(
        "/profil/import-cv",
        data={"consentement": "1"},
        files={"fichier": ("cv.pdf", designed_cv(), "application/pdf")},
    )
    template = re.search(r'action="(/profil/gabarit/\d+/activer)"', page.text)
    assert template
    importer.post(template.group(1), headers=HTMX)
    for manifest in tmp_path.rglob("SHA256SUMS"):
        manifest.write_text(manifest.read_text() + "altéré\n")

    response = importer.post(
        "/profil/cv/groupe-ajouter", data={"name_fr": "Outils"}, headers=HTMX
    )

    assert response.status_code == 200
    assert response.headers["HX-Retarget"] == "#erreur"
    assert "Ton gabarit de CV est illisible" in response.text


def test_an_image_pdf_is_refused_and_the_neutral_template_stays(
    importer: TestClient,
) -> None:
    refused = importer.post(
        "/profil/import-cv",
        data={"consentement": "1"},
        files={"fichier": ("cv.pdf", image_only_cv(), "application/pdf")},
        headers=HTMX,
    )

    kit = section(refused.text, "kit")
    assert "pas de texte lisible" in kit
    assert "CV français : gabarit neutre de Rocky" in " ".join(kit.split())


def test_a_template_no_longer_used_is_deleted_after_confirmation(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """Decision D6, Q8: « Supprimer… » under « Autres gabarits »; the template in service has no such button."""
    browser, email = logged_in(app, migrated_engine)
    with migrated_engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        editor = Seeker(account.id, email).editor(connection)
        used = editor.record_cv_template("comptes/x/u", "u", "CV en service", "fr")
        trial = editor.record_cv_template(
            "comptes/x/t", "t", "Essai de mise au point", "fr"
        )
        editor.activate_cv_template(used, "fr")
    kit = section(browser.get("/profil").text, "kit")
    assert f'action="/profil/gabarit/{trial}/supprimer"' in kit
    assert f'action="/profil/gabarit/{used}/supprimer"' not in kit

    deleted = browser.post(f"/profil/gabarit/{trial}/supprimer", headers=HTMX)

    assert "Essai de mise au point" not in section(deleted.text, "kit")
    assert "CV en service" in section(deleted.text, "kit")
    refused = browser.post(f"/profil/gabarit/{used}/supprimer", headers=HTMX)
    assert "celui de ton CV" in refused.text


def test_a_skill_like_another_is_offered_as_its_other_name_in_one_gesture(
    client: TestClient,
) -> None:
    """Step G5: « ML Flow » typed next to « MLFlow » is refused with a button that keeps it as an alias."""
    client.post(
        "/profil/competences", data={"label_fr": "MLFlow", "category": "technical"}
    )

    refused = client.post(
        "/profil/competences",
        data={
            "label_fr": "ML Flow",
            "aliases": "MLflow Tracking",
            "category": "technical",
        },
        headers=HTMX,
    )

    assert "« ML Flow » ressemble à « MLFlow »" in refused.text
    action = re.search(r'hx-post="(/profil/competences/\d+/autre-nom)"', refused.text)
    assert action, "no alias gesture"
    names = re.findall(r'type="hidden" name="names" value="([^"]*)"', refused.text)
    assert names == ["ML Flow", "MLflow Tracking"]

    saved = client.post(action.group(1), data={"names": names}, headers=HTMX)

    page = section(saved.text, "competences")
    assert page.count('class="skill"') == 1
    assert "ressemble" not in page
    skill_id = action.group(1).split("/")[3]
    edit = client.get(f"/profil/competences?modifier={skill_id}")
    assert re.findall(r'name="aliases"[^>]*>([^<]*)<', edit.text) == [
        "ML Flow\nMLflow Tracking"
    ]


@pytest.mark.parametrize(
    ("who", "path"),
    [
        ("client", "/profil/pistes?modifier=nouveau"),
        ("newcomer", "/profil/demarrage?etape=3"),
    ],
)
def test_the_track_lists_say_one_per_line_and_what_an_excluded_word_does(
    request: pytest.FixtureRequest, who: str, path: str
) -> None:
    """Step G5: the help said excluded words discard adverts (false since C4) and not that a list is one per line."""
    page = request.getfixturevalue(who).get(path).text

    assert (
        "un mot exclu plafonne son score ; dans sa description, il est seulement signalé"
        in page
    )
    assert "un par ligne ou séparés par des virgules" in page
    assert "département (nom ou numéro)" in page
    assert "sont écartées" not in page


def test_the_kit_says_what_the_neutral_template_cuts(client: TestClient) -> None:
    """Step G5: a paragraph beyond its limit is cut to hold one page, and Profil & kit says so (Q1)."""
    client.post(
        "/profil/parcours",
        data={
            "kind": "job",
            "title_fr": "Analyste de données",
            "organisation": "Exemple SA",
            "start": "2022-03",
            "end": "",
            "bullets_fr": "Tableaux de bord " * 20,
        },
        headers=HTMX,
    )

    kit = section(client.get("/profil").text, "kit")

    assert (
        "CV français : pour tenir sur une page, le gabarit neutre a coupé 1 texte"
        in kit
    )
    assert "Expérience « Analyste de données », puce 1 : coupé à 140 caractères." in kit


def test_a_project_spilling_out_of_its_card_is_named_to_shorten(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Recette of G5: the CV preview of an application links to the project to shorten in the profile."""
    app = make_app(migrated_engine, storage_root=tmp_path)
    app.state.llm_model = ReaderModel()
    browser, email = logged_in(app, migrated_engine)
    page = browser.post(
        "/profil/import-cv",
        data={"consentement": "1"},
        files={"fichier": ("cv.pdf", designed_cv(), "application/pdf")},
    )
    template = re.search(r'action="(/profil/gabarit/\d+/activer)"', page.text)
    assert template
    browser.post(template.group(1), headers=HTMX)
    with migrated_engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        editor = Seeker(account.id, email).editor(connection)
        long = editor.add_project(
            make_project(
                name_fr="Trop long", problem_fr="Des milliers de messages. " * 30
            )
        )
        profile = editor.profile()
    profile = replace(profile, cv=replace(profile.cv, projects=(long,)))
    request = Request({"type": "http", "app": app, "headers": []})

    drawing = cv_drawing(request, account, profile, "fr")

    assert drawing.projects_to_shorten == ((long, "Trop long"),)
    assert any("carte du projet 1" in problem for problem in drawing.problems)


def test_a_profile_page_offers_the_way_back_to_the_application(
    client: TestClient,
) -> None:
    back = client.get("/profil/projets?retour=%2Fcandidatures%2F3%3Fetape%3Dcv").text

    assert 'href="/candidatures/3?etape=cv">← Revenir à la candidature</a>' in back
    for elsewhere in ("https://evil.example", "//evil.example", "/candidatures/3/../x"):
        page = client.get("/profil/projets", params={"retour": elsewhere}).text
        assert "Revenir à la candidature" not in page
