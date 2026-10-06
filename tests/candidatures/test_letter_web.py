"""The step « Lettre » and the accompanying message of an application, through HTTP (decision D4)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select

from rocky.profil.letter import make_letter
from rocky.profil.model import LetterOrigin
from rocky.profil.rules import make_identity
from rocky.system.events import events
from tests.candidatures.test_dossier_web import dossier_with
from tests.candidatures.test_web import Desk, desk_with
from tests.offres.fakes import NOW
from tests.system.web_support import HTMX, make_app, use_model, used_model

WHY_YOU = (
    "Exemple analyse les ventes de ses magasins avec Python et SQL : c'est le travail que je veux faire, "
    "dans une équipe qui décide avec ses données. Mon projet Prévision m'a appris à relier une question "
    "métier à un modèle simple et lisible."
)
ADAPTED_OPENING = (
    "Je souhaite rejoindre Exemple comme Data analyst, pour ses données de vente."
)
MESSAGE = (
    "Bonjour, je postule au poste de Data analyst chez Exemple. Mon projet Prévision m'a appris à "
    "relier une question métier à SQL et Python, ce que demande votre annonce. Je serais heureux "
    "d'en parler avec vous."
)


class LetterModel:
    """Adapts the letter or proposes the message, by the schema asked; keeps what it was sent."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.prompts.append(prompt)
        if "message" in schema["properties"]:
            return {"message": MESSAGE}
        return {
            "why_you": WHY_YOU,
            "paragraphs": [
                {"id": "p0", "text": ADAPTED_OPENING},
                {
                    "id": "p1",
                    "text": "Passionné, j'ai piloté des projets pendant huit ans.",
                },
            ],
        }


@pytest.fixture
def app(migrated_engine: Engine, tmp_path: Path) -> FastAPI:
    app = make_app(migrated_engine, storage_root=tmp_path)
    app.state.auth.clock.now = NOW
    use_model(app, LetterModel())
    return app


@pytest.fixture
def desk(app: FastAPI, migrated_engine: Engine) -> Desk:
    return letter_desk(app, migrated_engine)


def letter_desk(app: FastAPI, migrated_engine: Engine) -> Desk:
    """The application of ``test_dossier_web`` (an offer « Data analyst (H/F) » at Exemple), and a French generic
    letter with its empty place « pourquoi vous »."""
    desk = dossier_with(app, migrated_engine)
    with migrated_engine.begin() as connection:
        editor = desk.seeker.editor(connection)
        editor.save_identity(
            make_identity(
                full_name="Camille Martin",
                city="Chartres",
                contact_email=desk.seeker.email,
            )
        )
        editor.save_generic_letter(
            make_letter(
                "fr",
                [
                    ("opening", "Je souhaite rejoindre {entreprise} comme {poste}."),
                    ("journey", "J'ai piloté des projets pendant huit ans."),
                    ("closing", "Je serais heureux d'en parler avec vous."),
                ],
            ),
            LetterOrigin.IMPORT,
        )
    return desk


LETTER = "?etape=lettre"


def base(desk: Desk) -> str:
    return f"/candidatures/{desk.application_id()}"


def page(desk: Desk, query: str = "") -> str:
    response = desk.client.get(base(desk) + query)
    assert response.status_code == 200
    return response.text


def adapted(desk: Desk) -> str:
    response = desk.client.post(
        f"{base(desk)}/lettre/adapter",
        data={"consentement": "1"},
        headers=HTMX,
    )
    assert response.status_code == 200
    return response.text


def form_of(html: str) -> dict[str, str]:
    """The fields of the letter form as the page fills them: one text per paragraph (decision D6, Q3)."""
    start = html.index('class="stack letter-editor"')
    form = html[start : html.index("</form>", start)]
    fields = dict(
        re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', form)
    )
    fields.update(re.findall(r'name="(objet)" value="([^"]*)"', form))
    fields.update(re.findall(r'<textarea name="(\w+)"[^>]*>([^<]*)</textarea>', form))
    return {key: value.replace("&#39;", "'") for key, value in fields.items()}


