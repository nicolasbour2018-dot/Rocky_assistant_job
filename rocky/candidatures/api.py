"""What ``candidatures`` gives the other modules (the messages, decisions E2 and E4): on the caller's connection and
inside its transaction, they never read the tables of the applications themselves. No route here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Connection

from rocky.candidatures.model import MailTarget, Stage
from rocky.candidatures.rules import dossier, standing
from rocky.candidatures.sql import SqlApplicationStore
from rocky.candidatures.usecases import (
    cancel_change_if_last,
    move_by_message,
    record_outside_application,
    set_employer_domain,
)
from rocky.offres import api as offres_api
from rocky.offres.decisions import Author, Decision, DecisionValue


class OffresDecisions:
    """``OfferDecisions`` on the public functions of ``offres``, in the caller's transaction (the functions below and
    the routes of the applications)."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def decision_in_force(self, account_id: int, offer_id: int) -> DecisionValue | None:
        return offres_api.decision_in_force(self._conn, account_id, offer_id)

    def record_interested(
        self, account_id: int, offer_id: int, decision: Decision, now: datetime
    ) -> int:
        return offres_api.record_application_decision(
            self._conn,
            account_id=account_id,
            offer_id=offer_id,
            decision=decision,
            now=now,
        )

    def cancel(self, account_id: int, decision_id: int, now: datetime) -> bool:
        return offres_api.cancel_application_decision(
            self._conn, account_id=account_id, decision_id=decision_id, now=now
        )


# The stages a received message may concern (decision E2, Q11): from « Préremplie » on, the outcomes included.
MAIL_STAGES = frozenset(
    {
        Stage.PREFILLED,
        Stage.SENT,
        Stage.IN_DISCUSSION,
        Stage.INTERVIEW,
        Stage.OFFER,
        Stage.REJECTED,
        Stage.WITHDRAWN,
        Stage.NO_RESPONSE,
    }
)


def mail_targets(connection: Connection, account_id: int) -> list[MailTarget]:
    """For the module ``messages`` (decision E2, Q3, Q11), on the caller's connection: the applications of the account
    a received message may concern, with what recognises their employer."""
    store = SqlApplicationStore(connection)
    found = [
        (application, state.stage)
        for application, changes in store.applications_of(account_id)
        if (state := dossier(changes)).stage in MAIL_STAGES
    ]
    headings = offres_api.offer_headings(
        connection, account_id, [application.offer_id for application, _ in found]
    )
    targets: list[MailTarget] = []
    for application, stage in found:
        heading = headings.get(application.offer_id)
        if heading is None or stage is None:
            continue
        sendings = store.sendings(application.id)
        targets.append(
            MailTarget(
                application_id=application.id,
                company=heading.company or "",
                title=heading.title,
                stage=stage,
                sent_on=sendings[-1].sent_on if sendings else None,
                employer_domain=store.employer_domain(application.id),
                links=tuple(
                    link for link in (heading.url, heading.application_url) if link
                ),
            )
        )
    return targets


def application_labels(
    connection: Connection, account_id: int, application_ids: Iterable[int]
) -> dict[int, str]:
    """« Employeur — intitulé » of the account's applications among ``application_ids`` (the module ``messages``)."""
    wanted = set(application_ids)
    if not wanted:
        return {}
    found = [
        application
        for application, _ in SqlApplicationStore(connection).applications_of(
            account_id
        )
        if application.id in wanted
    ]
    headings = offres_api.offer_headings(
        connection, account_id, [application.offer_id for application in found]
    )
    return {
        application.id: " — ".join(
            part for part in (heading.company, heading.title) if part
        )
        for application in found
        if (heading := headings.get(application.offer_id)) is not None
    }


def open_application_labels(connection: Connection, account_id: int) -> dict[int, str]:
    """« Employeur — intitulé » of every open application of the account (decision E4: the applications a correction
    may attach a message to)."""
    opened = [
        application.id
        for application, changes in SqlApplicationStore(connection).applications_of(
            account_id
        )
        if dossier(changes).open
    ]
    return application_labels(connection, account_id, opened)


# For the module ``messages`` (decision E4), on the caller's connection and inside its transaction: the transitions a
# received message gives, written with the decision about the message, or not at all.


def mail_stage(
    connection: Connection, account_id: int, application_id: int
) -> Stage | None:
    """The stage of an open application of the account, its row held until the end of the transaction; None for a
    cancelled application or one of another account."""
    store = SqlApplicationStore(connection)
    application = store.locked_application(account_id, application_id)
    if application is None:
        return None
    state = dossier(store.changes(application.id))
    return state.stage if state.open else None


def change_in_force(
    connection: Connection, account_id: int, application_id: int, change_id: int
) -> bool:
    """The change is still in force: neither cancelled nor a cancellation (Q3: what a correction may undo)."""
    store = SqlApplicationStore(connection)
    application = store.locked_application(account_id, application_id)
    if application is None:
        return False
    return any(
        change.id == change_id for change in standing(store.changes(application.id))
    )


def move_application_by_message(
    connection: Connection,
    *,
    account_id: int,
    application_id: int,
    stage: Stage,
    author: Author,
    message_id: int,
    now: datetime,
    today: date,
) -> int | None:
    """The transition a message gave (Q1: by a rule; or applied by the user): the change's id, None when already at
    ``stage``. Raises ``InvalidChangeError`` for a transition a rule may not make."""
    return move_by_message(
        SqlApplicationStore(connection),
        account_id=account_id,
        application_id=application_id,
        stage=stage,
        author=author,
        message_id=message_id,
        now=now,
        today=today,
    )


def cancel_message_change(
    connection: Connection,
    *,
    account_id: int,
    application_id: int,
    change_id: int,
    now: datetime,
) -> bool:
    """Undo the transition a message gave while it is the application's latest change (Q3); False otherwise."""
    return cancel_change_if_last(
        SqlApplicationStore(connection),
        OffresDecisions(connection),
        account_id=account_id,
        application_id=application_id,
        change_id=change_id,
        now=now,
    )


def learn_employer_domain(
    connection: Connection,
    *,
    account_id: int,
    application_id: int,
    domain: str,
    now: datetime,
) -> bool:
    """« Retenir le domaine » after a correction (Q7): the employer's e-mail domain of the application."""
    return set_employer_domain(
        SqlApplicationStore(connection),
        account_id=account_id,
        application_id=application_id,
        typed=domain,
        now=now,
    )


def open_outside_application(
    connection: Connection,
    *,
    account_id: int,
    offer_id: int,
    sent_on: date,
    now: datetime,
) -> int:
    """« Créer la candidature » from a message (Q4): the application made outside Rocky, at « Envoyée »."""
    return record_outside_application(
        SqlApplicationStore(connection),
        OffresDecisions(connection),
        account_id=account_id,
        offer_id=offer_id,
        sent_on=sent_on,
        now=now,
    )
