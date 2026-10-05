"""Use cases of the classification: decide the messages of an account that have no decision, or classify them again.

Decision ``docs/decisions/E2-classification.md``. The rules decide first; a message they leave to the language model
waits for a call, within the limits of the account (Q18). Each decision is written alone in its transaction with its
event, the message's row held; the network is never used inside a transaction. A call that gives no answer writes no
decision: the message waits for the next pass, and no other call is made in this one (Q12).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rocky.messages.classification.llm import (
    INSTRUCTIONS,
    SCHEMA,
    checked,
    prompt,
)
from rocky.messages.classification.model import (
    CLASSIFY_VERSION,
    CallOutcome,
    ClassificationStorage,
    ClassificationStore,
    Context,
    Limits,
    MailToClassify,
    Pending,
    Targets,
    Verdict,
)
from rocky.messages.classification.rules import classify
from rocky.offres.decisions import Author
from rocky.system.events import Actor, NewEvent
from rocky.system.llm import JsonModel, LlmUnavailableError

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]

DEFAULT_LIMITS = Limits()
# Messages read at once; a pass reads every batch, the model being bounded by the limits.
BATCH = 500
NOT_CONFIGURED_REASON = "Le modèle de langage n'est pas configuré (clé Gemini absente)."
HOUR_LIMIT_REASON = (
    "Plafond d'appels au modèle atteint pour l'heure : la suite au prochain passage."
)
DAY_LIMIT_REASON = (
    "Plafond d'appels au modèle atteint pour la journée : la suite demain."
)
RUN_LIMIT_REASON = "Limite d'appels de ce passage atteinte."
WITHOUT_MODEL_REASON = "Classement sans le modèle de langage (règles seules)."


class ClassifyBusyError(Exception):
    """The messages of this account are being classified elsewhere."""


@dataclass
class ClassifyReport:
    """What a pass did: decisions by the rules and by the model, calls made, messages still waiting and why."""

    by_rules: int = 0
    by_model: int = 0
    refused: int = 0
    calls: int = 0
    waiting: int = 0
    reason: str | None = None
    decided: list[int] = field(default_factory=list)


def classify_messages(
    storage: ClassificationStorage,
    *,
    account_id: int,
    targets: Targets,
    model: JsonModel | None,
    clock: Clock,
    limits: Limits = DEFAULT_LIMITS,
    max_calls: int | None = None,
    again: bool = False,
    no_model_reason: str = WITHOUT_MODEL_REASON,
    only: Sequence[int] | None = None,
) -> ClassifyReport:
    """The messages of the account without a decision (``again``: all of them, never over a user's decision, Q13).

    ``model`` None: the rules only, the others waiting for ``no_model_reason``. ``max_calls`` bounds the calls of this
    pass under the account's limits. ``only``: these messages alone (decision E4: those of a sender the user made a
    rule for, or citing an employer whose application was just created). Raises ``ClassifyBusyError``.
    """
    with storage.classify_lock(account_id) as locked:
        if not locked:
            raise ClassifyBusyError(account_id)
        with storage.transaction() as store:
            threads = store.attached_threads(account_id)
            rules = store.sender_rules(account_id)
        context = Context(tuple(targets(account_id)), threads, rules)
        report = ClassifyReport()
        waiting: list[tuple[MailToClassify, Pending]] = []
        after = 0
        while batch := _batch(storage, account_id, after, again=again, only=only):
            after = batch[-1].id
            for message in batch:
                found = classify(message, context)
                if isinstance(found, Pending):
                    waiting.append((message, found))
                elif _write(
                    storage, account_id, message, found, again=again, now=clock()
                ):
                    report.by_rules += 1
                    report.decided.append(message.id)
                    _follow_thread(context, message, found)
        waiting.sort(key=lambda item: item[0].received_at, reverse=True)
        _ask_model(
            storage,
            report,
            waiting,
            context,
            account_id=account_id,
            model=model,
            clock=clock,
            limits=limits,
            max_calls=max_calls,
            again=again,
            no_model_reason=no_model_reason,
        )
        return report


def _batch(
    storage: ClassificationStorage,
    account_id: int,
    after: int,
    *,
    again: bool,
    only: Sequence[int] | None,
) -> list[MailToClassify]:
    """The next messages to classify, in the order they were collected (the rules are cheap: every batch is read)."""
    with storage.transaction() as store:
        if only is not None:
            wanted = sorted(message_id for message_id in only if message_id > after)
            return store.messages_among(account_id, wanted[:BATCH])
        if again:
            return store.messages_of(account_id, after, BATCH)
        return store.undecided(account_id, after, BATCH)


def _ask_model(
    storage: ClassificationStorage,
    report: ClassifyReport,
    waiting: list[tuple[MailToClassify, Pending]],
    context: Context,
    *,
    account_id: int,
    model: JsonModel | None,
    clock: Clock,
    limits: Limits,
    max_calls: int | None,
    again: bool,
    no_model_reason: str,
) -> None:
    """Q12, Q18: the newest waiting messages first, while the limits allow; the first failure ends the pass."""
    for index, (message, pending) in enumerate(waiting):
        reason = (
            no_model_reason
            if model is None
            else _stop_reason(storage, account_id, clock, limits, report, max_calls)
        )
        if reason is not None or model is None:
            report.waiting = len(waiting) - index
            report.reason = reason
            return
        started = time.monotonic()
        try:
            answer = model.complete_json(INSTRUCTIONS, prompt(message, pending), SCHEMA)
        except LlmUnavailableError as error:
            with storage.transaction() as store:
                store.add_call(
                    account_id,
                    message.id,
                    outcome=CallOutcome.FAILED,
                    reason=error.reason,
                    duration_ms=_since(started),
                    now=clock(),
                )
            report.calls += 1
            report.waiting = len(waiting) - index
            report.reason = error.reason
            return
        result = checked(answer, message, pending)
        outcome = CallOutcome.ACCEPTED if result.accepted else CallOutcome.REFUSED
        report.calls += 1
        if _write(
            storage,
            account_id,
            message,
            result.verdict,
            again=again,
            now=clock(),
            call=(outcome, _since(started)),
        ):
            report.by_model += 1
            report.refused += 0 if result.accepted else 1
            report.decided.append(message.id)
            _follow_thread(context, message, result.verdict)
    report.waiting = 0


def _stop_reason(
    storage: ClassificationStorage,
    account_id: int,
    clock: Clock,
    limits: Limits,
    report: ClassifyReport,
    max_calls: int | None,
) -> str | None:
    if max_calls is not None and report.calls >= max_calls:
        return RUN_LIMIT_REASON
    now = clock()
    with storage.transaction() as store:
        last_hour = store.calls_since(account_id, now - timedelta(hours=1))
        last_day = store.calls_since(account_id, now - timedelta(days=1))
    if last_day >= limits.per_day:
        return DAY_LIMIT_REASON
    if last_hour >= limits.per_hour:
        return HOUR_LIMIT_REASON
    return None


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _write(
    storage: ClassificationStorage,
    account_id: int,
    message: MailToClassify,
    verdict: Verdict,
    *,
    again: bool,
    now: datetime,
    call: tuple[CallOutcome, int] | None = None,
) -> bool:
    """The decision, its event and the call that gave it, in one transaction. False when the message got a decision
    meanwhile (or, classified again, when the user decided it)."""
    with storage.transaction() as store:
        if call is not None:
            outcome, duration_ms = call
            store.add_call(
                account_id,
                message.id,
                outcome=outcome,
                reason=None,
                duration_ms=duration_ms,
                now=now,
            )
        store.lock_message(message.id)
        if _already_decided(store, message.id, again=again):
            return False
        decision_id = store.add_decision(account_id, message.id, verdict, now)
        store.append_event(
            NewEvent(
                type="messages.message_classified",
                actor=Actor(verdict.author.value),
                subject_type="email_message",
                subject_id=str(message.id),
                payload={
                    "decision_id": decision_id,
                    "category": None
                    if verdict.category is None
                    else verdict.category.value,
                    "application_id": verdict.application_id,
                    "level": verdict.level.value,
                    "rule": verdict.proofs[0].rule,
                    "version": CLASSIFY_VERSION,
                },
                account_id=account_id,
            )
        )
        store.follow(account_id, message, decision_id, verdict, now)
    return True


def _already_decided(
    store: ClassificationStore, message_id: int, *, again: bool
) -> bool:
    if again:
        return store.current_author(message_id) is Author.USER
    return store.has_decision(message_id)


def _follow_thread(context: Context, message: MailToClassify, verdict: Verdict) -> None:
    """A message attached in this pass lends its application to the next ones of its thread."""
    if verdict.application_id is not None:
        context.threads.setdefault(
            (message.mailbox_id, message.thread_id), verdict.application_id
        )
