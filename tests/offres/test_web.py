"""The offers screen through HTTP, on stored offers, as HTMX drives it (``HX-Request``) and without JavaScript."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine, select

from rocky.offres.imports.rules import BROWSER_REFUSED_REASON, OTHER_PAGE_REASON
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sql import SqlStorage, SqlStore, job_decisions, job_offers
from rocky.offres.usecases import record_offer
from rocky.offres.watch.model import RunCounts, RunStatus, Trigger
from rocky.offres.web import READ_NOTE
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.events import events
from rocky.system.llm import LlmUnavailableError
from rocky.system.llm.calls import model_calls
from rocky.system.workstation import NOT_RUNNING, ShownPage
from tests.offres.fakes import (
    HALF_PAST_MIDNIGHT,
    NOW,
    SUMMARY,
    TODAY,
    FakeBrowser,
    FakeModel,
    Seeker,
    equip,
    posting,
)
from tests.system.web_support import HTMX, logged_in, make_app, use_model, used_model

# Current scores (best track): four offers at 75, an incomplete one at 53, two under the threshold.
POSTINGS = {
    "analyst": (posting("analyst", contract="CDI"), ("Data",)),
    "python": (posting("python", title="Data analyst Python"), ("Data",)),
    "scientist": (posting("scientist", title="Data scientist"), ("IA",)),
    "junior": (
        posting(
            "junior", source="wttj", title="Data analyst junior", company="Jems Group"
        ),
        ("Data",),
    ),
    "excerpt": (posting("excerpt", complete=False), ("Data",)),
    "accounting": (
        posting(
            "accounting",
            title="Comptable",
            description="Tenue de la comptabilité générale. Excel.",
        ),
        ("Data",),
    ),
    # On LinkedIn: the lecture assistée is offered (an Apec offer is completed by hand, decision E5, Q8).
    "manager": (
        posting("manager", source="linkedin", title="Chef de projet", complete=False),
        ("Data",),
    ),
    # The same posting as « junior » on another site (« vue aussi sur … »).
    "junior_apec": (
        posting("junior_apec", title="Data analyst junior (H/F)", company="JEMS"),
        ("Data",),
    ),
}
# The page a LinkedIn posting shows in the workstation's browser (decision E5): the page recorded in C2.
SHOWN = ShownPage(
    "https://fr.linkedin.com/jobs/view/data-analyst-at-plenitude-4468625023",
    (
        Path(__file__).parent / "imports" / "data" / "linkedin" / "posting.html"
    ).read_text(),
)
QUEUE = ["analyst", "python", "scientist", "junior", "junior_apec", "excerpt"]
BELOW = ["accounting", "manager"]


@dataclass(frozen=True)
class Board:
    client: TestClient
    seeker: Seeker
    ids: dict[str, int]
    engine: Engine

    def id(self, name: str) -> int:
        return self.ids[name]


def seed(engine: Engine, email: str) -> tuple[Seeker, dict[str, int]]:
    with engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        seeker = equip(connection, account.id, email)
        inputs = scoring_inputs(seeker.profile(connection))
        ids = {}
        for name, (offer, tracks) in POSTINGS.items():
            ids[name] = record_offer(
                SqlStore(connection),
                account_id=account.id,
                offer=offer,
                inputs=inputs,
                origin=Origin.WATCH,
                track_ids=[seeker.tracks[track] for track in tracks],
                now=NOW,
                today=TODAY,
            ).offer_id
    return seeker, ids


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    app = make_app(migrated_engine)
    app.state.auth.clock.now = NOW
    use_model(app, FakeModel(SUMMARY))
    app.state.workstation = FakeBrowser(SHOWN)
    return app


@pytest.fixture
def board(app: FastAPI, migrated_engine: Engine) -> Board:
    client, email = logged_in(app, migrated_engine)
    seeker, ids = seed(migrated_engine, email)
    return Board(client, seeker, ids, migrated_engine)


def title(name: str) -> str:
    return str(escape(POSTINGS[name][0].title))


def card_of(html: str) -> str:
    return html.split('class="card offer-card"')[1]


def decide(
    board: Board,
    name: str,
    decision: str = "rejected",
    reasons: tuple[str, ...] = ("too_senior",),
    note: str = "",
    context: str = "tri",
    track: str = "",
) -> str:
    response = board.client.post(
        f"/offres/{board.id(name)}/decision",
        data={
            "decision": decision,
            "motifs": list(reasons),
            "precision": note,
            "contexte": context,
            "piste": track,
        },
        headers=HTMX,
    )
    assert response.status_code == 200
    return response.text


def rows(html: str) -> list[int]:
    return [int(i) for i in re.findall(r'hx-get="/offres/(\d+)/fiche', html)]


def to_review(html: str) -> int:
    match = re.search(r"<strong>(\d+)</strong> à examiner", html)
    assert match is not None
    return int(match.group(1))


def event_types(board: Board) -> list[str]:
    with board.engine.connect() as connection:
        return list(
            connection.execute(
                select(events.c.type)
                .where(events.c.account_id == board.seeker.account_id)
                .where(events.c.type.like("offres.decision_%"))
                .order_by(events.c.id)
            ).scalars()
        )


def test_offers_open_on_triage_with_the_best_offer(board: Board) -> None:
    page = board.client.get("/offres")

    assert page.status_code == 200
    assert 'aria-current="page">Trier' in page.text
    assert title("analyst") in card_of(page.text)
    assert to_review(page.text) == len(QUEUE)
    assert f"{len(BELOW)} sous le seuil →" in page.text
    assert "Prototype" not in page.text


def test_the_cockpit_counts_the_offers_to_review(board: Board) -> None:
    """Decision G3: the instrument « Offres à examiner » is the queue of the triage; before a first watch, the start
    list is the hero and carries the one main button (Q6, Q12)."""
    page = board.client.get("/").text

    assert '<p class="instrument-figure">' + str(len(QUEUE)) + "</p>" in page
    assert 'href="/offres?vue=tri">Trier les offres</a>' in page
    assert "Pour démarrer" in page
    assert page.count("btn-primary") == 1


def test_a_decision_needs_a_reason(board: Board) -> None:
    response = board.client.post(
        f"/offres/{board.id('analyst')}/decision",
        data={"decision": "rejected", "contexte": "tri"},
        headers=HTMX,
    )

    assert "Choisis au moins un motif." in response.text
    assert response.headers["HX-Retarget"] == "#decision-area"
    assert event_types(board) == []  # nothing recorded


def test_other_needs_a_note(board: Board) -> None:
    html = decide(board, "analyst", "interested", ("other",))

    assert "Précise le motif « autre »." in html


def test_the_reasons_panel_lists_the_reasons_of_the_decision(board: Board) -> None:
    panel = board.client.get(
        f"/offres/{board.id('analyst')}/motifs?decision=rejected&contexte=tri",
        headers=HTMX,
    ).text

    assert "Pourquoi écartée ?" in panel
    assert 'value="sector"' in panel and 'value="blocking_condition"' in panel
    assert 'value="too_junior"' not in panel
    assert 'data-key="9"' in panel
    assert re.search(
        r'data-key="0">\s*<input type="checkbox" name="motifs" value="other"', panel
    )


def test_a_decision_is_stored_with_its_score_and_its_event(board: Board) -> None:
    html = decide(board, "analyst", "rejected", ("too_senior", "sector"))

    assert html.startswith('<section id="triage"')
    assert title("python") in card_of(html)
    assert 'hx-swap-oob="true"' in html
    assert to_review(html) == len(QUEUE) - 1
    with board.engine.connect() as connection:
        row = connection.execute(
            select(job_decisions).where(job_decisions.c.offer_id == board.id("analyst"))
        ).one()
        event = connection.execute(
            select(events).where(
                events.c.type == "offres.decision_recorded",
                events.c.subject_id == str(board.id("analyst")),
            )
        ).one()
    assert (row.kind, row.value, row.reasons, row.author) == (
        "decision",
        "rejected",
        ["too_senior", "sector"],
        "user",
    )
    # Q11: the best track was shown in triage, and the whole score is kept.
    assert row.track_id == board.seeker.tracks["Data"]
    assert row.displayed_score == 75
    assert len(row.score["tracks"]) == 2 and row.inputs_hash
    assert event.actor == "user"
    assert event.payload["value"] == "rejected"
    assert event.payload["decision_id"] == row.id


def test_without_javascript_a_decision_redirects(board: Board) -> None:
    response = board.client.post(
        f"/offres/{board.id('analyst')}/decision",
        data={"decision": "later", "motifs": ["reread"], "contexte": "tri"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/offres?vue=tri"


def test_undo_goes_back_several_decisions_and_lasts(board: Board) -> None:
    for name in ("analyst", "python", "scientist"):
        decide(board, name)
    # « Annuler » reads the stored decisions: nothing is kept in memory between requests.
    for name in ("scientist", "python", "analyst"):
        html = board.client.post("/offres/annuler", headers=HTMX).text
        assert title(name) in card_of(html)

    assert to_review(html) == len(QUEUE)
    assert re.search(r'data-key="u"[^>]*disabled', html)
    assert (
        event_types(board)
        == ["offres.decision_recorded"] * 3 + ["offres.decision_cancelled"] * 3
    )


def test_undoing_a_change_brings_the_previous_decision_back(board: Board) -> None:
    decide(board, "analyst", "later", ("reread",))
    decide(board, "analyst", "interested", ("target_job",))

    board.client.post("/offres/annuler", headers=HTMX)

    later = board.client.get("/offres/liste?decision=plus_tard", headers=HTMX).text
    assert board.id("analyst") in rows(later)
    with board.engine.connect() as connection:
        payload = connection.execute(
            select(events.c.payload).where(
                events.c.type == "offres.decision_cancelled",
                events.c.subject_id == str(board.id("analyst")),
            )
        ).scalar_one()
    assert payload["value"] == "interested" and payload["restored"] == "later"


def test_j_and_k_move_between_offers_without_deciding(board: Board) -> None:
    html = board.client.get(f"/offres/tri/{board.id('python')}", headers=HTMX).text

    assert f'hx-get="/offres/tri/{board.id("analyst")}"' in html
    assert f'hx-get="/offres/tri/{board.id("scientist")}"' in html
    assert event_types(board) == []


def test_the_card_shows_what_decides(board: Board) -> None:
    card = card_of(board.client.get(f"/offres/tri/{board.id('junior')}").text)

    assert "Data" in card  # its track
    assert "✔ Python" not in card and "≈ Python" in card  # declared, not proven
    assert f'hx-get="/offres/tri/{board.id("junior_apec")}"' in card
    assert "vue aussi sur Apec" in card
    assert 'data-key="c"' not in card  # complete: nothing to paste


def test_why_explains_each_component_of_the_shown_track(board: Board) -> None:
    offer = board.id("scientist")
    best = board.client.get(f"/offres/{offer}/pourquoi", headers=HTMX).text
    data = board.client.get(
        f"/offres/{offer}/pourquoi?piste={board.seeker.tracks['Data']}", headers=HTMX
    ).text

    assert "Score : 75 / 100" in best
    assert "Score : 49 / 100" in data
    for label in ("Compétences", "Intitulé", "Contrat", "Lieu"):
        assert label in best


def test_list_filters_are_independent(board: Board) -> None:
    get = board.client.get
    above = rows(get("/offres/liste", headers=HTMX).text)
    with_below = rows(get("/offres/liste?sous_seuil=1", headers=HTMX).text)
    incomplete = rows(get("/offres/liste?incompletes=1", headers=HTMX).text)

    assert set(above) == {board.id(name) for name in QUEUE}
    assert set(with_below) == {board.id(name) for name in QUEUE + BELOW}
    assert with_below[-len(BELOW) :] == [board.id("manager"), board.id("accounting")]
    # Q13: the incomplete offers above and under the threshold.
    assert set(incomplete) == {board.id("excerpt"), board.id("manager")}


def test_a_list_filtered_on_a_track_shows_its_score(board: Board) -> None:
    data = board.seeker.tracks["IA"]

    html = board.client.get(f"/offres/liste?piste={data}", headers=HTMX).text

    assert rows(html) == [board.id("scientist")]
    assert ">75</span>" in html
    assert f"/offres/{board.id('scientist')}/fiche?piste={data}" in html


def test_a_decision_from_a_filtered_list_keeps_the_shown_track(board: Board) -> None:
    data = board.seeker.tracks["Data"]
    decide(
        board,
        "scientist",
        "interested",
        ("growth",),
        context="fiche",
        track=str(data),
    )

    with board.engine.connect() as connection:
        row = connection.execute(
            select(job_decisions).where(
                job_decisions.c.offer_id == board.id("scientist")
            )
        ).one()
    assert (row.track_id, row.displayed_score) == (data, 49)


def test_the_list_follows_decisions(board: Board) -> None:
    decide(board, "analyst", "rejected", ("contract",))

    rejected = board.client.get("/offres/liste?decision=ecarte", headers=HTMX).text
    to_examine = board.client.get("/offres/liste", headers=HTMX).text

    assert rows(rejected) == [board.id("analyst")]
    assert board.id("analyst") not in rows(to_examine)


def test_the_list_pages_by_a_hundred(
    board: Board, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rocky.offres.web.PAGE_SIZE", 4)

    first = board.client.get("/offres/liste?sous_seuil=1", headers=HTMX).text
    more = re.search(r'hx-get="/offres/liste\?([^"]+)"', first)
    assert more is not None
    second = board.client.get(
        f"/offres/liste?{more.group(1).replace('&amp;', '&')}", headers=HTMX
    ).text

    assert len(rows(first)) == 4
    assert not second.startswith("<table")
    assert len(rows(second)) == 4
    assert "Afficher plus" not in second


def test_a_list_url_without_htmx_opens_the_whole_page(board: Board) -> None:
    response = board.client.get("/offres/liste?piste=7&sous_seuil=1")

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "/offres?vue=liste&piste=7&decision=a_examiner&sous_seuil=1"
    )


def test_the_sheet_decides_and_refreshes_the_list(board: Board) -> None:
    offer = board.id("junior")
    sheet = board.client.get(f"/offres/{offer}/fiche", headers=HTMX).text
    assert title("junior") in sheet
    assert "contexte=fiche" in sheet

    decide(board, "junior", "interested", ("skills_match",), context="fiche")
    response = board.client.post(
        f"/offres/{offer}/decision",
        data={"decision": "rejected", "motifs": ["salary"], "contexte": "fiche"},
        headers=HTMX,
    )

    assert response.headers["HX-Trigger"] == "offers-changed"
    assert "Décision : <strong>Écarté</strong>" in response.text
    assert "salaire" in response.text


def test_a_sheet_url_without_htmx_opens_the_list_with_the_sheet(board: Board) -> None:
    page = board.client.get(f"/offres/{board.id('manager')}/fiche").text

    assert 'aria-current="page">Liste' in page
    assert title("manager") in page.split('id="fiche"')[1]


def test_when_everything_is_sorted_the_list_opens(board: Board) -> None:
    for name in QUEUE:
        last = decide(board, name, "later", ("reread",))

    page = board.client.get("/offres").text

    assert "Tout est trié" in last
    assert to_review(last) == 0
    assert 'aria-current="page">Liste' in page


def test_an_account_without_offers_is_told_where_they_come_from(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    page = client.get("/offres?vue=tri").text

    assert "Aucune offre pour l'instant" in page


def test_decisions_and_offers_belong_to_their_account(
    app: FastAPI, migrated_engine: Engine, board: Board
) -> None:
    other, _ = logged_in(app, migrated_engine)
    decide(board, "analyst")

    offer = board.id("python")
    assert other.get(f"/offres/{offer}/fiche", headers=HTMX).status_code == 404
    assert other.get(f"/offres/{offer}/pourquoi", headers=HTMX).status_code == 404
    assert (
        other.post(
            f"/offres/{offer}/decision",
            data={"decision": "later", "motifs": ["reread"]},
            headers=HTMX,
        ).status_code
        == 404
    )
    assert (
        other.post(
            f"/offres/{offer}/description", data={"texte": "x"}, headers=HTMX
        ).status_code
        == 404
    )
    # Nothing to cancel for the other account: the board's decision stays.
    other.post("/offres/annuler", headers=HTMX)
    assert event_types(board) == ["offres.decision_recorded"]


def test_a_superscript_digit_is_no_track(board: Board) -> None:
    """Step H1: ``"²".isdigit()`` is true, ``int("²")`` fails: it was a 500."""
    offer = board.id("analyst")

    assert board.client.get("/offres?vue=liste&piste=²").status_code == 200
    sheet = board.client.get(f"/offres/{offer}/fiche?piste=²", headers=HTMX)
    assert sheet.status_code == 200


def test_unknown_offers_are_not_found(board: Board) -> None:
    assert (
        board.client.get("/offres/999999999/pourquoi", headers=HTMX).status_code == 404
    )
    assert board.client.get("/offres/999999999/fiche", headers=HTMX).status_code == 404


def test_a_pasted_description_scores_the_offer_again(board: Board) -> None:
    offer = board.id("manager")
    card = board.client.get(f"/offres/{offer}/fiche", headers=HTMX).text
    assert "Coller la description" in card and 'data-key="c"' in card

    html = board.client.post(
        f"/offres/{offer}/description",
        data={
            "texte": "Chef de projet data analyst.\nPython, SQL et Tableau exigés.",
            "contexte": "fiche",
        },
        headers=HTMX,
    )

    assert html.headers["HX-Trigger"] == "offers-changed"
    assert "annonce incomplète" not in html.text
    with board.engine.connect() as connection:
        stored = connection.execute(
            select(job_offers).where(job_offers.c.id == offer)
        ).one()
        event = connection.execute(
            select(events.c.payload).where(
                events.c.type == "offres.offer_enriched",
                events.c.subject_id == str(offer),
            )
        ).scalar_one()
    assert stored.description_complete
    assert stored.last_seen_at == NOW  # a paste is not a new sighting
    assert event["score_after"] > event["score_before"]


def test_an_empty_paste_says_why(board: Board) -> None:
    offer = board.id("excerpt")

    html = board.client.post(
        f"/offres/{offer}/description",
        data={"texte": "   ", "contexte": "tri"},
        headers=HTMX,
    ).text

    assert "Colle le texte de l&#39;annonce." in html
    assert title("excerpt") in card_of(html)  # the offer stays on screen


# The lecture assistée (decision E5).


def browser(app: FastAPI) -> FakeBrowser:
    fake: FakeBrowser = app.state.workstation
    return fake


def enrichment(board: Board, offer: int) -> dict[str, object] | None:
    with board.engine.connect() as connection:
        payload = connection.execute(
            select(events.c.payload).where(
                events.c.type == "offres.offer_enriched",
                events.c.subject_id == str(offer),
            )
        ).scalar_one_or_none()
    return None if payload is None else dict(payload)


def test_only_an_incomplete_offer_offers_to_open_its_posting(board: Board) -> None:
    incomplete = board.client.get(f"/offres/{board.id('manager')}/fiche", headers=HTMX)
    complete = board.client.get(f"/offres/{board.id('analyst')}/fiche", headers=HTMX)

    assert "Ouvrir dans le navigateur" in incomplete.text
    assert 'data-key="n"' in incomplete.text
    assert "Ouvrir dans le navigateur" not in complete.text


def data_keys(html: str) -> list[str]:
    return re.findall(r'data-key="([^"]+)"', html)


def test_each_key_of_an_incomplete_offer_does_one_thing(board: Board) -> None:
    """« e » is « Écarté »; the lecture assistée has its own key, before and after the tab is opened (H1)."""
    offer = board.id("manager")
    triage = board.client.get(f"/offres/tri/{offer}").text
    sheet = board.client.get(f"/offres/{offer}/fiche").text
    opened = board.client.post(
        f"/offres/{offer}/navigateur",
        data={"contexte": "tri", "piste": ""},
        headers=HTMX,
    ).text

    for page in (triage, sheet):
        keys = data_keys(page)
        assert "Ouvrir dans le navigateur" in page
        assert len(keys) == len(set(keys)), keys
        assert keys.count("n") == 1
    assert data_keys(opened) == ["n"]


def test_a_posting_is_opened_then_its_page_completes_the_offer(
    board: Board, app: FastAPI
) -> None:
    offer = board.id("manager")

    opened = board.client.post(
        f"/offres/{offer}/navigateur",
        data={"contexte": "fiche", "piste": ""},
        headers=HTMX,
    ).text

    assert browser(app).opened == ["https://linkedin.example/offres/manager"]
    assert "Lire la page affichée" in opened
    assert 'name="onglet" value="onglet-1"' in opened
    assert 'hx-target="#fiche"' in opened

    read = board.client.post(
        f"/offres/{offer}/navigateur/lire",
        data={"onglet": "onglet-1", "contexte": "fiche", "piste": ""},
        headers=HTMX,
    )

    assert browser(app).read == ["onglet-1"]
    assert read.headers["HX-Trigger"] == "offers-changed"
    assert READ_NOTE in read.text
    assert "Ouvrir dans le navigateur" not in read.text  # complete now
    with board.engine.connect() as connection:
        stored = connection.execute(
            select(job_offers).where(job_offers.c.id == offer)
        ).one()
    assert stored.description_complete and stored.incomplete_reason is None
    assert stored.last_seen_at == NOW
    event = enrichment(board, offer)
    assert event is not None
    assert (event["how"], event["description_read"]) == ("browser", True)


def test_an_apec_offer_is_completed_by_hand_only(board: Board, app: FastAPI) -> None:
    offer = board.id("excerpt")  # an Apec offer
    card = board.client.get(f"/offres/{offer}/fiche", headers=HTMX).text

    opened = board.client.post(
        f"/offres/{offer}/navigateur", data={"contexte": "fiche"}, headers=HTMX
    ).text

    assert "Ouvrir dans le navigateur" not in card
    assert "Coller la description" in card
    assert str(escape(BROWSER_REFUSED_REASON)) in opened
    assert browser(app).opened == []  # the workstation is never asked


def test_a_workstation_that_does_not_answer_says_why(
    board: Board, app: FastAPI
) -> None:
    browser(app).error = NOT_RUNNING

    html = board.client.post(
        f"/offres/{board.id('manager')}/navigateur",
        data={"contexte": "tri"},
        headers=HTMX,
    ).text

    assert str(escape(NOT_RUNNING)) in html
    assert "Ouvrir dans le navigateur" in html  # the gesture can be made again


def test_a_page_of_another_site_is_refused_and_the_offer_stays(
    board: Board, app: FastAPI
) -> None:
    offer = board.id("excerpt")
    browser(app).shown = ShownPage("https://login.example.com/sso", SHOWN.html)

    html = board.client.post(
        f"/offres/{offer}/navigateur/lire",
        data={"onglet": "onglet-1", "contexte": "tri"},
        headers=HTMX,
    ).text

    assert str(escape(OTHER_PAGE_REASON)) in html
    assert title("excerpt") in card_of(html)  # the offer stays on screen
    assert enrichment(board, offer) is None


def test_the_reading_of_another_account_s_offer_is_not_found(
    board: Board, app: FastAPI, migrated_engine: Engine
) -> None:
    other, _ = logged_in(app, migrated_engine)
    offer = board.id("manager")

    assert other.post(f"/offres/{offer}/navigateur", headers=HTMX).status_code == 404
    assert (
        other.post(
            f"/offres/{offer}/navigateur/lire",
            data={"onglet": "onglet-1"},
            headers=HTMX,
        ).status_code
        == 404
    )
    assert browser(app).opened == [] and browser(app).read == []


def test_a_route_about_one_offer_never_reads_the_list(
    board: Board, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step H5 (rule of the screen): only the screen that shows the list reads it."""

    def no_list(*_: object) -> None:
        raise AssertionError("the list was read")

    monkeypatch.setattr(SqlStore, "listed_offers", no_list)
    offer = board.id("manager")
    cockpit = {"contexte": "cockpit", "piste": ""}

    with pytest.raises(AssertionError, match="the list was read"):
        board.client.get("/offres", headers=HTMX)  # the check bites
    assert board.client.get(f"/offres/{offer}/fiche", headers=HTMX).status_code == 200
    assert (
        board.client.get(f"/offres/{offer}/pourquoi", headers=HTMX).status_code == 200
    )
    for path, data in (
        ("navigateur", cockpit),
        ("navigateur/lire", {**cockpit, "onglet": "onglet-1"}),
        ("description", {**cockpit, "texte": "Chef de projet data, Python et SQL."}),
    ):
        response = board.client.post(f"/offres/{offer}/{path}", data=data, headers=HTMX)
        assert response.status_code == 200, path


