"""The page of an application and its step « CV » through HTTP (decision D3, Q1, Q4, Q9, Q11, Q23)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select

from rocky.candidatures import dossier_web
from rocky.profil import web as profil_web
from rocky.profil.model import CvLayout, SkillGroup, Text
from rocky.profil.rules import make_identity, make_project, make_skill
from rocky.system.events import events
from tests.candidatures.test_web import Desk, desk_with
from tests.offres.fakes import NOW, TODAY
from tests.system.web_support import HTMX, make_app


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.auth.clock.now = NOW
    return app


@pytest.fixture
def desk(app: FastAPI, migrated_engine: Engine) -> Desk:
    return dossier_with(app, migrated_engine)


def dossier_with(app: FastAPI, migrated_engine: Engine) -> Desk:
    """An open application on an offer asking Python and SQL (« Un plus : Tableau »), and a master CV holding one
    group « Langages » (Tableau, Python), the soft skill Curiosité and two projects."""
    desk = desk_with(app, migrated_engine)
    with migrated_engine.begin() as connection:
        editor = desk.seeker.editor(connection)
        skills = {skill.label.fr: skill.id for skill in editor.profile().skills}
        curiosity = editor.add_skill(make_skill(label_fr="Curiosité", category="soft"))
        sorting = editor.add_project(
            make_project(name_fr="Tri", skill_ids=[skills["Tableau"]])
        )
        editor.add_project(
            make_project(name_fr="Prévision", stack="Python", skill_ids=[skills["SQL"]])
        )
        editor.save_cv_layout(
            CvLayout(
                groups=(
                    SkillGroup(Text("Langages"), (skills["Tableau"], skills["Python"])),
                ),
                transversal=(curiosity,),
                projects=(sorting,),
            )
        )
    desk.prepare("target_job")
    return desk


def page(desk: Desk, query: str = "") -> str:
    response = desk.client.get(f"/candidatures/{desk.application_id()}{query}")
    assert response.status_code == 200
    return response.text


def in_english(desk: Desk) -> None:
    """The language of the application (decision D6, Q4)."""
    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/langue", data={"langue": "en"}
    )
    assert response.status_code == 303


def chip(html: str, label: str, kind: str = "on") -> str:
    """The chip of ``label`` (decision D6, recette): in the CV (``on``) or suggested (``add``), with its reason."""
    start = html.index(f'class="chip chip-{kind} tip"')
    while f">{label}" not in html[start : html.index("</button>", start)]:
        start = html.index(f'class="chip chip-{kind} tip"', start + 1)
    return html[start : html.index("</button>", start)]


def test_the_page_of_an_application_shows_its_targeted_cv(desk: Desk) -> None:
    html = page(desk)

    assert "1. CV" in html
    # Chips, no arrows (recette of D6): Python is required, it comes before Tableau, welcome only.
    assert html.index('Python<span class="chip-x"') < html.index(
        'Tableau<span class="chip-x"'
    )
    assert "↑" not in html and "↓" not in html
    assert "Citée par l&#39;annonce (éliminatoire)" in chip(html, "Python")
    # Prévision proves SQL: it replaces Tri, which stays one click away, and says why.
    assert 'Prévision<span class="chip-x"' in html
    assert "Remplacé par un projet qui prouve plus de compétences de l&#39;annonce" in (
        chip(html, "+ Tri", "add")
    )
    # SQL is required but outside the master CV: suggested, added in one click to the only group.
    assert 'name="groupe" value="0"' in html
    assert "+ SQL" in html
    assert "Dans ton profil, pas dans le CV" in html
    # The page itself, as an image, is loaded beside the step.
    assert f'hx-get="/candidatures/{desk.application_id()}/cv/apercu"' in html


def test_the_box_of_the_offer_links_to_its_application(desk: Desk) -> None:
    box = desk.client.get(f"/candidatures/offre/{desk.offer_id}", headers=HTMX).text

    assert f'href="/candidatures/{desk.application_id()}"' in box


def test_a_gesture_is_kept_for_the_application_and_journaled(
    desk: Desk, migrated_engine: Engine
) -> None:
    application_id = desk.application_id()
    before = page(desk)
    assert "Revenir à la proposition de Rocky" not in before

    html = desk.client.post(
        f"/candidatures/{application_id}/cv",
        data={
            "geste": "competence-ajouter",
            "element": _skill(desk, "SQL"),
            "groupe": "0",
        },
        headers=HTMX,
    ).text

    assert "Revenir à la proposition de Rocky" in html
    # SQL is cited by the posting: its reason says so, and that the user added it.
    assert "Citée par l&#39;annonce (éliminatoire) : ajoutée par toi" in html
    with migrated_engine.connect() as connection:
        types = (
            connection.execute(
                select(events.c.type).where(
                    events.c.subject_type == "application",
                    events.c.subject_id == str(application_id),
                )
            )
            .scalars()
            .all()
        )
    assert "candidatures.cv_selection_changed" in types

    reset = desk.client.post(
        f"/candidatures/{application_id}/cv/proposition", headers=HTMX
    ).text
    assert "Revenir à la proposition de Rocky" not in reset


def test_the_french_cv_of_the_application_is_a_pdf(desk: Desk) -> None:
    response = desk.client.get(f"/candidatures/{desk.application_id()}/cv.pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_a_name_outside_latin_1_downloads_the_cv_of_the_application(
    desk: Desk, migrated_engine: Engine
) -> None:
    """Step H1: the raw name in ``Content-Disposition`` was a UnicodeEncodeError."""
    with migrated_engine.begin() as connection:
        desk.seeker.editor(connection).save_identity(
            make_identity(full_name="Łukasz Ñandú")
        )

    response = desk.client.get(f"/candidatures/{desk.application_id()}/cv.pdf")

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(
        "filename*=UTF-8''CV_%C5%81ukasz_%C3%91and%C3%BA_FR.pdf"
    )


def test_an_english_cv_still_in_french_is_refused_with_what_is_missing(
    desk: Desk,
) -> None:
    in_english(desk)
    response = desk.client.get(f"/candidatures/{desk.application_id()}/cv.pdf")

    assert response.status_code == 409
    assert "Traduire les champs manquants" in response.text
    assert "Projet « Prévision » : stack" in response.text


def test_checking_the_cv_of_the_application_reads_its_targeted_pdf(
    desk: Desk,
) -> None:
    base = f"/candidatures/{desk.application_id()}/cv/verifier"

    checked = desk.client.post(base, headers=HTMX).text
    in_english(desk)
    refused = desk.client.post(base, headers=HTMX).text

    assert 'class="cv-check"' in checked
    assert "pypdf :" in checked  # each reader says what it read
    assert 'id="dossier-cv"' in checked  # the step is swapped whole
    assert "Traduire les champs manquants" in refused


def test_an_application_goes_from_its_cv_to_sent_on_its_page(
    desk: Desk, migrated_engine: Engine
) -> None:
    base = f"/candidatures/{desk.application_id()}"
    start = page(desk)
    # One step at a time (decision D6, Q2): the page opens on the CV, the others are a click away.
    assert (
        f'<li aria-current="step">\n      <a href="{base}?etape=cv">1. CV</a>' in start
    )
    assert f'href="{base}?etape=lettre">CV prêt : passer à la lettre →</a>' in start
    assert 'id="lettre"' not in start
    assert "Disponible quand ta lettre est prête" in page(desk, "?etape=envoi")

    # No letter for this one (decision D4, Q4, Q16): ready to send, in one gesture.
    ready = desk.client.post(f"{base}/lettre/sans")

    assert (ready.status_code, ready.headers["location"]) == (
        303,
        f"{base}?etape=envoi",
    )
    sending = page(desk)
    assert '<span class="badge badge-accent">Prête à envoyer</span>' in sending
    assert "1. CV ✓" in sending
    assert "2. Lettre ✓" in sending
    assert 'id="envoi"' in sending  # the page opens on the step it is at
    # No application link from the source: the posting itself, its domain shown.
    assert 'href="https://apec.example/offres/d1" target="_blank"' in sending
    assert "apec.example" in sending
    assert "CV prêt : passer à la lettre" not in sending

    # « Envoyée » goes through its confirmation (decision D5, Q5): here, explicitly without document of Rocky.
    moved = desk.client.post(f"{base}/etape", data={"etape": "sent", "retour": "suivi"})
    assert moved.headers["location"] == f"{base}/envoi"
    confirmed = desk.client.post(
        f"{base}/envoi",
        data={
            "date": TODAY.isoformat(),
            "canal": "apec",
            "cv": "aucun",
            "lettre": "aucun",
        },
    )
    assert confirmed.headers["location"] == f"{base}?etape=suivi"
    sent = page(desk)
    assert 'id="suivi"' in sent  # a sent application opens on its follow-up
    assert "Relancer</strong>" in sent
    assert "Envoi confirmé : le 29/09/2026 via Apec" in sent
    assert "Envoyée sans document de Rocky" in page(desk, "?etape=envoi")

    undone = desk.client.post(f"{base}/annuler", data={"retour": "suivi"})
    assert undone.headers["location"] == f"{base}?etape=suivi"
    assert "J'ai envoyé ma candidature</summary>" in page(desk)
    with migrated_engine.connect() as connection:
        types = (
            connection.execute(
                select(events.c.type).where(
                    events.c.subject_type == "application",
                    events.c.subject_id == str(desk.application_id()),
                )
            )
            .scalars()
            .all()
        )
    assert types.count("candidatures.stage_changed") == 2
    assert types.count("candidatures.letter_skipped") == 1


def test_a_gesture_never_returns_to_an_address_it_is_given(desk: Desk) -> None:
    response = desk.client.post(
        f"/candidatures/{desk.application_id()}/etape",
        data={"etape": "ready", "retour": "https://ailleurs.example"},
    )

    assert response.headers["location"] == "/candidatures"


def test_a_cancelled_application_says_so_without_steps(desk: Desk) -> None:
    desk.client.post(
        f"/candidatures/{desk.application_id()}/annuler", data={"retour": "dossier"}
    )

    html = page(desk)
    assert "Candidature annulée" in html
    assert 'class="steps' not in html


def test_the_application_of_another_account_is_not_found(
    app: FastAPI, migrated_engine: Engine, desk: Desk
) -> None:
    other = desk_with(app, migrated_engine)

    assert other.client.get(f"/candidatures/{desk.application_id()}").status_code == 404
    assert (
        other.client.post(
            f"/candidatures/{desk.application_id()}/cv",
            data={"geste": "projet-basculer", "element": "1"},
        ).status_code
        == 404
    )


def test_a_kept_selection_survives_the_removal_of_its_skill_and_project(
    desk: Desk, migrated_engine: Engine
) -> None:
    """Step H1: a kept selection naming a removed skill or project was a KeyError at the page, preview and PDF."""
    base = f"/candidatures/{desk.application_id()}"
    kept = desk.client.post(
        f"{base}/cv",
        data={
            "geste": "competence-ajouter",
            "element": _skill(desk, "SQL"),
            "groupe": "0",
        },
        headers=HTMX,
    )
    assert "Revenir à la proposition de Rocky" in kept.text
    with migrated_engine.begin() as connection:
        editor = desk.seeker.editor(connection)
        profile = editor.profile()
        python = next(s.id for s in profile.skills if s.label.fr == "Python")
        forecast = next(
            p.id for p in profile.projects if p.content.name.fr == "Prévision"
        )
        assert editor.delete_skill(python)
        assert editor.delete_project(forecast)

    html = page(desk)
    assert 'Python<span class="chip-x"' not in html
    assert 'SQL<span class="chip-x"' in html
    assert desk.client.get(f"{base}/cv/apercu", headers=HTMX).status_code == 200
    assert desk.client.get(f"{base}/cv.pdf").status_code == 200


def _skill(desk: Desk, label: str) -> str:
    with desk.engine.connect() as connection:
        skills = desk.seeker.profile(connection).skills
    return str(next(skill.id for skill in skills if skill.label.fr == label))


def test_the_cv_of_the_application_is_previewed_as_an_image(desk: Desk) -> None:
    """Decision D6, recette: the CV seen at a glance beside the step, not a PDF opened in a page."""
    base = f"/candidatures/{desk.application_id()}"

    preview = desk.client.get(f"{base}/cv/apercu", headers=HTMX).text

    assert '<img src="data:image/png;base64,' in preview
    assert "Le CV tient sur une page." in preview
    assert f'href="{base}/cv.pdf?apercu=1"' in preview
    in_english(desk)
    refused = desk.client.get(f"{base}/cv/apercu", headers=HTMX).text
    assert "<img" not in refused
    assert "Projet « Prévision » : stack" in refused


def test_the_cv_preview_says_what_the_neutral_template_cut(
    desk: Desk, migrated_engine: Engine
) -> None:
    """Step G5, Q1: a project text beyond its limit is cut to hold one page, and the preview says so."""
    base = f"/candidatures/{desk.application_id()}"
    with migrated_engine.begin() as connection:
        editor = desk.seeker.editor(connection)
        forecast = next(
            p for p in editor.profile().projects if p.content.name.fr == "Prévision"
        )
        long = Text("Prévoir la demande des entrepôts régionaux chaque semaine. " * 4)
        assert editor.update_project(
            forecast.id, replace(forecast.content, problem=long)
        )

    preview = desk.client.get(f"{base}/cv/apercu", headers=HTMX).text

    assert '<img src="data:image/png;base64,' in preview
    assert "le gabarit neutre a coupé 1 texte" in preview
    assert "Projet « Prévision », problème : coupé à 140 caractères." in preview


def test_the_cv_preview_links_each_project_to_shorten_with_the_way_back(
    desk: Desk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recette of G5: « Ouvrir le PDF » only opened the PDF; a spilling project now leads to its form in the profile,
    which offers the way back to this step."""
    application_id = desk.application_id()
    drawn = profil_web.cv_drawing

    def spilling(*args: Any) -> profil_web.CvDrawing:
        return replace(drawn(*args), projects_to_shorten=((42, "Prévision"),))

    monkeypatch.setattr(dossier_web, "cv_drawing", spilling)

    preview = desk.client.get(
        f"/candidatures/{application_id}/cv/apercu", headers=HTMX
    ).text

    back = f"%2Fcandidatures%2F{application_id}%3Fetape%3Dcv"
    assert (
        f'href="/profil/projets?modifier=42&amp;retour={back}#section-projets">'
        "Raccourcir « Prévision » dans mon profil →</a>"
    ) in preview


def test_the_employer_domain_is_typed_in_the_follow_up(desk: Desk) -> None:
    """Decision E2, Q3: « E-mails de l'employeur » in the step « Suivi »; a wrong domain says how to write it."""
    base = f"/candidatures/{desk.application_id()}"

    saved = desk.client.post(
        f"{base}/domaine", data={"domaine": "rh@exemple.fr", "retour": "suivi"}
    )
    refused = desk.client.post(
        f"{base}/domaine", data={"domaine": "exemple", "retour": "suivi"}
    )

    assert saved.status_code == 303
    assert "E-mails de l'employeur : exemple.fr" in page(desk, "?etape=suivi")
    assert "Domaine invalide" in refused.text
    assert (
        desk.client.post(
            "/candidatures/999999/domaine", data={"domaine": "x.fr"}
        ).status_code
        == 404
    )