def sent_form(html: str) -> dict[str, str]:
    """The fields of the form « J'ai envoyé ma candidature » as the page fills them (decision D5)."""
    form = html[html.index('id="confirmer"') : html.index("Confirmer l'envoi</button>")]
    fields = {
        "date": re.findall(r'name="date" value="([^"]+)"', form)[0],
        "canal": re.findall(r'<option value="(\w+)" selected>', form)[0],
    }
    for name in ("cv", "lettre"):
        checked = re.findall(
            rf'name="{name}" value="(\w+)" (?:required )?checked', form
        )
        if checked:
            fields[name] = checked[0]
    if re.search(r'name="message" value="1" checked', form):
        fields["message"] = "1"
    return fields


def test_the_letter_starts_from_the_generic_one_for_this_offer(desk: Desk) -> None:
    html = page(desk, LETTER)

    assert "2. Lettre" in html
    assert (
        "Je souhaite rejoindre Exemple comme Data analyst." in html
    )  # « (H/F) » gone (Q18)
    assert 'value="Candidature au poste de Data analyst"' in html
    assert "Adapter à l'annonce" in html
    desk.client.post(f"{base(desk)}/langue", data={"langue": "en"})
    english = page(desk, LETTER)
    assert "Prépare d&#39;abord ta lettre anglaise dans Profil &amp; kit." in english


def test_adapting_asks_consent_and_sends_neither_name_nor_contact(
    desk: Desk, app: FastAPI
) -> None:
    refused = desk.client.post(f"{base(desk)}/lettre/adapter", headers=HTMX).text
    assert "Coche l&#39;accord d&#39;envoi" in refused
    assert used_model(app).prompts == []

    html = adapted(desk)

    (prompt,) = used_model(app).prompts
    assert "Exemple" in prompt and "Data analyst" in prompt
    assert "Camille" not in prompt and desk.seeker.email not in prompt
    assert 'id="lettre"' in html  # the step is swapped whole
    assert ADAPTED_OPENING in html
    assert "Formule convenue : « passionné »." in html  # flagged, not blocked (Q8)
    assert WHY_YOU.replace("'", "&#39;") in html


def test_the_letter_validated_paragraph_by_paragraph_is_kept_with_its_origins(
    desk: Desk, migrated_engine: Engine
) -> None:
    fields = form_of(adapted(desk))
    # One text per paragraph (D6, Q3): the user's own by default (D4, Q14), the « pourquoi vous » written for the
    # offer, Gemini's opening beside it.
    assert fields["texte_0"] == "Je souhaite rejoindre Exemple comme Data analyst."
    assert fields["texte_1"] == "J'ai piloté des projets pendant huit ans."
    assert fields["texte_2"] == WHY_YOU
    assert fields["adapte_0"] == ADAPTED_OPENING
    fields["texte_0"] = fields["adapte_0"]

    response = desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    assert response.headers["location"] == f"{base(desk)}{LETTER}"
    html = page(desk, LETTER)
    assert "2. Lettre ✓" in html
    assert "Lettre validée le" in html
    assert (
        f'{ADAPTED_OPENING} <span class="badge badge-muted">version de Gemini</span>'
        in html
    )
    assert "Lettre prête : passer à l'envoi" in html
    with migrated_engine.connect() as connection:
        payload = connection.execute(
            select(events.c.payload).where(
                events.c.type == "candidatures.letter_validated",
                events.c.subject_id == str(desk.application_id()),
            )
        ).scalar_one()
    assert payload["origins"] == ["adapted", "generic", "adapted", "generic"]


def switch(desk: Desk, fields: dict[str, str], value: str) -> dict[str, str]:
    html = desk.client.post(
        f"{base(desk)}/lettre/basculer",
        data={**fields, "basculer": value},
        headers=HTMX,
    ).text
    assert 'id="lettre"' in html
    return form_of(html)