def test_the_reading_works_without_javascript(board: Board, app: FastAPI) -> None:
    offer = board.id("manager")

    opened = board.client.post(
        f"/offres/{offer}/navigateur", data={"contexte": "fiche"}
    )
    read = board.client.post(
        f"/offres/{offer}/navigateur/lire",
        data={"onglet": "onglet-1", "contexte": "fiche"},
        follow_redirects=False,
    )

    assert opened.status_code == 200
    assert "<html" in opened.text and "Lire la page affichée" in opened.text
    assert (read.status_code, read.headers["location"]) == (
        303,
        f"/offres/{offer}/fiche",
    )
    assert enrichment(board, offer) is not None


def test_the_summary_is_asked_once_then_kept(board: Board, app: FastAPI) -> None:
    offer = board.id("analyst")
    model: FakeModel = used_model(app)

    first = board.client.post(f"/offres/{offer}/resume", headers=HTMX).text
    card = card_of(board.client.get(f"/offres/tri/{offer}").text)

    assert "Analyser les données de vente." in first
    assert "Analyser les données de vente." in card
    assert 'data-key="r"' not in card
    assert model.calls == 1
    # Decision G4 (Q9): the call is recorded for the account, as a summary.
    with board.engine.connect() as connection:
        recorded = connection.execute(
            select(model_calls.c.call_type, model_calls.c.outcome).where(
                model_calls.c.account_id == board.seeker.account_id
            )
        ).all()
    assert [tuple(row) for row in recorded] == [("summary", "ok")]


