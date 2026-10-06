"""What 🏠 Aujourd'hui shows of the applications (decision F1, Q5): the follow-ups due, then the applications to finish;
and the drawer 🐾 of 📝 Candidatures (Q12): the applications whose action is due, each to its page.

Both blocks read the rows of the screen 📝 Candidatures (``web.rows_of``), once per request: no second reading of the
applications (plan §8, D6 → F1).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from fastapi import FastAPI, Request

from rocky.candidatures.dossier_web import dossier_url
from rocky.candidatures.model import (
    BEFORE_SENDING,
    FOLLOW_UP_STAGES,
    STAGE_LABELS,
    Stage,
)
from rocky.candidatures.rules import Tab
from rocky.candidatures.web import Row, rows_of
from rocky.candidatures.web_common import engine_of
from rocky.system.auth.model import Account
from rocky.system.clock import today_of
from rocky.system.shell import Action, Card, Drawer, add_drawer, add_today_cards

# The applications named in a block; the others are counted.
SHOWN_ROWS = 3


def install(app: FastAPI) -> None:
    add_today_cards(app, "relances", _follow_up_cards)
    add_today_cards(app, "dossiers", _unfinished_cards)
    add_drawer(app, "applications", _drawer)


def _rows(request: Request, account: Account) -> list[Row]:
    """The rows of the account, read once for the two blocks of the request."""
    cached: list[Row] | None = getattr(request.state, "application_rows", None)
    if cached is None:
        with engine_of(request).connect() as connection:
            cached = rows_of(connection, account.id, today_of(request))
        request.state.application_rows = cached
    return cached


def _follow_up_cards(request: Request, account: Account) -> list[Card]:
    card = follow_up_card(_rows(request, account), today_of(request))
    return [] if card is None else [card]


def _unfinished_cards(request: Request, account: Account) -> list[Card]:
    card = unfinished_card(_rows(request, account), today_of(request))
    return [] if card is None else [card]


def follow_up_card(rows: Sequence[Row], today: date) -> Card | None:
    """« Relances dues »: the sent applications whose next action is due, the most overdue first."""
    due = sorted(
        (
            row
            for row in rows
            if row.stage in FOLLOW_UP_STAGES and Tab.TO_DO in row.tabs
        ),
        key=_by_due,
    )
    if not due:
        return None
    lines = [_due_line(row, today) for row in due[:SHOWN_ROWS]]
    lines.extend(_more(len(due)))
    return Card(
        "📝 Relances dues",
        tuple(lines),
        action=Action("Voir les relances", "/candidatures"),
    )


def unfinished_card(rows: Sequence[Row], today: date) -> Card | None:
    """« Dossiers à finir »: the applications not sent yet, those due first."""
    unfinished = sorted(
        (row for row in rows if row.stage in BEFORE_SENDING), key=_by_due
    )
    if not unfinished:
        return None
    lines = [
        _due_line(row, today)
        if row.next_action
        else f"{_label(row)} : {STAGE_LABELS[row.stage]}"
        for row in unfinished[:SHOWN_ROWS]
    ]
    lines.extend(_more(len(unfinished)))
    preparing = any(row.stage is Stage.PREPARING for row in unfinished)
    tab = Tab.PREPARING if preparing else Tab.READY
    return Card(
        "📝 Dossiers à finir",
        tuple(lines),
        action=Action("Finir les dossiers", f"/candidatures?vue={tab.value}"),
    )


def _by_due(row: Row) -> tuple[date, int]:
    return (row.next_action.due if row.next_action else date.max, row.id)


def _label(row: Row) -> str:
    return " — ".join(part for part in (row.offer.company, row.offer.title) if part)


def _due_line(row: Row, today: date) -> str:
    action = row.next_action
    if action is None:
        return _label(row)
    if action.due < today:
        when = f"en retard depuis le {action.due:%d/%m}"
    elif action.due == today:
        when = "aujourd'hui"
    else:
        when = f"le {action.due:%d/%m}"
    return f"{_label(row)} : {action.label} ({when})"


def _more(count: int) -> list[str]:
    others = count - SHOWN_ROWS
    if others <= 0:
        return []
    s = "s" if others > 1 else ""
    return [f"… et {others} autre{s}."]


def _drawer(request: Request, account: Account) -> Drawer:
    return Drawer(actions=due_actions(_rows(request, account)))


def due_actions(rows: Sequence[Row]) -> tuple[Action, ...]:
    """The applications whose next action is due, the most overdue first, each to its page."""
    due = sorted((row for row in rows if Tab.TO_DO in row.tabs), key=_by_due)
    return tuple(
        Action(f"{_label(row)} : {row.next_action.label}", dossier_url(row.id, None))
        for row in due
        if row.next_action is not None
    )
