"""SQL access of the applications: the only place where the tables of the module ``candidatures`` are queried.

Decision ``docs/decisions/D1-dossier-statuts.md``: the changes are appended, never changed; the stage and the next
action are computed from them (``rules.dossier``).
"""

from __future__ import annotations

from collections.abc import Mapping
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rocky.candidatures.model import (
    Application,
    Change,
    ChangeKind,
    LetterEntry,
    LetterHeader,
    LetterOrigin,
    LetterParagraph,
    LetterVersion,
    MessageOrigin,
    MessageVersion,
    NewChange,
    NewLetter,
    NewMessage,
    NextAction,
    NoLetter,
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

# The CV selection of an application (decision D3, Q4): appended at each adjustment, the latest in force; a null
# layout goes back to the rules' proposal.
application_cv_selections = Table(
    "application_cv_selections",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("application_id", BigInteger, ForeignKey("applications.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("layout", JSONB),
    Column("changed_at", DateTime(timezone=True), nullable=False),
    Index("ix_application_cv_selections_application_id", "application_id", "id"),
)


# The letters of an application (decision D4, Q4, Q11, Q17): appended at each validation, the latest of each language
# in force; a row « none » is « Pas de lettre pour cette candidature ».
application_letters = Table(
    "application_letters",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("application_id", BigInteger, ForeignKey("applications.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("language", Text),
    # [{"role", "text", "origin", "proposed", "signals"}]: the choice of each paragraph is training data (D14).
    Column("paragraphs", JSONB),
    Column("subject", Text),
    Column("recipient", Text),
    Column("generic_sha256", Text),
    Column("checks_version", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("kind IN ('letter', 'none')", name="kind"),
    CheckConstraint("language IS NULL OR language IN ('fr', 'en')", name="language"),
    CheckConstraint(
        "(kind = 'letter') = (language IS NOT NULL AND paragraphs IS NOT NULL "
        "AND subject IS NOT NULL AND recipient IS NOT NULL)",
        name="letter_complete",
    ),
    Index("ix_application_letters_application_id", "application_id", "id"),
)

# The accompanying message of an application (decision D4, Q1, Q12): appended at each validation.
application_messages = Table(
    "application_messages",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("application_id", BigInteger, ForeignKey("applications.id"), nullable=False),
    Column("account_id", BigInteger, ForeignKey("accounts.id"), nullable=False),
    Column("language", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("proposed", Text),
    Column("signals", JSONB, nullable=False),
    Column("checks_version", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("language IN ('fr', 'en')", name="language"),
    CheckConstraint(_in("origin", MessageOrigin), name="origin"),
    Index("ix_application_messages_application_id", "application_id", "id"),
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

    def cv_selection(self, application_id: int) -> Mapping[str, Any] | None:
        layout = self._conn.execute(
            select(application_cv_selections.c.layout)
            .where(application_cv_selections.c.application_id == application_id)
            .order_by(application_cv_selections.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return None if layout is None else dict(layout)

    def insert_cv_selection(
        self,
        account_id: int,
        application_id: int,
        layout: Mapping[str, Any] | None,
        now: datetime,
    ) -> None:
        self._conn.execute(
            application_cv_selections.insert().values(
                application_id=application_id,
                account_id=account_id,
                layout=None if layout is None else dict(layout),
                changed_at=now,
            )
        )

    def letters(self, application_id: int) -> list[LetterEntry]:
        rows = self._conn.execute(
            select(application_letters)
            .where(application_letters.c.application_id == application_id)
            .order_by(application_letters.c.id)
        )
        return [_letter(row) for row in rows]

    def insert_letter(
        self,
        account_id: int,
        application_id: int,
        letter: NewLetter | None,
        now: datetime,
    ) -> int:
        values: dict[str, Any] = {"kind": "none"}
        if letter is not None:
            values = {
                "kind": "letter",
                "language": letter.language,
                "paragraphs": [
                    {
                        "role": p.role,
                        "text": p.text,
                        "origin": p.origin.value,
                        "proposed": p.proposed,
                        "signals": list(p.signals),
                    }
                    for p in letter.paragraphs
                ],
                "subject": letter.header.subject,
                "recipient": letter.header.recipient,
                "generic_sha256": letter.generic_sha256,
                "checks_version": letter.checks_version,
            }
        letter_id: int = self._conn.execute(
            application_letters.insert()
            .values(
                application_id=application_id,
                account_id=account_id,
                created_at=now,
                **values,
            )
            .returning(application_letters.c.id)
        ).scalar_one()
        return letter_id

    def messages(self, application_id: int) -> list[MessageVersion]:
        rows = self._conn.execute(
            select(application_messages)
            .where(application_messages.c.application_id == application_id)
            .order_by(application_messages.c.id)
        )
        return [
            MessageVersion(
                id=row.id,
                language=row.language,
                text=row.text,
                origin=MessageOrigin(row.origin),
                created_at=row.created_at,
            )
            for row in rows
        ]

    def insert_message(
        self,
        account_id: int,
        application_id: int,
        message: NewMessage,
        now: datetime,
    ) -> int:
        message_id: int = self._conn.execute(
            application_messages.insert()
            .values(
                application_id=application_id,
                account_id=account_id,
                language=message.language,
                text=message.text,
                origin=message.origin.value,
                proposed=message.proposed,
                signals=list(message.signals),
                checks_version=message.checks_version,
                created_at=now,
            )
            .returning(application_messages.c.id)
        ).scalar_one()
        return message_id

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


def _letter(row: Row[Any]) -> LetterEntry:
    if row.kind == "none":
        return NoLetter(id=row.id, created_at=row.created_at)
    return LetterVersion(
        id=row.id,
        language=row.language,
        paragraphs=tuple(
            LetterParagraph(
                role=item["role"],
                text=item["text"],
                origin=LetterOrigin(item["origin"]),
                proposed=item.get("proposed"),
                signals=tuple(item.get("signals", ())),
            )
            for item in row.paragraphs
        ),
        header=LetterHeader(row.subject, row.recipient),
        generic_sha256=row.generic_sha256,
        created_at=row.created_at,
    )
