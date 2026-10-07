"""The mail collection on PostgreSQL (exit criterion of E1): a collection run again downloads and writes nothing; a
message is stored before anything else, once; a collection is always closed with its reason."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Engine, func, select

from rocky.messages.model import (
    AccessLostError,
    GmailError,
    MailboxStatus,
    Query,
    SyncCounts,
    SyncStatus,
    Trigger,
)
from rocky.messages.oauth import ACCESS_LOST_REASON
from rocky.messages.rules import INTERRUPTED_REASON, QUERIES_VERSION, parse_message
from rocky.messages.sql import SqlStorage, email_messages, mail_syncs
from rocky.messages.usecases import (
    KEY_CHANGED_REASON,
    CollectBusyError,
    MailboxNotConnectedError,
    MailboxNotFoundError,
    collect,
    connect_mailbox,
    disconnect_mailbox,
    recover_interrupted,
)
from rocky.system.crypto import TokenCipher
from rocky.system.events import events
from tests.messages.fakes import (
    ALERT_ID,
    LATIN_ID,
    NOW,
    REPLY_ID,
    FakeGmail,
    FakeReader,
    cipher,
    new_account,
    raw_message,
    unreadable,
)

REFRESH = "1//rafraichissement-de-test"


@dataclass
class Box:
    storage: SqlStorage
    account_id: int
    mailbox_id: int


@pytest.fixture
def box(migrated_engine: Engine) -> Box:
    with migrated_engine.begin() as connection:
        account_id = new_account(connection)
    storage = SqlStorage(migrated_engine)
    mailbox_id, _ = connect_mailbox(
        storage,
        cipher(),
        account_id=account_id,
        address="camille.dupont@example.com",
        refresh_token=REFRESH,
        now=NOW,
    )
    return Box(storage, account_id, mailbox_id)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> Any:
        return self.now


def run(box: Box, gmail: FakeGmail, clock: Clock | None = None) -> Any:
    return collect(
        box.storage,
        gmail,
        cipher(),
        mailbox_id=box.mailbox_id,
        trigger=Trigger.SCHEDULED,
        clock=clock or Clock(),
    )


def stored(engine: Engine, box: Box) -> dict[str, Any]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(email_messages).where(email_messages.c.mailbox_id == box.mailbox_id)
        )
        return {row.gmail_id: row for row in rows}


def event_types(engine: Engine, box: Box) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                select(events.c.type)
                .where(events.c.account_id == box.account_id)
                .order_by(events.c.id)
            ).scalars()
        )


def test_a_collection_stores_each_new_message_once_with_the_queries_that_found_it(
    migrated_engine: Engine, box: Box
) -> None:
    gmail = FakeGmail()

    result = run(box, gmail)

    assert result.status is SyncStatus.COMPLETED
    assert result.reason is None
    assert result.counts == SyncCounts(listed=3, known=0, new=3, not_written=0)
    rows = stored(migrated_engine, box)
    assert set(rows) == {REPLY_ID, LATIN_ID, ALERT_ID}
    assert sorted(result.written) == sorted(row.id for row in rows.values())
    assert rows[REPLY_ID].found_by == ["replies", "alerts"]
    assert rows[ALERT_ID].found_by == ["alerts"]
    assert rows[LATIN_ID].attachments == [
        {"name": "fiche-de-poste.pdf", "mime_type": "application/pdf", "size": 104857}
    ]
    assert rows[REPLY_ID].queries_version == QUERIES_VERSION
    assert rows[REPLY_ID].sync_id == result.sync_id
    assert (
        rows[REPLY_ID].subject
        == parse_message(raw_message("message_reply.json")).subject
    )
    # The token was opened to read the mailbox; the first window is 30 days.
    assert gmail.tokens == [REFRESH]
    after = int((NOW - timedelta(days=30)).timestamp())
    assert all(query.endswith(f"after:{after}") for query in gmail.reader_.queries)
    assert event_types(migrated_engine, box) == [
        "messages.mailbox_connected",
        "messages.sync_finished",
    ]


def test_a_collection_run_again_downloads_nothing_and_writes_nothing(
    migrated_engine: Engine, box: Box
) -> None:
    clock = Clock()
    first = run(box, FakeGmail(), clock)
    clock.now = NOW + timedelta(hours=1)
    again = FakeGmail()

    result = run(box, again, clock)

    assert again.reader_.gets == []
    assert result.written == []
    assert result.counts == SyncCounts(listed=3, known=3, new=0, not_written=0)
    assert result.status is SyncStatus.COMPLETED
    assert len(stored(migrated_engine, box)) == 3
    # From the start of the last completed collection, with a day of margin (Q6).
    after = int((NOW - timedelta(days=1)).timestamp())
    assert all(query.endswith(f"after:{after}") for query in again.reader_.queries)
    with migrated_engine.connect() as connection:
        counts = connection.execute(
            select(func.count()).where(mail_syncs.c.mailbox_id == box.mailbox_id)
        ).scalar_one()
    assert counts == 2
    assert first.sync_id != result.sync_id


def test_a_message_that_fails_is_not_written_and_is_taken_up_by_the_next_collection(
    migrated_engine: Engine, box: Box
) -> None:
    failing = FakeGmail(FakeReader(failures={LATIN_ID: unreadable()}))

    first = run(box, failing)

    assert first.status is SyncStatus.PARTIAL
    assert first.reason == (
        "1 message non écrit, repris au prochain relevé : message 18f incomplet"
    )
    assert first.counts == SyncCounts(listed=3, known=0, new=2, not_written=1)
    assert LATIN_ID not in stored(migrated_engine, box)

    retry = FakeGmail()
    second = run(box, retry)

    # A partial collection does not move the window: the message is listed again, and only it is downloaded.
    assert retry.reader_.gets == [LATIN_ID]
    assert second.status is SyncStatus.COMPLETED
    assert second.counts == SyncCounts(listed=3, known=2, new=1, not_written=0)
    assert set(stored(migrated_engine, box)) == {REPLY_ID, LATIN_ID, ALERT_ID}


def test_a_failed_search_keeps_what_the_other_one_found(
    migrated_engine: Engine, box: Box
) -> None:
    down = GmailError("Gmail est en panne (HTTP 503).")

    result = run(box, FakeGmail(FakeReader(failures={"alerts": down})))

    assert result.status is SyncStatus.PARTIAL
    assert (
        result.reason
        == "Gmail est en panne (HTTP 503). (recherche « Expéditeur d'alertes »)"
    )
    assert set(stored(migrated_engine, box)) == {REPLY_ID, LATIN_ID}


def test_a_collection_that_could_search_nothing_fails_with_its_reason(
    migrated_engine: Engine, box: Box
) -> None:
    down = GmailError("Gmail est en panne (HTTP 503).")

    result = run(box, FakeGmail(FakeReader(failures={"replies": down, "alerts": down})))

    assert result.status is SyncStatus.FAILED
    assert (
        result.reason
        == "Gmail est en panne (HTTP 503). (recherche « Boîte principale »)"
    )
    assert stored(migrated_engine, box) == {}


def test_google_refusing_the_token_asks_to_reconnect_the_mailbox(
    migrated_engine: Engine, box: Box
) -> None:
    result = run(box, FakeGmail(refusal=AccessLostError(ACCESS_LOST_REASON)))

    assert result.status is SyncStatus.FAILED
    assert result.reason == ACCESS_LOST_REASON
    with box.storage.transaction() as store:
        mailbox = store.mailbox(box.mailbox_id)
    assert mailbox is not None
    assert mailbox.status is MailboxStatus.ACCESS_LOST
    assert mailbox.sealed_token is None
    assert event_types(migrated_engine, box)[-2:] == [
        "messages.sync_finished",
        "messages.mailbox_access_lost",
    ]
    with pytest.raises(MailboxNotConnectedError):
        run(box, FakeGmail())


def test_access_lost_while_downloading_a_message_asks_to_reconnect(box: Box) -> None:
    """H3: a refusal met on a message (not on the token) is not counted as one unreadable message."""
    reader = FakeReader(failures={REPLY_ID: AccessLostError(ACCESS_LOST_REASON)})

    result = run(box, FakeGmail(reader))

    assert (result.status, result.reason) == (SyncStatus.FAILED, ACCESS_LOST_REASON)
    with box.storage.transaction() as store:
        mailbox = store.mailbox(box.mailbox_id)
    assert mailbox is not None and mailbox.status is MailboxStatus.ACCESS_LOST
    assert reader.gets == [REPLY_ID]


def test_access_lost_after_a_message_keeps_the_counts_of_what_came_in(box: Box) -> None:
    """H3: the messages written before the refusal are counted with the collection, which is partial."""
    reader = FakeReader(failures={LATIN_ID: AccessLostError(ACCESS_LOST_REASON)})

    result = run(box, FakeGmail(reader))

    assert (result.status, result.reason) == (SyncStatus.PARTIAL, ACCESS_LOST_REASON)
    assert result.counts.new == 1 and len(result.written) == 1
    with box.storage.transaction() as store:
        mailbox = store.mailbox(box.mailbox_id)
    assert mailbox is not None and mailbox.status is MailboxStatus.ACCESS_LOST


def test_a_token_sealed_with_another_key_asks_to_reconnect(box: Box) -> None:
    other = TokenCipher(Fernet.generate_key().decode())
    with box.storage.transaction() as store:
        store.set_mailbox(
            box.mailbox_id,
            status=MailboxStatus.CONNECTED,
            sealed_token=other.seal(REFRESH),
            now=NOW,
        )

    result = run(box, FakeGmail())

    assert (result.status, result.reason) == (SyncStatus.FAILED, KEY_CHANGED_REASON)


def test_an_unexpected_error_closes_the_collection_as_failed(box: Box) -> None:
    result = run(box, FakeGmail(FakeReader(failures={"replies": RuntimeError("bug")})))

    assert result.status is SyncStatus.FAILED
    assert result.reason is not None and "Erreur technique" in result.reason


class WrittenMeanwhile(FakeReader):
    """Another collection writes the reply while this one downloads it."""

    def __init__(self, box: Box) -> None:
        super().__init__()
        self.box = box

    def get(self, gmail_id: str) -> dict[str, object]:
        raw = super().get(gmail_id)
        if gmail_id == REPLY_ID:
            with self.box.storage.transaction() as store:
                mailbox = store.mailbox(self.box.mailbox_id)
                assert mailbox is not None
                sync_id = store.start_sync(mailbox, Trigger.MANUAL, NOW, NOW)
                store.add_message(
                    mailbox,
                    parse_message(raw),
                    found_by=[Query.REPLIES],
                    sync_id=sync_id,
                    now=NOW,
                )
                store.finish_sync(
                    sync_id,
                    status=SyncStatus.COMPLETED,
                    reason=None,
                    counts=SyncCounts(),
                    now=NOW,
                )
        return raw


def test_two_collections_at_once_never_store_a_message_twice(
    migrated_engine: Engine, box: Box
) -> None:
    result = run(box, FakeGmail(WrittenMeanwhile(box)))

    assert result.counts == SyncCounts(listed=3, known=1, new=2, not_written=0)
    assert len(result.written) == 2
    assert len(stored(migrated_engine, box)) == 3


def test_a_mailbox_is_collected_by_one_process_at_a_time(box: Box) -> None:
    with box.storage.lock(box.mailbox_id) as locked:
        assert locked
        with pytest.raises(CollectBusyError):
            run(box, FakeGmail())


def test_a_stop_during_the_collection_closes_it_as_interrupted(
    migrated_engine: Engine, box: Box
) -> None:
    stopping = FakeGmail(FakeReader(failures={ALERT_ID: KeyboardInterrupt()}))

    with pytest.raises(KeyboardInterrupt):
        run(box, stopping)

    with migrated_engine.connect() as connection:
        sync = connection.execute(
            select(mail_syncs).where(mail_syncs.c.mailbox_id == box.mailbox_id)
        ).one()
    assert sync.status == "interrupted"
    assert sync.reason == INTERRUPTED_REASON
    assert sync.finished_at is not None


def test_a_collection_left_running_is_closed_at_the_next_start(
    migrated_engine: Engine, box: Box
) -> None:
    with box.storage.transaction() as store:
        mailbox = store.mailbox(box.mailbox_id)
        assert mailbox is not None
        sync_id = store.start_sync(mailbox, Trigger.SCHEDULED, NOW, NOW)

    closed = recover_interrupted(box.storage, clock=lambda: NOW)

    assert sync_id in closed
    with box.storage.transaction() as store:
        sync = store.get_sync(sync_id)
    assert sync is not None
    assert (sync.status, sync.reason) == (SyncStatus.INTERRUPTED, INTERRUPTED_REASON)
    assert event_types(migrated_engine, box)[-1] == "messages.sync_interrupted"


def test_connecting_a_known_address_again_reconnects_it(
    migrated_engine: Engine, box: Box
) -> None:
    run(box, FakeGmail(refusal=AccessLostError(ACCESS_LOST_REASON)))

    mailbox_id, reconnected = connect_mailbox(
        box.storage,
        cipher(),
        account_id=box.account_id,
        address="camille.dupont@example.com",
        refresh_token="1//nouveau",
        now=NOW,
    )

    assert (mailbox_id, reconnected) == (box.mailbox_id, True)
    with box.storage.transaction() as store:
        assert [m.id for m in store.mailboxes(box.account_id)] == [box.mailbox_id]
        mailbox = store.mailbox(box.mailbox_id)
    assert mailbox is not None and mailbox.sealed_token is not None
    assert cipher().open(mailbox.sealed_token) == "1//nouveau"
    assert event_types(migrated_engine, box)[-1] == "messages.mailbox_reconnected"


def test_disconnecting_revokes_the_access_and_keeps_the_messages(
    migrated_engine: Engine, box: Box
) -> None:
    run(box, FakeGmail())
    revoked: list[str] = []

    warning = disconnect_mailbox(
        box.storage,
        cipher(),
        revoked.append,
        account_id=box.account_id,
        mailbox_id=box.mailbox_id,
        now=NOW,
    )

    assert warning is None
    assert revoked == [REFRESH]
    with box.storage.transaction() as store:
        mailbox = store.mailbox(box.mailbox_id)
    assert mailbox is not None
    assert (mailbox.status, mailbox.sealed_token) == (MailboxStatus.DISCONNECTED, None)
    assert len(stored(migrated_engine, box)) == 3
    assert event_types(migrated_engine, box)[-1] == "messages.mailbox_disconnected"


def test_a_revocation_google_refuses_still_forgets_the_token(box: Box) -> None:
    def refuse(token: str) -> None:
        raise GmailError("Google est injoignable (erreur réseau).")

    warning = disconnect_mailbox(
        box.storage,
        cipher(),
        refuse,
        account_id=box.account_id,
        mailbox_id=box.mailbox_id,
        now=NOW,
    )

    assert warning == (
        "Google est injoignable (erreur réseau). Retire l'accès de Rocky dans ton compte Google."
    )
    with box.storage.transaction() as store:
        mailbox = store.mailbox(box.mailbox_id)
    assert mailbox is not None and mailbox.sealed_token is None


def test_an_account_cannot_disconnect_the_mailbox_of_another(
    migrated_engine: Engine, box: Box
) -> None:
    with migrated_engine.begin() as connection:
        other = new_account(connection)

    with pytest.raises(MailboxNotFoundError):
        disconnect_mailbox(
            box.storage,
            cipher(),
            lambda token: None,
            account_id=other,
            mailbox_id=box.mailbox_id,
            now=NOW,
        )
