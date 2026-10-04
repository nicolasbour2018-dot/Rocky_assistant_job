"""The chronology of an application (decision D6, Q7): every event the use cases write has its French line."""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

from rocky.candidatures import timeline as timeline_module
from rocky.candidatures.timeline import LINES, timeline
from rocky.system.events import Actor, JsonValue, StoredEvent

AT = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
CANDIDATURES = Path(timeline_module.__file__).parent


def event(
    type_: str, payload: dict[str, JsonValue], actor: Actor = Actor.USER
) -> StoredEvent:
    return StoredEvent(1, AT, type_, actor, payload)


def written_types() -> set[str]:
    """The event types appearing as string literals in the module's code."""
    found = set()
    for path in CANDIDATURES.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.fullmatch(r"candidatures\.[a-z_]+", node.value)
            ):
                found.add(node.value)
    return found


def test_every_event_written_has_its_line() -> None:
    written = written_types()

    assert "candidatures.action_done" in written  # the scan sees the use cases
    assert written <= set(LINES)


def test_the_major_facts_and_the_details() -> None:
    lines = timeline(
        [
            event(
                "candidatures.stage_changed",
                {"from": "ready", "to": "sent", "next_action": None},
            ),
            event(
                "candidatures.next_action_set",
                {
                    "next_action": {"label": "Relancer", "due": "2026-10-14"},
                    "previous": None,
                    "deferred_days": 3,
                },
            ),
            event(
                "candidatures.action_done",
                {
                    "done": {"label": "Relancer", "due": "2026-10-11"},
                    "next_action": {"label": "Relancer", "due": "2026-10-18"},
                },
            ),
            event(
                "candidatures.sending_confirmed",
                {"sent_on": "2026-10-04", "channel": "linkedin"},
            ),
            event("candidatures.note_added", {"note_id": 5}),
            event("candidatures.note_removed", {"note_id": 5}),
            event("candidatures.change_cancelled", {"kind": "action_done"}),
        ],
        {5: "Appel de Julie"},
    )

    assert [(line.text, line.major) for line in lines] == [
        ("Annulé : « Fait »", True),
        ("Note retirée : « Appel de Julie »", True),
        ("Note : Appel de Julie", True),
        ("Envoi confirmé : le 04/10/2026 via LinkedIn", True),
        ("Fait : Relancer ; ensuite : Relancer le 18/10/2026", True),
        ("Prochaine action différée : Relancer le 14/10/2026", False),
        ("Étape : Prête à envoyer → Envoyée", True),
    ]


def test_an_event_by_a_rule_says_so_and_an_unknown_one_is_still_shown() -> None:
    lines = timeline(
        [
            event(
                "candidatures.stage_changed",
                {"from": "sent", "to": "rejected"},
                Actor.RULE,
            ),
            event("candidatures.something_new", {}),
        ],
        {},
    )

    assert (lines[0].text, lines[0].major) == (
        "Événement candidatures.something_new",
        False,
    )
    assert (lines[1].text, lines[1].by) == (
        "Étape : Envoyée → Refusée",
        "par une règle",
    )
