"""Append-only event journal: every decision and transition of Rocky is recorded here.

The database refuses UPDATE, DELETE and TRUNCATE on ``events`` (triggers of migration 0001).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

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
    func,
    insert,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from rocky.system.db import metadata

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)

MODULES = frozenset({"system", "profil", "offres", "candidatures", "messages"})
# "<module>.<fact_in_past_tense>", e.g. "offres.decision_recorded".
EVENT_TYPE = re.compile(r"^(?P<module>[a-z]+)\.[a-z][a-z0-9_]*$")


class Actor(StrEnum):
    USER = "user"
    RULE = "rule"
    AI = "ai"
    SYSTEM = "system"


@dataclass(frozen=True)
class NewEvent:
    """An event to append; validated on creation, before any SQL."""

    type: str
    actor: Actor
    subject_type: str | None = None
    subject_id: str | None = None
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    account_id: int | None = None

    def __post_init__(self) -> None:
        match = EVENT_TYPE.match(self.type)
        if match is None:
            raise ValueError(
                f"event type {self.type!r} is not of the form '<module>.<fact>'"
            )
        if match["module"] not in MODULES:
            raise ValueError(f"event type {self.type!r} names an unknown module")
        if (self.subject_type is None) != (self.subject_id is None):
            raise ValueError("an event subject needs both subject_type and subject_id")
        if self.subject_type == "" or self.subject_id == "":
            raise ValueError("an event subject cannot be empty")


events = Table(
    "events",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("type", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("subject_type", Text),
    Column("subject_id", Text),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    # The account concerned; None for events of Rocky itself. Never cascades: the journal keeps all.
    Column("account_id", BigInteger, ForeignKey("accounts.id")),
    CheckConstraint(
        "actor IN ({})".format(", ".join(f"'{actor.value}'" for actor in Actor)),
        name="actor",
    ),
    CheckConstraint(
        "(subject_type IS NULL) = (subject_id IS NULL)", name="subject_complete"
    ),
    Index("ix_events_subject", "subject_type", "subject_id", "id"),
    Index("ix_events_account_id", "account_id"),
)


def append_event(connection: Connection, event: NewEvent) -> int:
    """Append ``event`` in the caller's transaction and return its id.

    Never begins nor commits: the event is written together with the change it describes.
    """
    statement = (
        insert(events)
        .values(
            type=event.type,
            actor=event.actor.value,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            payload=dict(event.payload),
            account_id=event.account_id,
        )
        .returning(events.c.id)
    )
    return int(connection.execute(statement).scalar_one())
