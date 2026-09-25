"""The profile screen and the onboarding through HTTP, as HTMX drives them and without JavaScript."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

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
    assert "étape D2" in section(page.text, "kit")
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


def test_each_category_shows_one_line_and_folds_the_rest(client: TestClient) -> None:
    for name in ("Airflow", "BigQuery", "Docker", "Excel"):
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

    technical, soft = page.split('class="skill-group')[1:3]
    assert technical.startswith(' folded"')
    assert "Tout afficher (5)" in technical
    assert technical.index("Python") < technical.index("Airflow")  # key skills first
    assert not soft.startswith(" folded")
    assert "Tout afficher" not in soft

    python_id = re.search(r"modifier=(\d+)[^>]*>\s*<span class=\"key-mark\"", page)
    assert python_id
    editing = client.get(
        f"/profil/competences?modifier={python_id.group(1)}", headers=HTMX
    ).text
    assert '<details class="skill-more" open>' in editing
    assert 'class="item skill-editing"' in editing


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
