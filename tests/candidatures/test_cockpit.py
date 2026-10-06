"""What 📝 Candidatures gives 🧭 Cockpit (decision G3): the heroes in their order (Q27), the start list (Q12), the
instruments and their flows (Q13, Q20), the states of the feed (Q16), the sentences (Q3) and the drawer (F1, Q12)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from rocky.candidatures.cockpit import (
    Reading,
    application_heroes,
    application_instruments,
    application_sentences,
    application_series,
    due_actions,
    start_hero,
    state_lines,
)
from rocky.candidatures.model import NextAction, Stage
from rocky.candidatures.progress import Moments, Reached, Start
from rocky.candidatures.rules import tabs_of
from rocky.candidatures.web import Row
from rocky.offres.model import OfferHeading
from rocky.system.cockpit import pick_hero
from rocky.system.periods import Period

# Wednesday 7 October 2026.
TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 10, tzinfo=UTC)
NOTHING = Moments()


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 10, tzinfo=UTC)


def row(
    row_id: int,
    stage: Stage,
    *,
    due_in: int | None = None,
    deadline_in: int | None = None,
    company: str = "Acme",
) -> Row:
    action = (
        None
        if due_in is None
        else NextAction("Relancer", TODAY + timedelta(days=due_in))
    )
    return Row(
        row_id,
        OfferHeading(row_id, f"Data analyst {row_id}", company, "Paris"),
        stage,
        action,
        action is not None and action.due < TODAY,
        None if deadline_in is None else TODAY + timedelta(days=deadline_in),
        tabs_of(stage, action, TODAY),
    )


def reading(
    rows: list[Row],
    moments: Moments = NOTHING,
    goal: int = 3,
    active: frozenset[date] = frozenset(),
) -> Reading:
    return Reading(
        rows,
        [],
        {},
        moments,
        [],
        set(active),
        Start(watch=Reached(True, NOW)),
        goal,
        TODAY,
    )


def test_the_follow_up_due_comes_first_then_the_ready_dossier_then_the_dossier_to_finish() -> (
    None
):
    rows = [
        row(1, Stage.PREPARING, deadline_in=10),
        row(2, Stage.PREPARING, deadline_in=2),
        row(3, Stage.READY),
        row(4, Stage.SENT, due_in=0),
        row(5, Stage.SENT, due_in=-2),
        row(6, Stage.SENT, due_in=4),  # not due yet
    ]

    heroes = application_heroes(rows, TODAY)

    assert [h.rank for h in heroes] == ["relance", "prete", "en_cours"]
    relance, prete, en_cours = heroes
    assert relance.title == "Data analyst 5 chez Acme"  # the most overdue
    assert relance.kind == "En retard depuis le 05/10"
    assert (
        relance.primary is not None
        and relance.primary.url == "/candidatures/5?etape=suivi"
    )
    assert (
        prete.primary is not None and prete.primary.url == "/candidatures/3?etape=envoi"
    )
    assert en_cours.title == "Data analyst 2 chez Acme"  # the nearest deadline
    assert en_cours.chips == ("Date limite le 09/10",)
    picked = pick_hero(heroes)
    assert picked is not None and picked.rank == "relance"


def test_the_start_list_points_at_the_first_step_not_done() -> None:
    hero = start_hero(Start(profile=Reached(True), track=Reached(True)))

    assert hero.rank == "demarrage"
    assert hero.title == "Encore 3 étapes et Rocky cherche pour toi"
    assert [step.done for step in hero.steps] == [True, True, False, False, False]
    assert hero.primary is not None and hero.primary.url == "/profil/kit"
    assert hero.steps[0].action is None


def test_the_instruments_say_now_and_the_delta_at_the_same_point() -> None:
    moments = Moments(
        opened=(at(date(2026, 10, 5)), at(date(2026, 9, 29))),
        sent=(at(date(2026, 10, 6)), at(date(2026, 9, 28)), at(date(2026, 9, 30))),
        answered=(at(date(2026, 10, 7)),),
        interviews=(at(date(2026, 10, 7)),),
    )
    rows = [row(1, Stage.PREPARING), row(2, Stage.READY), row(3, Stage.SENT)]

    dossiers, semaine, retours = application_instruments(
        reading(rows, moments, goal=2, active=frozenset({date(2026, 10, 5)}))
    )

    assert (dossiers.figure, dossiers.detail) == ("2", "dont 1 prêt à envoyer")
    assert dossiers.delta is not None and (
        dossiers.delta.now,
        dossiers.delta.before,
    ) == (1, 1)
    assert semaine.ring is not None and (semaine.ring.done, semaine.ring.goal) == (1, 2)
    assert [d.active for d in semaine.ring.days] == [True, False, False, False, False]
    assert semaine.delta is not None and (semaine.delta.now, semaine.delta.before) == (
        1,
        2,
    )
    assert retours.figure == "1"
    assert retours.detail == "réponse sur 3 envoyées, dont 1 entretien"


def test_the_series_of_the_week_carry_the_goal_line_and_the_months_do_not() -> None:
    moments = Moments(sent=(at(date(2026, 10, 6)), at(date(2026, 9, 1))))

    weeks = application_series(reading([], moments, goal=4), "semaine", Period.WEEK)
    months = application_series(reading([], moments, goal=4), "semaine", Period.MONTH)

    assert weeks is not None and weeks.goal == 4 and weeks.values[0][-1] == 1
    assert months is not None and months.goal is None
    assert months.values[0][-2:] == (1, 1)
    assert application_series(reading([]), "offres", Period.WEEK) is None


def test_the_feed_keeps_the_follow_ups_and_the_near_deadlines_as_states() -> None:
    rows = [
        row(1, Stage.SENT, due_in=-1),
        row(2, Stage.PREPARING, deadline_in=3),
        row(3, Stage.PREPARING, deadline_in=4),  # too far
    ]

    lines = state_lines(rows, TODAY, NOW)

    assert [line.text for line in lines] == [
        "Relancer : Data analyst 1 chez Acme (depuis le 06/10).",
        "Date limite le 10/10 : Data analyst 2 chez Acme.",
    ]
    assert all(line.standing for line in lines)


def test_the_heaviest_sentence_is_the_follow_up_then_the_ready_dossier() -> None:
    sentences = application_sentences(
        reading([row(1, Stage.READY), row(2, Stage.SENT, due_in=0)], goal=1)
    )

    assert (
        max(sentences, key=lambda s: s.weight).text
        == "Data analyst 2 chez Acme attend ta relance."
    )
    one_left = application_sentences(reading([], goal=1))
    assert [s.text for s in one_left] == [
        "Plus qu'une candidature pour ton objectif de la semaine."
    ]


def test_the_drawer_leads_to_each_application_whose_action_is_due() -> None:
    actions = due_actions(
        [
            row(1, Stage.SENT, due_in=0),
            row(2, Stage.SENT, due_in=3),
            row(3, Stage.PREPARING, due_in=-1, company="Covéa"),
        ]
    )

    assert [(action.label, action.url) for action in actions] == [
        ("Data analyst 3 chez Covéa : Relancer", "/candidatures/3"),
        ("Data analyst 1 chez Acme : Relancer", "/candidatures/1"),
    ]