def test_a_failed_summary_is_shown_and_not_kept(board: Board, app: FastAPI) -> None:
    use_model(app, FakeModel(error=LlmUnavailableError("délai dépassé")))
    offer = board.id("analyst")

    html = board.client.post(f"/offres/{offer}/resume", headers=HTMX).text
    card = card_of(board.client.get(f"/offres/tri/{offer}").text)

    assert "délai dépassé" in html
    assert 'data-key="r"' in card


def test_every_swap_into_the_decision_area_keeps_the_area(board: Board) -> None:
    """HTMX inherits hx-swap: "Revenir" sits in a form swapping outerHTML, so it must say innerHTML itself.

    Without it, "Revenir" replaced #decision-area and the decision buttons lost their target (bug found by Nicolas).
    """
    offer = board.id("analyst")
    panel = board.client.get(
        f"/offres/{offer}/motifs?decision=rejected&contexte=tri", headers=HTMX
    ).text
    actions = board.client.get(
        f"/offres/{offer}/actions?contexte=tri", headers=HTMX
    ).text

    for html in (panel, actions):
        for tag in re.findall(r"<[^>]*hx-target=\"#decision-area\"[^>]*>", html):
            assert 'hx-swap="innerHTML"' in tag, tag
    assert 'id="decision-area"' not in actions  # the fragment fills the area


