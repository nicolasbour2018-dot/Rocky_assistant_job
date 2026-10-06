"""The conversations with the assistant (decision G4, Q3, Q10, Q20): one general per account and one per object, each
turn with its question, the answer shown, the facts cited, the model's raw answer and its call.

Turns are only added (Q3: kept whole, training data); the deletion of an account's conversations, before the beta, is
noted in the plan (§8, Q22).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Table,
    Text,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB

from rocky.system.assistant.model import (
    AnswerOutcome,
    Exchange,
    Fact,
    Subject,
    SubjectKind,
)
from rocky.system.db import metadata


def _in(column: str, values: type[SubjectKind | AnswerOutcome]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


assistant_conversations = Table(
    "assistant_conversations",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    # Both empty: the general conversation (Q20). No foreign key: the object is read through its module.
    Column("subject_kind", Text),
    Column("subject_id", BigInteger),
    Column("started_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"subject_kind IS NULL OR {_in('subject_kind', SubjectKind)}",
        name="subject_kind",
    ),
    CheckConstraint(
        "(subject_kind IS NULL) = (subject_id IS NULL)", name="subject_complete"
    ),
    Index(
        "ix_assistant_conversations_account_id_subject_kind",
        "account_id",
        "subject_kind",
        "subject_id",
        "id",
    ),
)

assistant_turns = Table(
    "assistant_turns",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "conversation_id",
        BigInteger,
        ForeignKey("assistant_conversations.id"),
        nullable=False,
    ),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("asked_at", DateTime(timezone=True), nullable=False),
    Column("question", Text, nullable=False),
    # What the screen showed: the model's answer, or the replacement of a rejected one (Q12).
    Column("answer", Text, nullable=False),
    # The facts cited, as shown: [{"id", "label", "link"}].
    Column("cited", JSONB, nullable=False),
    Column("raw_answer", JSONB),
    Column("outcome", Text, nullable=False),
    Column("model_call_id", BigInteger, ForeignKey("model_calls.id"), nullable=False),
    CheckConstraint(_in("outcome", AnswerOutcome), name="outcome"),
    CheckConstraint("length(question) > 0", name="question_given"),
    Index("ix_assistant_turns_conversation_id", "conversation_id", "id"),
)


@dataclass(frozen=True)
class CitedFact:
    label: str
    link: str | None


@dataclass(frozen=True)
class TurnRecord:
    question: str
    answer: str
    cited: tuple[CitedFact, ...]
    outcome: AnswerOutcome
    asked_at: datetime

    @property
    def exchange(self) -> Exchange:
        return Exchange(self.question, self.answer)


class AssistantStore:
    """The SQL of the conversations, on the caller's connection and transaction."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def current(self, account_id: int, subject: Subject | None) -> int | None:
        """The conversation in progress about ``subject`` (the latest started), None before the first question."""
        query = select(assistant_conversations.c.id).where(
            assistant_conversations.c.account_id == account_id
        )
        if subject is None:
            query = query.where(assistant_conversations.c.subject_kind.is_(None))
        else:
            query = query.where(
                assistant_conversations.c.subject_kind == subject.kind,
                assistant_conversations.c.subject_id == subject.id,
            )
        found: int | None = self._conn.execute(
            query.order_by(assistant_conversations.c.id.desc()).limit(1)
        ).scalar_one_or_none()
        return found

    def start(self, account_id: int, subject: Subject | None, now: datetime) -> int:
        """A new conversation about ``subject``: the previous ones are kept, no longer sent (Q20)."""
        conversation_id: int = self._conn.execute(
            insert(assistant_conversations)
            .values(
                account_id=account_id,
                subject_kind=None if subject is None else subject.kind,
                subject_id=None if subject is None else subject.id,
                started_at=now,
            )
            .returning(assistant_conversations.c.id)
        ).scalar_one()
        return conversation_id

    def turns(self, conversation_id: int) -> list[TurnRecord]:
        rows = self._conn.execute(
            select(assistant_turns)
            .where(assistant_turns.c.conversation_id == conversation_id)
            .order_by(assistant_turns.c.id)
        ).all()
        return [
            TurnRecord(
                row.question,
                row.answer,
                tuple(CitedFact(one["label"], one.get("link")) for one in row.cited),
                AnswerOutcome(row.outcome),
                row.asked_at,
            )
            for row in rows
        ]

    def add_turn(
        self,
        *,
        conversation_id: int,
        account_id: int,
        asked_at: datetime,
        question: str,
        answer: str,
        cited: Sequence[Fact],
        raw_answer: Any,
        outcome: AnswerOutcome,
        model_call_id: int,
    ) -> None:
        self._conn.execute(
            insert(assistant_turns).values(
                conversation_id=conversation_id,
                account_id=account_id,
                asked_at=asked_at,
                question=question,
                answer=answer,
                cited=[
                    {"id": fact.id, "label": fact.label, "link": fact.link}
                    for fact in cited
                ],
                raw_answer=raw_answer,
                outcome=outcome,
                model_call_id=model_call_id,
            )
        )