def test_the_switch_puts_a_version_in_the_text_and_keeps_what_was_written(
    desk: Desk, migrated_engine: Engine
) -> None:
    fields = form_of(adapted(desk))

    gemini = switch(desk, fields, "0:adapte")
    assert gemini["texte_0"] == ADAPTED_OPENING
    assert gemini["texte_1"] == fields["texte_1"]  # the other paragraphs as they were

    gemini["texte_0"] = "Je veux rejoindre Exemple pour ses données de vente."
    mine = switch(desk, gemini, "0:original")
    assert mine["texte_0"] == "Je souhaite rejoindre Exemple comme Data analyst."
    assert mine["mien_0"] == "Je veux rejoindre Exemple pour ses données de vente."
    assert switch(desk, mine, "0:mien")["texte_0"] == mine["mien_0"]
    with migrated_engine.connect() as connection:
        validated = connection.execute(
            select(events.c.id).where(
                events.c.type == "candidatures.letter_validated",
                events.c.subject_id == str(desk.application_id()),
            )
        ).all()
    assert validated == []  # nothing is kept before « Valider »


def test_writing_over_a_paragraph_makes_it_mine(desk: Desk) -> None:
    fields = form_of(page(desk, LETTER))
    fields["texte_1"] = "J'ai mené des projets de bout en bout pendant huit ans."

    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    assert "ta version" in page(desk, LETTER)


def test_a_ready_letter_leads_to_sending_with_its_pdf(desk: Desk) -> None:
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk, LETTER)))

    ready = desk.client.post(f"{base(desk)}/lettre/prete")

    assert ready.headers["location"] == f"{base(desk)}?etape=envoi"
    html = page(desk)
    assert '<span class="badge badge-accent">Prête à envoyer</span>' in html
    assert "Générer les PDF à envoyer" in html
    # A draft in the step « Lettre »; the PDFs sent are generated in the step « Envoi » (decision D5, Q2).
    assert f'href="{base(desk)}/lettre.pdf?apercu=1"' in page(desk, LETTER)
    pdf = desk.client.get(f"{base(desk)}/lettre.pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    assert (
        'filename="Lettre_Camille_Martin_FR.pdf"' in pdf.headers["content-disposition"]
    )
    checked = desk.client.post(f"{base(desk)}/lettre/verifier", headers=HTMX).text
    assert "attendus de cette lettre" in checked


def test_a_name_outside_latin_1_downloads_its_letter(
    desk: Desk, migrated_engine: Engine
) -> None:
    """Step H1: the raw name in ``Content-Disposition`` was a UnicodeEncodeError."""
    with migrated_engine.begin() as connection:
        desk.seeker.editor(connection).save_identity(
            make_identity(
                full_name="Łukasz Ñandú",
                city="Chartres",
                contact_email=desk.seeker.email,
            )
        )
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk, LETTER)))

    pdf = desk.client.get(f"{base(desk)}/lettre.pdf")

    assert pdf.status_code == 200
    assert pdf.headers["content-disposition"].endswith(
        "filename*=UTF-8''Lettre_%C5%81ukasz_%C3%91and%C3%BA_FR.pdf"
    )


def test_a_letter_ready_needs_a_letter(desk: Desk) -> None:
    html = desk.client.post(f"{base(desk)}/lettre/prete", headers=HTMX).text

    assert "Valide d&#39;abord une lettre" in html
    assert desk.client.get(f"{base(desk)}/lettre.pdf").status_code == 409