def test_offers_of_the_board_are_all_scored(board: Board) -> None:
    with board.engine.connect() as connection:
        assert (
            SqlStore(connection).unscored_or_orphan_offers(board.seeker.account_id)
            == []
        )


def test_a_past_deadline_is_signalled_and_the_offer_stays_to_review(
    board: Board,
) -> None:
    with board.engine.begin() as connection:
        inputs = scoring_inputs(board.seeker.profile(connection))
        passed = record_offer(
            SqlStore(connection),
            account_id=board.seeker.account_id,
            offer=posting("passed", deadline=date(2026, 9, 1)),
            inputs=inputs,
            origin=Origin.WATCH,
            track_ids=[board.seeker.tracks["Data"]],
            now=NOW,
            today=TODAY,
        ).offer_id

    listed = board.client.get("/offres/liste", headers=HTMX).text
    sheet = board.client.get(f"/offres/{passed}/fiche", headers=HTMX).text
    # Signalled, never decided (decision G2, Q7, Q14): still in the queue.
    triage = board.client.get(f"/offres/tri/{passed}", headers=HTMX).text

    row = listed.split(f'hx-get="/offres/{passed}/fiche')[1].split("</tr>")[0]
    assert "date limite passée" in row
    assert "Date limite passée (01/09/2026)" in sheet
    assert "Date limite passée (01/09/2026)" in card_of(triage)
    assert "à examiner" in row
    others = listed.split(f'hx-get="/offres/{board.id("analyst")}/fiche')[1].split(
        "</tr>"
    )[0]
    assert "date limite passée" not in others


