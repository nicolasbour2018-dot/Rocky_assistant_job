"""What the assistant 🐾 knows of the messages (decision G4, Q11, Q31): the message whose « Corriger » panel is open,
and the messages attached to an application. Never the body of a message: its sender, subject, date, classification
and the excerpt that justifies it.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request

from rocky.messages.classification.model import (
    CATEGORY_LABELS,
    LEVEL_LABELS,
    SortedMessage,
    StoredDecision,
)
from rocky.messages.service import CorrectionView, MessagesService
from rocky.system.assistant.model import Fact, FactSheet, SubjectKind
from rocky.system.assistant.registry import add_facts
from rocky.system.auth.model import Account
from rocky.system.clock import paris_day

SUGGESTIONS = (
    "Qu'est-ce que ce message change pour moi ?",
    "À quelle candidature se rattache-t-il ?",
)
# The messages of an application given with its dossier.
APPLICATION_MESSAGES = 10
LINK = "/messages"


def install(app: FastAPI) -> None:
    add_facts(app, SubjectKind.MESSAGE, _sheet)
    add_facts(app, SubjectKind.APPLICATION, _application_messages)


def _service(request: Request) -> MessagesService:
    service: MessagesService = request.app.state.messages
    return service


def _sheet(request: Request, account: Account, message_id: int) -> FactSheet | None:
    try:
        view = _service(request).correction(account.id, message_id)
    except LookupError:
        return None
    return message_sheet(view)


def classification(decision: StoredDecision | None) -> str:
    if decision is None:
        return "pas encore classé"
    if decision.category is None:
        return f"aucune catégorie ({LEVEL_LABELS[decision.level].lower()})"
    return (
        f"{CATEGORY_LABELS[decision.category]} ({LEVEL_LABELS[decision.level].lower()})"
    )


def message_sheet(view: CorrectionView) -> FactSheet:
    """The facts of the message of ``view``, pure."""
    message, decision = view.message, view.decision
    facts = [
        Fact("message.expediteur", "Expéditeur", message.sender, LINK),
        Fact("message.objet", "Objet", message.subject, LINK),
        Fact(
            "message.date",
            "Reçu le",
            f"{paris_day(message.received_at):%d/%m/%Y}",
            LINK,
        ),
        Fact(
            "message.classement", "Classement de Rocky", classification(decision), LINK
        ),
    ]
    if decision is not None and decision.proofs:
        facts.append(
            Fact(
                "message.justification",
                "Ce qui justifie le classement",
                " ; ".join(
                    f"« {proof.excerpt} » ({proof.reason})" for proof in decision.proofs
                ),
                LINK,
            )
        )
    if decision is not None and decision.application_id is not None:
        label = view.applications.get(decision.application_id, "une candidature fermée")
        facts.append(
            Fact(
                "message.candidature",
                "Candidature liée",
                label,
                f"/candidatures/{decision.application_id}",
            )
        )
    if view.title:
        facts.append(
            Fact("message.intitule", "Intitulé cité par le message", view.title, LINK)
        )
    return FactSheet(f"Message de {message.sender}", tuple(facts), LINK, SUGGESTIONS)


def _application_messages(
    request: Request, account: Account, application_id: int
) -> FactSheet | None:
    messages = _service(request).application_messages(account.id, application_id)
    if not messages:
        return None
    return FactSheet("", application_facts(messages[:APPLICATION_MESSAGES]))


def application_facts(messages: Sequence[SortedMessage]) -> tuple[Fact, ...]:
    """The messages attached to an application, the latest first."""
    facts = []
    for index, message in enumerate(messages, start=1):
        text = (
            f"reçu le {paris_day(message.received_at):%d/%m/%Y} de {message.sender}, "
            f"« {message.subject} » : {classification(message.decision)}"
        )
        if message.decision is not None and message.decision.proofs:
            text += f" ; extrait : « {message.decision.proofs[0].excerpt} »"
        facts.append(Fact(f"candidature.message_{index}", "Message lié", text, LINK))
    return tuple(facts)