def test_the_message_is_proposed_on_gesture_then_validated(
    desk: Desk, app: FastAPI
) -> None:
    refused = desk.client.post(f"{base(desk)}/message/proposer", headers=HTMX).text
    assert (
        "Coche l&#39;accord d&#39;envoi pour que Rocky propose un message." in refused
    )

    proposed = desk.client.post(
        f"{base(desk)}/message/proposer",
        data={"consentement": "1"},
        headers=HTMX,
    ).text
    assert 'id="envoi"' in proposed
    assert "Valider ce message" in proposed
    assert "Formule convenue : « je serais ravi" not in proposed

    response = desk.client.post(
        f"{base(desk)}/message/valider",
        data={"texte": MESSAGE, "propose": MESSAGE},
    )

    assert response.headers["location"] == f"{base(desk)}?etape=envoi"
    assert "· validé le" in page(desk, "?etape=envoi")


def test_a_letter_changed_after_sending_says_which_one_was_sent(
    desk: Desk, app: FastAPI
) -> None:
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk, LETTER)))
    desk.client.post(f"{base(desk)}/lettre/prete")
    # Sent with the revisions generated (decision D5): the letter sent is the one of its revision.
    desk.client.post(f"{base(desk)}/documents")
    sent_with = sent_form(page(desk, "/envoi"))
    assert sent_with["lettre"] != "aucun"
    desk.client.post(f"{base(desk)}/envoi", data=sent_with)
    app.state.auth.clock.advance(timedelta(hours=1))

    fields = form_of(page(desk, f"{LETTER}&modifier=1"))
    fields["texte_1"] = "J'ai conduit des projets pendant huit ans."
    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    html = page(desk, LETTER)
    assert "Envoyée avec la version du" in html
    assert "la lettre a été modifiée depuis" in html


def test_the_letter_of_another_account_is_not_found(
    app: FastAPI, migrated_engine: Engine, desk: Desk
) -> None:
    other = desk_with(app, migrated_engine)

    assert other.client.post(f"{base(desk)}/lettre/sans").status_code == 404
    assert other.client.get(f"{base(desk)}/lettre.pdf").status_code == 404
    assert other.client.post(f"{base(desk)}/lettre/valider", data={}).status_code == 404


def test_the_preview_shows_the_letter_as_composed_without_keeping_it(
    desk: Desk, migrated_engine: Engine
) -> None:
    fields = form_of(adapted(desk))
    fields["texte_0"] = ADAPTED_OPENING

    html = desk.client.post(
        f"{base(desk)}/lettre/apercu", data=fields, headers=HTMX
    ).text

    assert '<img src="data:image/png;base64,' in html
    assert "La lettre tient sur une page." in html
    # The form comes back as it was left: Gemini's opening chosen, its proposals still there.
    assert form_of(html)["texte_0"] == ADAPTED_OPENING
    assert form_of(html)["adapte_0"] == ADAPTED_OPENING
    with migrated_engine.connect() as connection:
        validated = connection.execute(
            select(events.c.id).where(
                events.c.type == "candidatures.letter_validated",
                events.c.subject_id == str(desk.application_id()),
            )
        ).all()
    assert validated == []


def test_a_letter_too_long_is_refused_with_its_preview(desk: Desk) -> None:
    fields = form_of(page(desk, LETTER))
    fields["texte_1"] = " ".join(["J'ai piloté des projets pendant huit ans."] * 140)
    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    refused = desk.client.get(f"{base(desk)}/lettre.pdf")

    assert refused.status_code == 409
    assert "La lettre dépasse sa page" in refused.text
    assert '<img src="data:image/png;base64,' in refused.text


def test_the_letter_validated_is_previewed_beside_its_step(desk: Desk) -> None:
    """Decision D6, recette: the letter in force as an image, loaded beside the step."""
    assert (
        "Valide d&#39;abord cette lettre."
        in desk.client.get(f"{base(desk)}/lettre/apercu", headers=HTMX).text
    )
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk, LETTER)))

    step = page(desk, LETTER)
    preview = desk.client.get(f"{base(desk)}/lettre/apercu", headers=HTMX).text

    assert f'hx-get="{base(desk)}/lettre/apercu"' in step
    assert '<img src="data:image/png;base64,' in preview
    assert "La lettre tient sur une page." in preview
