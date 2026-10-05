"""The page 📈 Bilan (decision F1, Q9, Q10, Q14): one main action, whether something was sent or not."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from tests.candidatures.test_web import desk_with
from tests.offres.fakes import TODAY
from tests.system.web_support import HTMX, logged_in, make_app


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.import_today = lambda: TODAY
    return app


def test_before_any_sending_the_report_says_so(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    page = client.get("/bilan").text

    assert "Aucune candidature envoyée pour l'instant" in page
    assert page.count("btn-primary") == 1
    assert 'class="btn btn-primary card-action" href="/candidatures"' in page


def test_the_report_shows_each_figure_with_its_denominator(
    app: FastAPI, migrated_engine: Engine
) -> None:
    desk = desk_with(app, migrated_engine)
    desk.prepare("target_job")
    desk.post("etape", etape="in_discussion")

    page = desk.client.get("/bilan").text

    assert "1 candidature envoyée depuis le" in page
    assert (
        "<dt>Réponse d&#39;une personne</dt><dd><strong>1</strong> sur 1" in page
        or ("<dt>Réponse d'une personne</dt><dd><strong>1</strong> sur 1" in page)
    )
    assert "<dt>Accusé de réception seul</dt><dd><strong>0</strong> sur 1" in page
    assert page.count("btn-primary") == 1
    assert (
        'href="/candidatures?vue=suivi">Voir les candidatures en attente de réponse'
        in page
    )


def test_the_drawer_of_the_report_gives_its_main_action(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    drawer = client.get("/tiroir?ecran=report", headers=HTMX).text

    assert 'href="/candidatures">Voir les candidatures</a>' in drawer
