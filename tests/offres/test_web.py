"""The offers screen through HTTP, as HTMX drives it (``HX-Request``) and without JavaScript."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine

from rocky.offres.prototype import Offer, load_catalog
from tests.system.web_support import HTMX, logged_in, make_app


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    return make_app(migrated_engine)


@pytest.fixture
def client(app: FastAPI, migrated_engine: Engine) -> TestClient:
    return logged_in(app, migrated_engine)[0]


def queue() -> list[Offer]:
    return load_catalog().queue(decided=set())


def title(offer: Offer) -> str:
    return str(escape(offer.title))


def decide(
    client: TestClient,
    offer: Offer,
    decision: str = "rejected",
    reasons: tuple[str, ...] = ("too_senior",),
    note: str = "",
    context: str = "tri",
) -> str:
    response = client.post(
        f"/offres/{offer.id}/decision",
        data={
            "decision": decision,
            "motifs": list(reasons),
            "precision": note,
            "contexte": context,
        },
        headers=HTMX,
    )
    assert response.status_code == 200
    return response.text


def rows(html: str) -> int:
    return html.count('<td><span class="score')


def to_review(html: str) -> int:
    match = re.search(r"<strong>(\d+)</strong> à examiner", html)
    assert match is not None
    return int(match.group(1))


def test_offers_open_on_triage_with_the_best_offer(client: TestClient) -> None:
    page = client.get("/offres")

    assert page.status_code == 200
    assert 'aria-current="page">Trier' in page.text
    assert title(queue()[0]) in page.text
    below = sum(load_catalog().below_threshold(o) for o in load_catalog().offers)
    assert to_review(page.text) == len(queue())
    assert f"{below} sous le seuil →" in page.text


def test_a_decision_needs_a_reason(client: TestClient) -> None:
    offer = queue()[0]

    response = client.post(
        f"/offres/{offer.id}/decision",
        data={"decision": "rejected", "contexte": "tri"},
        headers=HTMX,
    )

    assert "Choisis au moins un motif." in response.text
    assert response.headers["HX-Retarget"] == "#decision-area"
    assert title(offer) in client.get("/offres").text  # nothing recorded


def test_other_needs_a_note(client: TestClient) -> None:
    offer = queue()[0]

    html = decide(client, offer, "interested", ("other",))

    assert "Précise le motif « autre »." in html


def test_the_reasons_panel_lists_the_reasons_of_the_decision(
    client: TestClient,
) -> None:
    offer = queue()[0]

    panel = client.get(
        f"/offres/{offer.id}/motifs?decision=rejected&contexte=tri", headers=HTMX
    ).text

    assert "Pourquoi écartée ?" in panel
    assert 'value="too_senior"' in panel
    assert 'data-key="9"' in panel
    assert 'value="growth"' not in panel


def test_a_decision_shows_the_next_offer_and_updates_the_counts(
    client: TestClient,
) -> None:
    first, second = queue()[0], queue()[1]

    html = decide(client, first, "rejected", ("too_senior", "location"))

    assert html.startswith('<section id="triage"')
    assert title(second) in html
    assert 'hx-swap-oob="true"' in html
    assert to_review(html) == len(queue()) - 1


def test_without_javascript_a_decision_redirects(client: TestClient) -> None:
    offer = queue()[0]

    response = client.post(
        f"/offres/{offer.id}/decision",
        data={"decision": "later", "motifs": ["reread"], "contexte": "tri"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/offres"


def test_undo_goes_back_several_decisions(client: TestClient) -> None:
    offers = queue()[:3]
    for offer in offers:
        decide(client, offer)

    for offer in reversed(offers):
        html = client.post("/offres/annuler", headers=HTMX).text
        assert title(offer) in html.split('class="card offer-card"')[1]
    assert to_review(html) == len(queue())
    assert re.search(r'data-key="u"[^>]*disabled', html)


def test_j_and_k_move_between_offers_without_deciding(client: TestClient) -> None:
    first, second, third = queue()[:3]

    html = client.get(f"/offres/tri/{second.id}", headers=HTMX).text

    assert f'hx-get="/offres/tri/{first.id}"' in html
    assert f'hx-get="/offres/tri/{third.id}"' in html
    assert to_review(client.get("/offres").text) == len(queue())


def test_why_explains_each_component(client: TestClient) -> None:
    offer = queue()[0]

    html = client.get(f"/offres/{offer.id}/pourquoi", headers=HTMX).text

    assert "Score provisoire" in html
    for component in offer.components:
        assert str(escape(component.label)) in html


def test_list_filters(client: TestClient) -> None:
    catalog = load_catalog()
    below = [o for o in catalog.offers if catalog.below_threshold(o)]
    analyst = [o for o in queue() if "data_analyst" in o.tracks]

    below_rows = client.get("/offres/liste?sous_seuil=1", headers=HTMX).text
    analyst_rows = client.get("/offres/liste?piste=data_analyst", headers=HTMX).text

    assert rows(below_rows) == len(below)
    assert rows(analyst_rows) == len(analyst)


def test_the_list_follows_decisions(client: TestClient) -> None:
    offer = queue()[0]
    decide(client, offer, "rejected", ("contract",))

    rejected = client.get("/offres/liste?decision=ecarte", headers=HTMX).text
    to_examine = client.get("/offres/liste", headers=HTMX).text

    assert title(offer) in rejected
    assert title(offer) not in to_examine


def test_a_list_url_without_htmx_opens_the_whole_page(client: TestClient) -> None:
    response = client.get("/offres/liste?piste=ai_ml&sous_seuil=1")

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "/offres?vue=liste&piste=ai_ml&decision=a_examiner&sous_seuil=1"
    )


def test_the_sheet_decides_and_refreshes_the_list(client: TestClient) -> None:
    offer = queue()[4]
    sheet = client.get(f"/offres/{offer.id}/fiche", headers=HTMX).text
    assert title(offer) in sheet
    assert "contexte=fiche" in sheet

    client.post(
        f"/offres/{offer.id}/decision",
        data={
            "decision": "interested",
            "motifs": ["skills_match"],
            "contexte": "fiche",
        },
        headers=HTMX,
    )
    response = client.post(
        f"/offres/{offer.id}/decision",
        data={"decision": "rejected", "motifs": ["salary"], "contexte": "fiche"},
        headers=HTMX,
    )

    assert response.headers["HX-Trigger"] == "offers-changed"
    assert "Décision : <strong>Écarté</strong>" in response.text
    assert "salaire" in response.text


def test_a_sheet_url_without_htmx_opens_the_list_with_the_sheet(
    client: TestClient,
) -> None:
    offer = load_catalog().offers[-1]

    page = client.get(f"/offres/{offer.id}/fiche").text

    assert 'aria-current="page">Liste' in page
    assert title(offer) in page.split('id="fiche"')[1]


def test_when_everything_is_sorted_the_list_opens(client: TestClient) -> None:
    for offer in queue():
        last = decide(client, offer, "later", ("reread",))

    page = client.get("/offres").text

    assert "Tout est trié" in last
    assert to_review(last) == 0
    assert 'aria-current="page">Liste' in page


def test_reset_forgets_the_decisions(client: TestClient) -> None:
    decide(client, queue()[0])

    response = client.post("/offres/reinitialiser")

    assert response.status_code == 303
    assert to_review(client.get("/offres").text) == len(queue())


def test_decisions_belong_to_their_account(
    app: FastAPI, migrated_engine: Engine, client: TestClient
) -> None:
    other, _ = logged_in(app, migrated_engine)
    decide(client, queue()[0])

    assert to_review(other.get("/offres").text) == len(queue())


def test_unknown_offers_are_not_found(client: TestClient) -> None:
    assert client.get("/offres/999999/pourquoi", headers=HTMX).status_code == 404
    assert client.get("/offres/999999/fiche", headers=HTMX).status_code == 404
