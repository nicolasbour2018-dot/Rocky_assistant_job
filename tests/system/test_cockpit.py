"""🧭 Cockpit (decision G3): the choices of the shell (the hero, the one main gesture, the feed, the sentence) and the
screen with fake parts, state by state: exactly one main button in each (criterion 4)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from rocky.system.cockpit import (
    SENTENCES,
    FeedLine,
    Hero,
    Instrument,
    Parts,
    Sentence,
    Series,
    StartStep,
    Status,
    add_cockpit,
    greeting,
    main_gesture,
    merge_feed,
    pick_hero,
    pick_sentence,
)
from rocky.system.periods import Delta, Period
from rocky.system.shell import Action, Card
from tests.system.web_support import HTMX, logged_in, make_app

NOW = datetime(2026, 10, 7, 10, tzinfo=UTC)
PREPARE = Action(
    "Préparer la candidature",
    "/candidatures/offre/7/preparer?contexte=cockpit",
    panel=True,
)
REJECT = Action(
    "Pas pour moi", "/offres/7/motifs?decision=rejected&contexte=cockpit", panel=True
)
SHEET = Action("Voir l'offre", "/offres/7/fiche")
FIX = Action("Relancer la veille", "/veille/lancer", post=True)
OFFER = Hero(
    "offre",
    "La meilleure offre à examiner",
    "Data analyst",
    primary=PREPARE,
    others=(REJECT, SHEET),
)


def test_the_hero_is_the_first_in_the_order_of_the_ranks() -> None:
    heroes = [
        OFFER,
        Hero("veille", "Tout est à jour", "Rien", primary=FIX),
        Hero("prete", "Prêt", "Un dossier", primary=SHEET),
    ]

    found = pick_hero(heroes)

    assert found is not None and found.rank == "prete"
    assert pick_hero([Hero("ailleurs", "?", "?")]) is None


def test_a_problem_with_a_gesture_takes_the_main_button_from_the_hero() -> None:
    problem = Card("⚠️ Veille échouée", action=FIX, problem=True)

    assert main_gesture([problem], OFFER) == "problem"
    assert main_gesture([Card("Sans geste", problem=True)], OFFER) == "hero"
    assert main_gesture([], Hero("veille", "En cours", "Veille")) == "none"


def test_the_feed_puts_the_states_first_then_seven_days_the_latest_first() -> None:
    since = NOW - timedelta(hours=2)
    lines = [
        FeedLine(NOW - timedelta(days=8), "Trop ancien."),
        FeedLine(NOW - timedelta(days=1), "Hier."),
        FeedLine(NOW - timedelta(hours=1), "Depuis la visite."),
        FeedLine(NOW, "Relance due.", standing=True),
    ]

    standing, days = merge_feed(lines, since=since, now=NOW)

    assert [e.line.text for e in standing] == ["Relance due."]
    assert [d.label for d in days] == ["Aujourd'hui", "Hier"]
    assert [(e.line.text, e.new) for d in days for e in d.entries] == [
        ("Depuis la visite.", True),
        ("Hier.", False),
    ]
    _, first_visit = merge_feed(lines, since=None, now=NOW)
    assert not any(e.new for d in first_visit for e in d.entries)


def test_the_feed_keeps_twenty_lines() -> None:
    lines = [FeedLine(NOW - timedelta(minutes=i), f"Ligne {i}.") for i in range(30)]

    _, days = merge_feed(lines, since=None, now=NOW)

    assert sum(len(d.entries) for d in days) == 20


def test_the_heaviest_sentence_else_the_sentence_of_the_day() -> None:
    day = date(2026, 10, 7)

    assert (
        pick_sentence([Sentence(20, "Série."), Sentence(70, "Relance.")], day)
        == "Relance."
    )
    assert pick_sentence([], day) == SENTENCES[day.toordinal() % len(SENTENCES)]
    assert pick_sentence([], day) == pick_sentence([], day)  # the same all day long


def test_the_greeting_takes_the_first_word_of_the_name() -> None:
    assert greeting("Nicolas Bour") == "Bonjour Nicolas"
    assert greeting("  ") == "Bonjour"
    assert greeting(None) == "Bonjour"


def test_a_part_of_an_unknown_module_is_refused() -> None:
    with pytest.raises(KeyError):
        add_cockpit(FastAPI(), "ailleurs", Parts())


# The screen, with fake parts


@pytest.fixture
def app(migrated_engine: Engine) -> FastAPI:
    return make_app(migrated_engine)


def _parts(app: FastAPI, **parts: Parts) -> None:
    """Replace the parts of the modules by ``parts`` (key → parts)."""
    app.state.cockpit_parts = dict(parts)


def _given[T](*found: T) -> Callable[[object, object], list[T]]:
    return lambda request, account: list(found)


INSTRUMENT = Instrument(
    "offres",
    "Offres à examiner",
    "12",
    "dont 3 à 75 ou plus",
    Delta(5, 2),
    "arrivées",
    Action("Trier les offres", "/offres?vue=tri"),
)


def _series(
    request: object, account: object, key: str, period: Period
) -> Series | None:
    if key != "offres":
        return None
    labels = ("28/09", "05/10") if period is Period.WEEK else ("sept.", "oct.")
    return Series(("Arrivées", "Décidées"), labels, ((3, 5), (1, 2)))


def _feed(*lines: FeedLine) -> Callable[[object, object, object], list[FeedLine]]:
    return lambda request, account, since: list(lines)


def _primaries(page: str) -> int:
    return page.count("btn-primary")


def test_a_new_account_has_the_start_list_and_one_main_button(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    importing = Action("Importer ton CV", "/profil/kit")
    _parts(
        app,
        candidatures=Parts(
            heroes=_given(
                Hero(
                    "demarrage",
                    "Pour démarrer",
                    "Encore 3 étapes et Rocky cherche pour toi",
                    primary=importing,
                    steps=(
                        StartStep("Profil complété", True),
                        StartStep("Première piste", True),
                        StartStep("CV importé", False, importing),
                        StartStep(
                            "Gmail connecté",
                            False,
                            Action("Connecter une boîte Gmail", "/messages"),
                        ),
                        StartStep("Première veille", False, FIX),
                    ),
                ),
                OFFER,
            )
        ),
    )

    page = client.get("/").text

    assert "Encore 3 étapes et Rocky cherche pour toi" in page
    assert "Data analyst" not in page  # the start list comes first (Q12)
    assert _primaries(page) == 1
    assert 'class="btn btn-primary btn-small" href="/profil/kit"' in page


def test_a_problem_carries_the_main_button_above_the_hero(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _parts(
        app,
        veille=Parts(
            problems=_given(
                Card(
                    "⚠️ Veille échouée",
                    ("LinkedIn a refusé.",),
                    action=FIX,
                    problem=True,
                )
            )
        ),
        offres=Parts(heroes=_given(OFFER)),
    )

    page = client.get("/").text

    assert page.index("Veille échouée") < page.index("Data analyst")
    assert _primaries(page) == 1
    assert 'class="btn btn-primary">Relancer la veille</button>' in page
    assert ">Préparer la candidature</button>" in page


def test_the_best_offer_is_prepared_from_the_hero_in_place(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _parts(
        app,
        offres=Parts(
            heroes=_given(OFFER),
            instruments=_given(INSTRUMENT),
            sentences=_given(Sentence(25, "La meilleure offre du jour est à 86.")),
        ),
    )

    page = client.get("/").text

    assert _primaries(page) == 1
    assert (
        '<button type="button" class="btn btn-primary" hx-get="/candidatures/offre/7/preparer?contexte=cockpit" '
        'hx-target="#hero-gestures" hx-swap="innerHTML">Préparer la candidature</button>'
    ) in page
    assert "La meilleure offre du jour est à 86." in page
    assert "Offres à examiner" in page and ">+3</strong>" in page
    assert 'href="/offres?vue=tri">Trier les offres</a>' in page


def test_nothing_to_do_leaves_the_watch_as_the_main_button(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _parts(
        app,
        veille=Parts(
            heroes=_given(
                Hero(
                    "veille", "Tout est à jour", "Aucune offre à examiner", primary=FIX
                )
            ),
            status=_given(
                Status(
                    "Dernière veille le 07/10 à 12:04 : 3 offres, dont 1 nouvelle.", FIX
                )
            ),
        ),
    )

    page = client.get("/").text

    assert _primaries(page) == 1
    assert 'class="btn btn-primary">Relancer la veille</button>' in page
    assert (
        'class="btn btn-small">Relancer la veille</button>' in page
    )  # the line of state: a plain button


def test_a_fragment_is_the_cockpit_alone_and_keeps_the_previous_visit(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    clock = app.state.auth.clock
    # A watch finished between the two visits.
    line = FeedLine(
        clock.now + timedelta(hours=1), "Veille terminée : 3 offres, dont 1 nouvelle."
    )
    _parts(app, offres=Parts(heroes=_given(OFFER), feed=_feed(line)))

    first = client.get("/").text
    clock.advance(timedelta(hours=2))
    second = client.get("/").text
    since = (clock.now - timedelta(hours=2)).isoformat()
    fragment = client.get("/", params={"depuis": since}, headers=HTMX).text

    assert "Veille terminée" not in first
    assert "nouveau</span>" in second
    assert fragment.lstrip().startswith('<div id="cockpit"')
    assert "<html" not in fragment
    assert "nouveau</span>" in fragment
    assert 'hx-trigger="cockpit-changed from:body"' in fragment


def test_an_instrument_turns_to_its_chart_on_weeks_or_months(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _parts(app, offres=Parts(instruments=_given(INSTRUMENT), series=_series))

    weeks = client.get("/cockpit/instrument/offres?periode=semaine", headers=HTMX).text
    months = client.get("/cockpit/instrument/offres?periode=mois", headers=HTMX).text
    front = client.get("/cockpit/instrument/offres", headers=HTMX).text

    assert 'class="instrument instrument-back"' in weeks
    assert "<svg" in weeks and "<title>05/10 : 5 — Arrivées</title>" in weeks
    assert "12 dernières semaines" in weeks
    assert 'aria-pressed="true"' in weeks and "<td>sept.</td>" in months
    assert "<svg" not in front and ">Évolution</button>" in front
    assert (
        client.get(
            "/cockpit/instrument/ailleurs?periode=semaine", headers=HTMX
        ).status_code
        == 404
    )
    assert (
        client.get("/cockpit/instrument/offres?periode=an", headers=HTMX).status_code
        == 404
    )


def test_the_line_of_a_running_watch_is_read_again_until_it_stops(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    running: list[Status] = [
        Status("Veille en cours depuis le 07/10 à 12:00.", polling=True)
    ]
    _parts(app, veille=Parts(status=lambda request, account: list(running)))

    page = client.get("/").text
    polled = client.get("/cockpit/etat", headers=HTMX)
    running[0] = Status(
        "Dernière veille le 07/10 à 12:00 : 3 offres, dont 1 nouvelle.", FIX
    )
    done = client.get("/cockpit/etat", headers=HTMX)

    assert 'hx-get="/cockpit/etat" hx-trigger="every 15s"' in page
    assert "HX-Trigger" not in polled.headers
    assert done.headers["HX-Trigger"] == "cockpit-changed"
    assert "every 15s" not in done.text


def _celebrate(found: Sequence[str]) -> Callable[[object, object, object], list[str]]:
    return lambda request, account, since: list(found)


def test_a_celebration_and_the_news_show_from_the_second_visit(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)
    _parts(
        app,
        candidatures=Parts(
            heroes=_given(OFFER),
            celebrations=_celebrate(["Objectif de la semaine atteint : 3 sur 3."]),
            news=_celebrate(["1 réponse"]),
        ),
    )

    first = client.get("/").text
    second = client.get("/").text

    assert "Objectif de la semaine atteint" not in first
    assert "Objectif de la semaine atteint : 3 sur 3." in second
    assert "Depuis ton dernier passage, le 24/09 à 14:00 : 1 réponse." in second


# The real modules


def test_a_new_account_with_the_real_modules_has_the_start_list_and_one_main_button(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    page = client.get("/").text

    assert "Pour démarrer" in page and "Encore " in page
    assert page.count("btn-primary") == 1
    for title in ("Offres à examiner", "Dossiers en cours", "Cette semaine", "Retours"):
        assert title in page


def test_the_goal_of_the_week_is_changed_from_the_cockpit(
    app: FastAPI, migrated_engine: Engine
) -> None:
    client, _ = logged_in(app, migrated_engine)

    changed = client.post("/profil/objectif", data={"objectif": "5"}, headers=HTMX)
    refused = client.post("/profil/objectif", data={"objectif": "11"}, headers=HTMX)
    page = client.get("/").text

    assert changed.headers["HX-Trigger"] == "cockpit-changed"
    assert refused.status_code == 422
    assert '<option value="5" selected>5</option>' in page
    assert "0/5" in page


def test_no_gesture_of_the_cockpit_inherits_a_target(
    app: FastAPI, migrated_engine: Engine
) -> None:
    """A boosted link or form inherits ``hx-target`` and ``hx-swap``: on a container, they would put the next page
    inside the cockpit (recette of G3). The reloads are asked by empty elements."""
    client, _ = logged_in(app, migrated_engine)
    running = Status("Veille en cours depuis le 07/10 à 12:00.", polling=True)
    _parts(
        app,
        veille=Parts(status=_given(running)),
        offres=Parts(heroes=_given(OFFER)),
    )

    page = client.get("/").text

    assert '<div id="cockpit" class="cockpit">' in page
    assert '<div id="cockpit-status" class="cockpit-status">' in page
    assert 'hx-target="this"' not in page
    assert (
        '<div hidden hx-get="/cockpit/etat" hx-trigger="every 15s" hx-target="#cockpit-status" '
        'hx-swap="outerHTML"></div>'
    ) in page
