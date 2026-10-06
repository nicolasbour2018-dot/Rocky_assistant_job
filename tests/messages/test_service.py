"""The collection assembled (decision E1): what decides about a message (E2, E4) only ever receives messages already
stored, after their commit; a collection run again gives it nothing."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import Engine, select

from rocky.messages.model import SyncStatus, Trigger
from rocky.messages.service import MessagesService, messages_service
from rocky.messages.sql import email_messages
from rocky.messages.usecases import connect_mailbox
from rocky.system.config import GmailSettings, LlmSettings, Settings
from rocky.system.llm import GeminiModel
from tests.messages.fakes import GMAIL, NOW, FakeGmail, FakeReader, cipher, new_account


class Decider:
    """A stand-in for E2: records what it receives and checks each message is already in the database."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.calls: list[tuple[int, list[int]]] = []
        self.stored_when_called: list[bool] = []

    def __call__(self, account_id: int, message_ids: Sequence[int]) -> None:
        with self.engine.connect() as connection:
            found = set(
                connection.execute(
                    select(email_messages.c.id).where(
                        email_messages.c.id.in_(list(message_ids))
                    )
                ).scalars()
            )
        self.stored_when_called.append(found == set(message_ids))
        self.calls.append((account_id, list(message_ids)))


def service(
    engine: Engine,
    gmail: FakeGmail,
    decider: Decider | None = None,
    settings: GmailSettings = GMAIL,
) -> MessagesService:
    return MessagesService(
        engine,
        settings=settings,
        clock=lambda: NOW,
        on_collected=decider or Decider(engine),
        gmail=gmail,
    )


@pytest.fixture
def mailbox(migrated_engine: Engine) -> tuple[int, int]:
    with migrated_engine.begin() as connection:
        account_id = new_account(connection)
    mailbox_id, _ = connect_mailbox(
        MessagesService(migrated_engine, settings=GMAIL, clock=lambda: NOW).storage,
        cipher(),
        account_id=account_id,
        address="camille.dupont@example.com",
        refresh_token="1//r",
        now=NOW,
    )
    return account_id, mailbox_id


def test_a_decision_receives_only_stored_messages_and_nothing_on_a_resync(
    migrated_engine: Engine, mailbox: tuple[int, int]
) -> None:
    account_id, mailbox_id = mailbox
    decider = Decider(migrated_engine)
    messages = service(migrated_engine, FakeGmail(), decider)

    first = messages.collect_mailbox(mailbox_id, Trigger.MANUAL)
    second = messages.collect_mailbox(mailbox_id, Trigger.MANUAL)

    assert decider.calls == [(account_id, first.written), (account_id, [])]
    assert len(first.written) == 3
    assert second.written == []
    assert decider.stored_when_called == [True, True]


def test_a_message_that_could_not_be_written_never_reaches_a_decision(
    migrated_engine: Engine, mailbox: tuple[int, int]
) -> None:
    _, mailbox_id = mailbox
    decider = Decider(migrated_engine)
    reader = FakeReader(failures={"18f0b2c3d4e5f607": RuntimeError("base en panne")})

    result = service(migrated_engine, FakeGmail(reader), decider).collect_mailbox(
        mailbox_id, Trigger.SCHEDULED
    )

    assert result.status is SyncStatus.PARTIAL
    assert len(decider.calls[0][1]) == 2
    assert decider.stored_when_called == [True]


def test_a_failing_decision_never_undoes_the_collection(
    migrated_engine: Engine, mailbox: tuple[int, int]
) -> None:
    _, mailbox_id = mailbox

    def broken(account_id: int, message_ids: Sequence[int]) -> None:
        raise RuntimeError("E2 en panne")

    messages = MessagesService(
        migrated_engine,
        settings=GMAIL,
        clock=lambda: NOW,
        on_collected=broken,
        gmail=FakeGmail(),
    )

    result = messages.collect_mailbox(mailbox_id, Trigger.SCHEDULED)

    assert result.status is SyncStatus.COMPLETED
    assert len(result.written) == 3


def test_the_hourly_collection_reads_every_connected_mailbox_and_nothing_unconfigured(
    migrated_engine: Engine, mailbox: tuple[int, int]
) -> None:
    _, mailbox_id = mailbox
    gmail = FakeGmail()

    assert service(migrated_engine, gmail, settings=GmailSettings()).collect_all() == []
    assert gmail.tokens == []

    results = service(migrated_engine, gmail).collect_all()

    assert mailbox_id in [result.mailbox_id for result in results]


def test_the_hourly_collection_skips_a_mailbox_being_collected(
    migrated_engine: Engine, mailbox: tuple[int, int]
) -> None:
    _, mailbox_id = mailbox
    messages = service(migrated_engine, FakeGmail())

    with messages.storage.lock(mailbox_id):
        results = messages.collect_all()

    assert mailbox_id not in [result.mailbox_id for result in results]


def test_the_factory_gives_the_model_only_to_what_classifies(
    migrated_engine: Engine,
) -> None:
    """Step H4: one construction of the service; a command that does not classify leaves the model out on purpose."""
    settings = Settings(
        database_url="",
        public_url="",
        gmail=GMAIL,
        llm=LlmSettings(api_key="clé", mail_per_hour=1),
    )

    def built(*, classify: bool) -> MessagesService:
        return messages_service(
            migrated_engine,
            settings,
            clock=lambda: NOW,
            classify=classify,
            new_http=None,
        )

    classifying, collecting = built(classify=True), built(classify=False)

    assert isinstance(classifying.model, GeminiModel)
    assert classifying.limits.per_hour == 1
    assert collecting.model is None
