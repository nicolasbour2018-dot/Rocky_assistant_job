"""SQL access of the applications: the only place where the tables of the module ``candidatures`` are queried.

Decision ``docs/decisions/D1-dossier-statuts.md``: the changes are appended, never changed; the stage and the next
action are computed from them (``rules.dossier``).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Row,
    Table,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rocky.candidatures.model import (
    Application,
    Change,
    ChangeKind,
    NewChange,
    NextAction,
    Stage,
)
from rocky.offres.decisions import Author
from rocky.system.db import metadata
from rocky.system.events import NewEvent, append_event


def _in(column: str, values: type[StrEnum]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


applications = Table(
    "applications",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("offer_id", BigInteger, ForeignKey("job_offers.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # One application per offer (Q7): opening it again reuses this row.
    UniqueConstraint("account_id", "offer_id"),
)

application_changes = Table(
    "application_changes",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("application_id", BigInteger, ForeignKey("applications.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    # Appended only (Q6): « Annuler » is a cancellation row that targets one change.
    Column("kind", Text, nullable=False),
    Column("stage", Text),
    Column("next_action_label", Text),
    Column("next_action_due", Date),
    Column("decision_id", BigInteger, ForeignKey("job_decisions.id")),
    Column("cancels_id", BigInteger, ForeignKey("application_changes.id")),
    Column("author", Text, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("cancels_id"),
    CheckConstraint(_in("kind", ChangeKind), name="kind"),
    CheckConstraint("stage IS NULL OR " + _in("stage", Stage), name="stage"),
    CheckConstraint(_in("author", Author), name="author"),
    CheckConstraint(
        "(kind IN ('created', 'stage')) = (stage IS NOT NULL)",
        name="stage_with_kind",
    ),
    CheckConstraint(
        "(kind = 'cancellation') = (cancels_id IS NOT NULL)",
        name="cancellation_has_target",
    ),
    CheckConstraint(
        "(next_action_label IS NULL) = (next_action_due IS NULL)",
        name="next_action_complete",
    ),
    CheckConstraint(
        "kind <> 'cancellation' OR next_action_label IS NULL",
        name="cancellation_alone",
    ),
    CheckConstraint(
        "decision_id IS NULL OR kind = 'created'", name="decision_on_creation"
    ),
    Index("ix_application_changes_application_id", "application_id", "id"),
)


class SqlApplicationStore:
    """``ApplicationStore`` on a connection, inside the caller's transaction; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def application_for_offer(
        self, account_id: int, offer_id: int, now: datetime
    ) -> Application:
        self._conn.execute(
            pg_insert(applications)
            .values(account_id=account_id, offer_id=offer_id, created_at=now)
            .on_conflict_do_nothing(index_elements=["account_id", "offer_id"])
        )
        row = self._conn.execute(
            select(applications)
            .where(
                applications.c.account_id == account_id,
                applications.c.offer_id == offer_id,
            )
            .with_for_update()
        ).one()
        return _application(row)

    def locked_application(
        self, account_id: int, application_id: int
    ) -> Application | None:
        row = self._conn.execute(
            select(applications)
            .where(
                applications.c.id == application_id,
                applications.c.account_id == account_id,
            )
            .with_for_update()
        ).one_or_none()
        return None if row is None else _application(row)

    def application_of_offer(
        self, account_id: int, offer_id: int
    ) -> Application | None:
        """The application of the offer, if any (read only, not locked)."""
        row = self._conn.execute(
            select(applications).where(
                applications.c.account_id == account_id,
                applications.c.offer_id == offer_id,
            )
        ).one_or_none()
        return None if row is None else _application(row)

    def changes(self, application_id: int) -> list[Change]:
        rows = self._conn.execute(
            select(application_changes)
            .where(application_changes.c.application_id == application_id)
            .order_by(application_changes.c.id)
        )
        return [_change(row) for row in rows]

    def applications_of(
        self, account_id: int
    ) -> list[tuple[Application, list[Change]]]:
        """Every application of the account with its changes (read only)."""
        found = [
            _application(row)
            for row in self._conn.execute(
                select(applications)
                .where(applications.c.account_id == account_id)
                .order_by(applications.c.id)
            )
        ]
        changes: dict[int, list[Change]] = {}
        for row in self._conn.execute(
            select(application_changes)
            .where(application_changes.c.account_id == account_id)
            .order_by(application_changes.c.id)
        ):
            changes.setdefault(row.application_id, []).append(_change(row))
        return [(found_one, changes.get(found_one.id, [])) for found_one in found]

    def insert_change(
        self,
        account_id: int,
        application_id: int,
        change: NewChange,
        *,
        author: Author,
        now: datetime,
    ) -> Change:
        action = change.next_action
        row = self._conn.execute(
            application_changes.insert()
            .values(
                application_id=application_id,
                account_id=account_id,
                kind=change.kind.value,
                stage=None if change.stage is None else change.stage.value,
                next_action_label=None if action is None else action.label,
                next_action_due=None if action is None else action.due,
                decision_id=change.decision_id,
                cancels_id=change.cancels,
                author=author.value,
                changed_at=now,
            )
            .returning(application_changes)
        ).one()
        return _change(row)

    def append_event(self, event: NewEvent) -> None:
        append_event(self._conn, event)


def _application(row: Row[Any]) -> Application:
    return Application(id=row.id, account_id=row.account_id, offer_id=row.offer_id)


def _change(row: Row[Any]) -> Change:
    return Change(
        id=row.id,
        application_id=row.application_id,
        kind=ChangeKind(row.kind),
        author=Author(row.author),
        changed_at=row.changed_at,
        stage=None if row.stage is None else Stage(row.stage),
        next_action=None
        if row.next_action_label is None
        else NextAction(row.next_action_label, row.next_action_due),
        decision_id=row.decision_id,
        cancels=row.cancels_id,
    )