def test_at_half_past_midnight_in_paris_the_age_counts_from_the_paris_day(
    app: FastAPI,
) -> None:
    app.state.auth.clock.now = HALF_PAST_MIDNIGHT
    age = app.state.templates.env.filters["age"]

    assert age(TODAY) == "aujourd'hui"
    assert age(date(2026, 9, 28)) == "hier"


# 🧭 Cockpit (decision G3): the best offer as the hero, prepared or decided in place


def watched(board: Board) -> None:
    """A first watch that brought offers in: the start list leaves the hero (Q12)."""
    with SqlStorage(board.engine).transaction() as store:
        run_id = store.start_run(board.seeker.account_id, Trigger.SCHEDULED, NOW)
        store.finish_run(
            run_id,
            status=RunStatus.COMPLETED,
            reason=None,
            counts=RunCounts(found=8, new=8),
            sources=(),
            now=NOW,
        )


def test_an_application_is_prepared_from_the_cockpit_in_three_clicks(
    board: Board,
) -> None:
    """Criterion 1 of G3: « Préparer la candidature » (1), a reason (2), « Préparer la candidature » (3)."""
    watched(board)
    offer_id = board.id("analyst")
    page = board.client.get("/").text

    assert page.count("btn-primary") == 1
    prepare = f"/candidatures/offre/{offer_id}/preparer?contexte=cockpit"
    assert f'class="btn btn-primary" hx-get="{prepare}"' in page
    panel = board.client.get(prepare, headers=HTMX)  # click 1
    assert '<input type="hidden" name="contexte" value="cockpit">' in panel.text
    assert 'hx-target="#hero-gestures"' in panel.text
    opened = board.client.post(  # click 2 ticks a reason, click 3 sends
        f"/candidatures/offre/{offer_id}/preparer",
        data={"motifs": ["target_job"], "contexte": "cockpit"},
        headers=HTMX,
    )

    assert opened.status_code == 200
    assert re.fullmatch(r"/candidatures/\d+", opened.headers["HX-Redirect"])


