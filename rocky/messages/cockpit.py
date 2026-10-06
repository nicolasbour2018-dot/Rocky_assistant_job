"""What 📬 Messages gives 🧭 Cockpit (decision G3): a mailbox to reconnect above the hero (Q4), the state of the
mailboxes (Q13), the lines of the feed (Q16: what moved, what to check, the alerts read, the messages sorted; the
gestures stay in 📬, decision F1, Q7) and the sentence of an answer (Q3).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from fastapi import FastAPI, Request

from rocky.candidatures.model import STAGE_LABELS, Stage
from rocky.messages.alerts.model import PLATFORM_LABELS, Platform
from rocky.messages.classification.model import View
from rocky.messages.decisions.model import Moved, Outcome
from rocky.messages.model import MailboxStatus, SyncStatus
from rocky.messages.service import Attention, MailboxView, MessagesService
from rocky.system.auth.model import Account
from rocky.system.clock import paris_day, paris_time
from rocky.system.cockpit import FeedLine, Parts, Sentence, Status, add_cockpit
from rocky.system.events import StoredEvent, events_of
from rocky.system.shell import Action, Card

CONNECT = Action("Connecter une boîte Gmail", "/messages/gmail/connecter", post=True)
RECONNECT = Action("Reconnecter la boîte", "/messages/gmail/connecter", post=True)
SEE_MESSAGES = Action("Voir dans Messages", "/messages")
# An answer of a person (decision F1, Q9): the sentence of the day says it first.
ANSWERS = frozenset({Stage.IN_DISCUSSION, Stage.INTERVIEW, Stage.OFFER})


def install(app: FastAPI) -> None:
    add_cockpit(
        app,
        "messages",
        Parts(problems=_problems, status=_status, feed=_feed, sentences=_sentences),
    )


def _service(request: Request) -> MessagesService:
    service: MessagesService = request.app.state.messages
    return service


def _attention(request: Request, account: Account) -> Attention:
    cached: Attention | None = getattr(request.state, "cockpit_attention", None)
    if cached is None:
        cached = _service(request).attention(account.id)
        request.state.cockpit_attention = cached
    return cached


def _views(request: Request, account: Account) -> list[MailboxView]:
    service = _service(request)
    return service.mailbox_views(account.id) if service.configured else []


def lost_cards(views: Sequence[MailboxView]) -> list[Card]:
    """A mailbox whose access was lost: a problem above the hero, with the gesture that reconnects it."""
    lost = [
        v.mailbox.address
        for v in views
        if v.mailbox.status is MailboxStatus.ACCESS_LOST
    ]
    if not lost:
        return []
    return [
        Card(
            "📬 Boîte Gmail à reconnecter",
            (
                f"Rocky n'a plus accès à {', '.join(lost)} : ni réponses ni alertes ne sont lues.",
            ),
            action=RECONNECT,
            problem=True,
        )
    ]


def _problems(request: Request, account: Account) -> list[Card]:
    return lost_cards(_views(request, account))


def mailbox_status(views: Sequence[MailboxView], *, configured: bool) -> list[Status]:
    if not configured:
        return []
    shown = [v for v in views if v.mailbox.status is not MailboxStatus.DISCONNECTED]
    if not shown:
        return [Status("Aucune boîte Gmail connectée.", CONNECT)]
    running = any(
        v.last is not None and v.last.status is SyncStatus.RUNNING for v in shown
    )
    failed = any(
        v.mailbox.status is MailboxStatus.ACCESS_LOST
        or (v.last is not None and v.last.status is SyncStatus.FAILED)
        for v in shown
    )
    last = max((v.last.started_at for v in shown if v.last is not None), default=None)
    count = len(shown)
    boxes = f"{count} boîte{'s' if count > 1 else ''} Gmail"
    if running:
        text = f"{boxes} : relevé en cours."
    elif last is None:
        text = f"{boxes}, jamais relevée{'s' if count > 1 else ''}."
    else:
        text = f"{boxes}, dernier relevé le {paris_time(last)}."
    return [Status(text, problem=failed)]


def _status(request: Request, account: Account) -> list[Status]:
    return mailbox_status(
        _views(request, account), configured=_service(request).configured
    )


def move_text(line: Moved, label: str) -> str:
    transition = line.transition
    text = f"{label} : {STAGE_LABELS[transition.from_stage]} → {STAGE_LABELS[transition.to_stage]}"
    return text + (" (proposé)." if transition.outcome is Outcome.PROPOSED else ".")


def attention_lines(attention: Attention, at: datetime) -> list[FeedLine]:
    """What moved (one line each, at its time) and the decisions to check (a state)."""
    lines = [
        FeedLine(
            line.transition.created_at,
            move_text(
                line,
                attention.applications.get(
                    line.transition.application_id, "Candidature"
                ),
            ),
            SEE_MESSAGES,
        )
        for line in attention.moved
    ]
    if attention.to_check:
        count = attention.to_check
        s = "s" if count > 1 else ""
        lines.append(
            FeedLine(
                at,
                f"{count} message{s} à vérifier : Rocky n'est pas sûr de son classement.",
                Action("Vérifier", f"/messages?vue={View.TO_CHECK.value}"),
                standing=True,
            )
        )
    return lines


def _count(value: object) -> int:
    return value if isinstance(value, int) else 0


def journal_lines(found: Sequence[StoredEvent]) -> list[FeedLine]:
    """The alerts read and the messages sorted, a line a day each (Q16), at the time of the last one."""
    lines: list[FeedLine] = []
    alerts: dict[date, list[StoredEvent]] = {}
    sorted_: dict[date, list[StoredEvent]] = {}
    for event in found:
        target = alerts if event.type == "messages.alert_read" else sorted_
        target.setdefault(paris_day(event.occurred_at), []).append(event)
    for events in alerts.values():
        created = sum(_count(e.payload.get("created")) for e in events)
        platforms = sorted(
            {
                PLATFORM_LABELS[Platform(str(e.payload["platform"]))]
                for e in events
                if e.payload.get("platform") in set(Platform)
            }
        )
        count = len(events)
        text = f"{count} alerte{'s' if count > 1 else ''} lue{'s' if count > 1 else ''}"
        if platforms:
            text += f" ({', '.join(platforms)})"
        text += f" : {created} offre{'s' if created > 1 else ''} ajoutée{'s' if created > 1 else ''}."
        lines.append(FeedLine(max(e.occurred_at for e in events), text))
    for events in sorted_.values():
        count = len(events)
        lines.append(
            FeedLine(
                max(e.occurred_at for e in events),
                f"{count} message{'s' if count > 1 else ''} classé{'s' if count > 1 else ''}.",
            )
        )
    return lines


def _feed(request: Request, account: Account, since: datetime) -> list[FeedLine]:
    service = _service(request)
    with service.engine.connect() as connection:
        found = events_of(
            connection,
            account.id,
            ("messages.alert_read", "messages.message_classified"),
            since,
        )
    return [
        *attention_lines(_attention(request, account), since),
        *journal_lines(found),
    ]


def answer_sentences(attention: Attention) -> list[Sentence]:
    """The latest answer of a person that moved an application (Q3): said before anything else."""
    answers = [m for m in attention.moved if m.transition.to_stage in ANSWERS]
    if not answers:
        return []
    latest = max(answers, key=lambda m: m.transition.created_at)
    label = attention.applications.get(
        latest.transition.application_id, "Une candidature"
    )
    return [
        Sentence(
            80,
            f"Du nouveau pour {label} : {STAGE_LABELS[latest.transition.to_stage].lower()}.",
        )
    ]


def _sentences(request: Request, account: Account) -> list[Sentence]:
    return answer_sentences(_attention(request, account))
