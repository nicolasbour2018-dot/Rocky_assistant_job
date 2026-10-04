"""In-memory adapters of the applications (D1): the store and the decisions of ``offres``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from rocky.candidatures.model import (
    Application,
    Change,
    LetterEntry,
    LetterVersion,
    MessageVersion,
    NewChange,
    NewLetter,
    NewMessage,
    NewPrefill,
    NewRevision,
    NewSending,
    NoLetter,
    NoteRow,
    Prefill,
    Revision,
    Sending,
)
from rocky.offres.decisions import Author, Decision, DecisionValue
from rocky.system.events import NewEvent

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TODAY = date(2026, 9, 29)


@dataclass
class FakeStore:
    applications: list[Application] = field(default_factory=list)
    rows: list[Change] = field(default_factory=list)
    events: list[NewEvent] = field(default_factory=list)
    selections: list[tuple[int, Mapping[str, Any] | None]] = field(default_factory=list)
    letter_rows: list[tuple[int, LetterEntry]] = field(default_factory=list)
    message_rows: list[tuple[int, MessageVersion]] = field(default_factory=list)
    revision_rows: list[Revision] = field(default_factory=list)
    sending_rows: list[Sending] = field(default_factory=list)
    prefill_rows: list[Prefill] = field(default_factory=list)
    note_rows: list[NoteRow] = field(default_factory=list)
    language_rows: list[tuple[int, str]] = field(default_factory=list)

    def application_for_offer(
        self, account_id: int, offer_id: int, now: datetime
    ) -> Application:
        for application in self.applications:
            if (application.account_id, application.offer_id) == (account_id, offer_id):
                return application
        application = Application(len(self.applications) + 1, account_id, offer_id)
        self.applications.append(application)
        return application

    def locked_application(
        self, account_id: int, application_id: int
    ) -> Application | None:
        return next(
            (
                application
                for application in self.applications
                if application.id == application_id
                and application.account_id == account_id
            ),
            None,
        )

    def changes(self, application_id: int) -> list[Change]:
        return [row for row in self.rows if row.application_id == application_id]

    def insert_change(
        self,
        account_id: int,
        application_id: int,
        change: NewChange,
        *,
        author: Author,
        now: datetime,
    ) -> Change:
        row = Change(
            id=len(self.rows) + 1,
            application_id=application_id,
            kind=change.kind,
            author=author,
            changed_at=now,
            stage=change.stage,
            next_action=change.next_action,
            decision_id=change.decision_id,
            cancels=change.cancels,
        )
        self.rows.append(row)
        return row

    def cv_selection(self, application_id: int) -> Mapping[str, Any] | None:
        mine = [layout for owner, layout in self.selections if owner == application_id]
        return mine[-1] if mine else None

    def insert_cv_selection(
        self,
        account_id: int,
        application_id: int,
        layout: Mapping[str, Any] | None,
        now: datetime,
    ) -> None:
        self.selections.append((application_id, layout))

    def letters(self, application_id: int) -> list[LetterEntry]:
        return [entry for owner, entry in self.letter_rows if owner == application_id]

    def insert_letter(
        self,
        account_id: int,
        application_id: int,
        letter: NewLetter | None,
        now: datetime,
    ) -> int:
        letter_id = len(self.letter_rows) + 1
        entry: LetterEntry = (
            NoLetter(letter_id, now)
            if letter is None
            else LetterVersion(
                letter_id,
                letter.language,
                letter.paragraphs,
                letter.header,
                letter.generic_sha256,
                now,
            )
        )
        self.letter_rows.append((application_id, entry))
        return letter_id

    def messages(self, application_id: int) -> list[MessageVersion]:
        return [entry for owner, entry in self.message_rows if owner == application_id]

    def insert_message(
        self,
        account_id: int,
        application_id: int,
        message: NewMessage,
        now: datetime,
    ) -> int:
        message_id = len(self.message_rows) + 1
        self.message_rows.append(
            (
                application_id,
                MessageVersion(
                    message_id, message.language, message.text, message.origin, now
                ),
            )
        )
        return message_id

    def revisions(self, application_id: int) -> list[Revision]:
        return [r for r in self.revision_rows if r.application_id == application_id]

    def insert_revision(
        self,
        account_id: int,
        application_id: int,
        revision: NewRevision,
        now: datetime,
    ) -> int:
        revision_id = len(self.revision_rows) + 1
        self.revision_rows.append(
            Revision(
                id=revision_id,
                application_id=application_id,
                kind=revision.kind,
                language=revision.language,
                path=revision.path,
                sha256=revision.sha256,
                inputs_sha256=revision.inputs_sha256,
                letter_id=revision.letter_id,
                created_at=now,
            )
        )
        return revision_id

    def sendings(self, application_id: int) -> list[Sending]:
        return [s for s in self.sending_rows if s.application_id == application_id]

    def insert_sending(
        self,
        account_id: int,
        application_id: int,
        change_id: int,
        sending: NewSending,
        now: datetime,
    ) -> int:
        sending_id = len(self.sending_rows) + 1
        self.sending_rows.append(
            Sending(
                id=sending_id,
                application_id=application_id,
                change_id=change_id,
                sent_on=sending.sent_on,
                channel=sending.channel,
                channel_detail=sending.channel_detail,
                cv_revision_id=sending.cv_revision_id,
                letter_revision_id=sending.letter_revision_id,
                message_id=sending.message_id,
                created_at=now,
            )
        )
        return sending_id

    def prefills(self, application_id: int) -> list[Prefill]:
        return [p for p in self.prefill_rows if p.application_id == application_id]

    def insert_prefill(
        self,
        account_id: int,
        application_id: int,
        prefill: NewPrefill,
        now: datetime,
    ) -> int:
        prefill_id = len(self.prefill_rows) + 1
        self.prefill_rows.append(
            Prefill(
                id=prefill_id,
                application_id=application_id,
                target_url=prefill.target_url,
                cv_revision_id=prefill.cv_revision_id,
                letter_revision_id=prefill.letter_revision_id,
                message_id=prefill.message_id,
                filled=prefill.filled,
                missing=prefill.missing,
                created_at=now,
            )
        )
        return prefill_id

    def notes(self, application_id: int) -> list[NoteRow]:
        return [n for n in self.note_rows if n.application_id == application_id]

    def insert_note(
        self,
        account_id: int,
        application_id: int,
        *,
        text: str | None,
        removes: int | None,
        now: datetime,
    ) -> int:
        note_id = len(self.note_rows) + 1
        self.note_rows.append(NoteRow(note_id, application_id, text, removes, now))
        return note_id

    def language(self, application_id: int) -> str | None:
        mine = [code for owner, code in self.language_rows if owner == application_id]
        return mine[-1] if mine else None

    def insert_language(
        self, account_id: int, application_id: int, language: str, now: datetime
    ) -> None:
        self.language_rows.append((application_id, language))

    def append_event(self, event: NewEvent) -> None:
        self.events.append(event)

    @property
    def event_types(self) -> list[str]:
        return [event.type for event in self.events]


@dataclass
class FakeOffers:
    """The decisions of the offers: the value in force of each offer, and what was recorded or cancelled."""

    in_force: dict[int, DecisionValue] = field(default_factory=dict)
    recorded: list[tuple[int, Decision]] = field(default_factory=list)
    cancelled: list[int] = field(default_factory=list)
    # The value each decision replaced, to restore it when the decision is cancelled.
    replaced: dict[int, DecisionValue | None] = field(default_factory=dict)

    def decision_in_force(self, account_id: int, offer_id: int) -> DecisionValue | None:
        return self.in_force.get(offer_id)

    def record_interested(
        self, account_id: int, offer_id: int, decision: Decision, now: datetime
    ) -> int:
        self.recorded.append((offer_id, decision))
        decision_id = 100 + len(self.recorded)
        self.replaced[decision_id] = self.in_force.get(offer_id)
        self.in_force[offer_id] = decision.value
        return decision_id

    def cancel(self, account_id: int, decision_id: int, now: datetime) -> bool:
        if decision_id in self.cancelled:
            return False
        self.cancelled.append(decision_id)
        offer_id = self.recorded[decision_id - 101][0]
        previous = self.replaced[decision_id]
        if previous is None:
            self.in_force.pop(offer_id, None)
        else:
            self.in_force[offer_id] = previous
        return True
