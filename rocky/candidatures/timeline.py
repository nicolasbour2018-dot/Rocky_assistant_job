"""The chronology of an application (decision D6, Q7): its journal in French, the major facts first.

Pure functions: the events come from ``system.events.events_about``, the notes from the application's store. Every
type the use cases write has its line here (a test checks it); a type unknown to this table is still shown, as is.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime

from rocky.candidatures.model import (
    CHANNEL_LABELS,
    LANGUAGE_LABELS,
    STAGE_LABELS,
    ChangeKind,
    Channel,
    Stage,
)
from rocky.system.events import Actor, JsonValue, StoredEvent


@dataclass(frozen=True)
class Line:
    """One line of the chronology. ``major``: shown at once; the others under « Tout afficher »."""

    at: datetime
    text: str
    major: bool
    by: str | None = None  # who made it, when not the user


type Payload = Mapping[str, JsonValue]

_CANCELLED = {
    ChangeKind.CREATED.value: "l'ouverture de la candidature",
    ChangeKind.STAGE.value: "le changement d'étape",
    ChangeKind.NEXT_ACTION.value: "le changement de prochaine action",
    ChangeKind.ACTION_DONE.value: "« Fait »",
}
_BY = {Actor.RULE: "par une règle", Actor.AI: "par l'IA", Actor.SYSTEM: "par Rocky"}


def _day(value: JsonValue) -> str:
    return date.fromisoformat(str(value)).strftime("%d/%m/%Y")


def _stage(value: JsonValue) -> str:
    return STAGE_LABELS[Stage(str(value))] if value in set(Stage) else str(value)


def _action(value: JsonValue) -> str | None:
    """« Relancer le 11/10/2026 » from a payload's action, None without one."""
    if not isinstance(value, dict):
        return None
    return f"{value.get('label')} le {_day(value.get('due'))}"


def _language(value: JsonValue) -> str:
    return LANGUAGE_LABELS.get(str(value), str(value)).lower()


def _created(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return "Candidature ouverte (En préparation)", True


def _stage_changed(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return f"Étape : {_stage(payload.get('from'))} → {_stage(payload.get('to'))}", True


def _next_action_set(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    action = _action(payload.get("next_action"))
    if action is None:
        return "Prochaine action effacée", False
    if payload.get("deferred_days"):
        return f"Prochaine action différée : {action}", False
    return f"Prochaine action : {action}", False


def _action_done(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    done = payload.get("done")
    label = done.get("label") if isinstance(done, dict) else None
    following = _action(payload.get("next_action"))
    text = f"Fait : {label}"
    return (f"{text} ; ensuite : {following}" if following else text), True


def _cancelled(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    what = _CANCELLED.get(str(payload.get("kind")), "un changement")
    return f"Annulé : {what}", True


def _cv(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    if payload.get("after") is None:
        return "CV revenu à la proposition de Rocky", False
    return "Sélection du CV ajustée", False


def _letter(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return f"Lettre validée ({_language(payload.get('language'))})", True


def _no_letter(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return "Pas de lettre pour cette candidature", True


def _message(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return (
        f"Message d'accompagnement validé ({_language(payload.get('language'))})",
        False,
    )


def _revisions(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    found = payload.get("revisions")
    revisions = found if isinstance(found, list) else []
    kinds = [
        "CV" if item.get("kind") == "cv" else "lettre"
        for item in revisions
        if isinstance(item, dict)
    ]
    language = next(
        (item.get("language") for item in revisions if isinstance(item, dict)), None
    )
    what = " et ".join(kinds) or "documents"
    return f"PDF à envoyer générés : {what} ({_language(language)})", True


def _sent(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    channel = str(payload.get("channel"))
    label = CHANNEL_LABELS[Channel(channel)] if channel in set(Channel) else channel
    return f"Envoi confirmé : le {_day(payload.get('sent_on'))} via {label}", True


def _prefilled(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return f"Formulaire prérempli ({payload.get('domain')})", True


def _note_text(payload: Payload, notes: Mapping[int, str]) -> str:
    note_id = payload.get("note_id")
    return notes.get(note_id, "") if isinstance(note_id, int) else ""


def _note_added(payload: Payload, notes: Mapping[int, str]) -> tuple[str, bool]:
    return f"Note : {_note_text(payload, notes)}", True


def _note_removed(payload: Payload, notes: Mapping[int, str]) -> tuple[str, bool]:
    return f"Note retirée : « {_note_text(payload, notes)} »", True


def _language_chosen(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    return f"Langue de la candidature : {_language(payload.get('language'))}", False


def _employer_domain_set(payload: Payload, _: Mapping[int, str]) -> tuple[str, bool]:
    domain = payload.get("domain")
    if not domain:
        return "Domaine e-mail de l'employeur retiré", False
    return f"Domaine e-mail de l'employeur : {domain}", False


LINES: dict[str, Callable[[Payload, Mapping[int, str]], tuple[str, bool]]] = {
    "candidatures.application_created": _created,
    "candidatures.stage_changed": _stage_changed,
    "candidatures.next_action_set": _next_action_set,
    "candidatures.action_done": _action_done,
    "candidatures.change_cancelled": _cancelled,
    "candidatures.cv_selection_changed": _cv,
    "candidatures.letter_validated": _letter,
    "candidatures.letter_skipped": _no_letter,
    "candidatures.message_validated": _message,
    "candidatures.revisions_generated": _revisions,
    "candidatures.sending_confirmed": _sent,
    "candidatures.prefilled": _prefilled,
    "candidatures.note_added": _note_added,
    "candidatures.note_removed": _note_removed,
    "candidatures.language_chosen": _language_chosen,
    "candidatures.employer_domain_set": _employer_domain_set,
}


def timeline(events: Iterable[StoredEvent], notes: Mapping[int, str]) -> list[Line]:
    """The lines of the chronology, the latest first. ``notes``: the text of every note of the application, removed
    ones included (a removal shows what it removed)."""
    lines = []
    for event in events:
        line = LINES.get(event.type)
        text, major = (
            (f"Événement {event.type}", False)
            if line is None
            else line(event.payload, notes)
        )
        lines.append(Line(event.occurred_at, text, major, _BY.get(event.actor)))
    return lines[::-1]
