"""The step « Lettre » and the accompanying message of an application, through HTTP (decision D4)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import timedelta
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
from tests.offres.fakes import TODAY
from tests.system.web_support import HTMX, make_app

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
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.import_today = lambda: TODAY
    app.state.llm_model = LetterModel()
    return app


@pytest.fixture
def desk(app: FastAPI, migrated_engine: Engine) -> Desk:
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


def base(desk: Desk) -> str:
    return f"/candidatures/{desk.application_id()}"


def page(desk: Desk, query: str = "") -> str:
    response = desk.client.get(base(desk) + query)
    assert response.status_code == 200
    return response.text


def adapted(desk: Desk) -> str:
    response = desk.client.post(
        f"{base(desk)}/lettre/adapter",
        data={"langue": "fr", "consentement": "1"},
        headers=HTMX,
    )
    assert response.status_code == 200
    return response.text


def form_of(html: str) -> dict[str, str]:
    """The fields of the letter form as the page fills them (radios: the checked one)."""
    form = html[
        html.index('action="/candidatures/') : html.index("Valider cette lettre")
    ]
    fields = dict(
        re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', form)
    )
    fields.update(re.findall(r'name="(objet)" value="([^"]*)"', form))
    fields.update(re.findall(r'<textarea name="(\w+)"[^>]*>([^<]*)</textarea>', form))
    fields.update(
        re.findall(r'<input type="radio" name="(\w+)" value="(\w+)" checked>', form)
    )
    return {key: value.replace("&#39;", "'") for key, value in fields.items()}


def test_the_letter_starts_from_the_generic_one_for_this_offer(desk: Desk) -> None:
    html = page(desk)

    assert "2. Lettre" in html
    assert (
        "Je souhaite rejoindre Exemple comme Data analyst." in html
    )  # « (H/F) » gone (Q18)
    assert 'value="Candidature au poste de Data analyst"' in html
    assert "Adapter à l'annonce" in html
    english = page(desk, "?lettre=en")
    assert "Prépare d&#39;abord ta lettre anglaise dans Profil &amp; kit." in english


def test_adapting_asks_consent_and_sends_neither_name_nor_contact(
    desk: Desk, app: FastAPI
) -> None:
    refused = desk.client.post(
        f"{base(desk)}/lettre/adapter", data={"langue": "fr"}, headers=HTMX
    ).text
    assert "Coche l&#39;accord d&#39;envoi" in refused
    assert app.state.llm_model.prompts == []

    html = adapted(desk)

    (prompt,) = app.state.llm_model.prompts
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
    # Ta lettre by default (Q14), the « pourquoi vous » written for the offer, the opening adapted.
    assert (fields["choix_0"], fields["choix_1"], fields["choix_2"]) == (
        "original",
        "original",
        "adapte",
    )
    fields["choix_0"] = "adapte"

    response = desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    assert response.headers["location"] == f"{base(desk)}#lettre"
    html = page(desk)
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


def test_writing_in_my_version_chooses_it(desk: Desk) -> None:
    fields = form_of(page(desk))
    fields["mien_1"] = "J'ai mené des projets de bout en bout pendant huit ans."

    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    assert "ta version" in page(desk)


def test_a_ready_letter_leads_to_sending_with_its_pdf(desk: Desk) -> None:
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk)))

    ready = desk.client.post(f"{base(desk)}/lettre/prete")

    assert ready.headers["location"] == f"{base(desk)}#envoi"
    html = page(desk)
    assert "<strong>Prête à envoyer</strong>" in html
    assert f'href="{base(desk)}/lettre.pdf?langue=fr"' in html
    pdf = desk.client.get(f"{base(desk)}/lettre.pdf?langue=fr")
    assert pdf.headers["content-type"] == "application/pdf"
    assert (
        'filename="Lettre_Camille_Martin_FR.pdf"' in pdf.headers["content-disposition"]
    )
    checked = desk.client.post(
        f"{base(desk)}/lettre/verifier", data={"langue": "fr"}, headers=HTMX
    ).text
    assert "attendus de cette lettre" in checked


def test_a_letter_ready_needs_a_letter(desk: Desk) -> None:
    html = desk.client.post(f"{base(desk)}/lettre/prete", headers=HTMX).text

    assert "Valide d&#39;abord une lettre" in html
    assert desk.client.get(f"{base(desk)}/lettre.pdf").status_code == 409


def test_the_message_is_proposed_on_gesture_then_validated(
    desk: Desk, app: FastAPI
) -> None:
    refused = desk.client.post(
        f"{base(desk)}/message/proposer", data={"langue": "fr"}, headers=HTMX
    ).text
    assert (
        "Coche l&#39;accord d&#39;envoi pour que Rocky propose un message." in refused
    )

    proposed = desk.client.post(
        f"{base(desk)}/message/proposer",
        data={"langue": "fr", "consentement": "1"},
        headers=HTMX,
    ).text
    assert 'id="envoi"' in proposed
    assert "Valider ce message" in proposed
    assert "Formule convenue : « je serais ravi" not in proposed

    response = desk.client.post(
        f"{base(desk)}/message/valider",
        data={"langue": "fr", "texte": MESSAGE, "propose": MESSAGE},
    )

    assert response.headers["location"] == f"{base(desk)}#envoi"
    assert "Validé le" in page(desk)


def test_a_letter_changed_after_sending_says_which_one_was_sent(
    desk: Desk, app: FastAPI
) -> None:
    desk.client.post(f"{base(desk)}/lettre/valider", data=form_of(page(desk)))
    desk.client.post(f"{base(desk)}/lettre/prete")
    desk.client.post(f"{base(desk)}/etape", data={"etape": "sent", "retour": "dossier"})
    app.state.auth.clock.advance(timedelta(hours=1))

    fields = form_of(page(desk, "?modifier=1"))
    fields["mien_1"] = "J'ai conduit des projets pendant huit ans."
    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    html = page(desk)
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
    fields["choix_0"] = "adapte"

    html = desk.client.post(
        f"{base(desk)}/lettre/apercu", data=fields, headers=HTMX
    ).text

    assert '<img src="data:image/png;base64,' in html
    assert "elle tient sur une page" in html
    # The form comes back as it was left: Gemini's opening chosen, its proposals still there.
    assert form_of(html)["choix_0"] == "adapte"
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
    fields = form_of(page(desk))
    fields["mien_1"] = " ".join(["J'ai piloté des projets pendant huit ans."] * 140)
    desk.client.post(f"{base(desk)}/lettre/valider", data=fields)

    refused = desk.client.get(f"{base(desk)}/lettre.pdf")

    assert refused.status_code == 409
    assert "La lettre dépasse sa page" in refused.text
    assert '<img src="data:image/png;base64,' in refused.text