def test_not_for_me_decides_in_place_and_the_cockpit_reads_itself_again(
    board: Board,
) -> None:
    watched(board)
    offer_id = board.id("analyst")

    refused = board.client.post(
        f"/offres/{offer_id}/decision",
        data={"decision": "rejected", "motifs": [], "contexte": "cockpit"},
        headers=HTMX,
    )
    decided = board.client.post(
        f"/offres/{offer_id}/decision",
        data={"decision": "rejected", "motifs": ["not_the_job"], "contexte": "cockpit"},
        headers=HTMX,
    )
    fragment = board.client.get("/", headers=HTMX).text

    assert refused.headers["HX-Retarget"] == "#hero-gestures"
    assert "Choisis au moins un motif." in refused.text
    assert (decided.headers["HX-Trigger"], decided.headers["HX-Reswap"]) == (
        "cockpit-changed",
        "none",
    )
    hero = fragment.split('id="hero"')[1].split("</section>")[0]
    assert f"/offres/{offer_id}/" not in hero
    assert title("python") in hero


def test_the_suggestions_are_the_best_offers_of_each_track_without_the_hero(
    board: Board,
) -> None:
    watched(board)

    page = board.client.get("/").text
    suggestions = page.split('id="suggestions-title"')[1].split("</section>")[0]

    assert '<h3 class="suggestion-group">Data</h3>' in suggestions
    assert '<h3 class="suggestion-group">IA</h3>' in suggestions
    assert f"/offres/{board.id('analyst')}/fiche" not in suggestions  # the hero
    assert (
        suggestions.count('class="suggestion"') == 3
    )  # two of « Data », one of « IA »
