"""Use cases of the mail collection: connect and disconnect a mailbox, collect it, recover interrupted collections.

Decision ``docs/decisions/E1-collecte.md``. A collection lists, then downloads only the messages not stored yet and
writes each one alone in its transaction, before anything is decided about it: a collection run again downloads
nothing and writes nothing. It is always closed with a final status and its reason. The network is never used inside
a transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime

from rocky.messages.model import (
    QUERY_LABELS,
    AccessLostError,
    Gmail,
    GmailError,
    Mailbox,
    MailboxStatus,
    MailReader,
    MessageUnreadableError,
    Query,
    Storage,
    SyncCounts,
    SyncResult,
    SyncStatus,
    Trigger,
)
from rocky.messages.oauth import ACCESS_LOST_REASON
from rocky.messages.rules import (
    INTERRUPTED_REASON,
    QUERIES_VERSION,
    TECHNICAL_REASON,
    gmail_query,
    parse_message,
    sync_status,
    window_start,
)
from rocky.system.crypto import SealedValueError, TokenCipher
from rocky.system.events import Actor, NewEvent

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]
type Revoke = Callable[[str], None]

# Who starts a collection, for the journal: the planner, or the user's gesture.
TRIGGER_ACTORS = {Trigger.SCHEDULED: Actor.SYSTEM, Trigger.MANUAL: Actor.USER}
KEY_CHANGED_REASON = (
    "Le jeton de cette boîte ne s'ouvre plus avec la clé de Rocky (ROCKY_SECRET_KEY a changé) : "
    "reconnecte-la."
)


class MailboxNotFoundError(Exception):
    """No such mailbox for this account."""


class MailboxNotConnectedError(Exception):
    """The mailbox is disconnected or must be connected again: nothing to collect."""


class CollectBusyError(Exception):
    """Another collection of this mailbox is running."""


def connect_mailbox(
    storage: Storage,
    cipher: TokenCipher,
    *,
    account_id: int,
    address: str,
    refresh_token: str,
    now: datetime,
) -> tuple[int, bool]:
    """Store the access to a mailbox (Q2, Q3); ``(mailbox id, reconnected)``. A known address is reconnected."""
    sealed = cipher.seal(refresh_token)
    with storage.transaction() as store:
        existing = store.find_mailbox(account_id, address)
        if existing is None:
            mailbox_id = store.add_mailbox(account_id, address, sealed, now)
        else:
            mailbox_id = existing.id
            store.set_mailbox(
                mailbox_id, status=MailboxStatus.CONNECTED, sealed_token=sealed, now=now
            )
        store.append_event(
            _mailbox_event(
                "mailbox_reconnected" if existing else "mailbox_connected",
                Actor.USER,
                account_id=account_id,
                mailbox_id=mailbox_id,
                address=address,
            )
        )
    return mailbox_id, existing is not None


def disconnect_mailbox(
    storage: Storage,
    cipher: TokenCipher,
    revoke: Revoke,
    *,
    account_id: int,
    mailbox_id: int,
    now: datetime,
) -> str | None:
    """Withdraw Rocky's access at Google, then forget the token; the mailbox and its messages stay.

    Returns the reason why Google could not be told (the token is forgotten all the same), or None.
    """
    with storage.transaction() as store:
        mailbox = _own_mailbox(store.mailbox(mailbox_id), account_id)
    warning: str | None = None
    if mailbox.sealed_token is not None:
        try:
            revoke(cipher.open(mailbox.sealed_token))
        except SealedValueError:
            warning = "Le jeton ne s'ouvrait plus : retire l'accès de Rocky dans ton compte Google."
        except GmailError as error:
            warning = f"{error.reason} Retire l'accès de Rocky dans ton compte Google."
    with storage.transaction() as store:
        store.set_mailbox(
            mailbox.id, status=MailboxStatus.DISCONNECTED, sealed_token=None, now=now
        )
        store.append_event(
            _mailbox_event(
                "mailbox_disconnected",
                Actor.USER,
                account_id=account_id,
                mailbox_id=mailbox.id,
                address=mailbox.address,
                revoked=warning is None and mailbox.sealed_token is not None,
            )
        )
    return warning


def collect(
    storage: Storage,
    gmail: Gmail,
    cipher: TokenCipher,
    *,
    mailbox_id: int,
    trigger: Trigger,
    clock: Clock,
) -> SyncResult:
    """One collection of one mailbox, always closed.

    Raises ``CollectBusyError`` while this mailbox is collected elsewhere, ``MailboxNotConnectedError`` when it has no
    access to use.
    """
    with storage.lock(mailbox_id) as locked:
        if not locked:
            raise CollectBusyError(mailbox_id)
        with storage.transaction() as store:
            mailbox = store.mailbox(mailbox_id)
            if mailbox is None or mailbox.status is not MailboxStatus.CONNECTED:
                raise MailboxNotConnectedError(mailbox_id)
            last = store.last_completed_sync(mailbox_id)
            now = clock()
            start = window_start(None if last is None else last.started_at, now)
            sync_id = store.start_sync(mailbox, trigger, start, now)
        result = SyncResult(sync_id, mailbox.id, mailbox.account_id)
        access_lost = False
        try:
            _collect(result, storage, gmail, cipher, mailbox, start=start, clock=clock)
        except (AccessLostError, SealedValueError) as error:
            access_lost = True
            result.status = SyncStatus.FAILED
            result.reason = (
                ACCESS_LOST_REASON
                if isinstance(error, AccessLostError)
                else KEY_CHANGED_REASON
            )
        except GmailError as error:
            result.status, result.reason = SyncStatus.FAILED, error.reason
        except Exception:
            logger.exception("collection %s of mailbox %s failed", sync_id, mailbox_id)
            result.status, result.reason = SyncStatus.FAILED, TECHNICAL_REASON
        except BaseException:
            # The process is being stopped: the collection is closed, then the stop goes on.
            result.status, result.reason = SyncStatus.INTERRUPTED, INTERRUPTED_REASON
            raise
        finally:
            _close(
                storage,
                result,
                mailbox,
                trigger=trigger,
                start=start,
                access_lost=access_lost,
                now=clock(),
            )
        return result


def _collect(
    result: SyncResult,
    storage: Storage,
    gmail: Gmail,
    cipher: TokenCipher,
    mailbox: Mailbox,
    *,
    start: datetime,
    clock: Clock,
) -> None:
    if mailbox.sealed_token is None:  # Excluded by the constraint token_when_connected.
        raise MailboxNotConnectedError(mailbox.id)
    refresh_token = cipher.open(mailbox.sealed_token)
    with gmail.reader(refresh_token) as reader:
        found, listing_failure = _list(reader, start)
        with storage.transaction() as store:
            known = store.known_ids(mailbox.id, list(found))
        counts = SyncCounts(listed=len(found), known=len(known))
        write_failure: str | None = None
        for gmail_id, queries in found.items():
            if gmail_id in known:
                continue  # Never downloaded again: the criterion of E1.
            try:
                message = parse_message(reader.get(gmail_id))
                with storage.transaction() as store:
                    row_id = store.add_message(
                        mailbox,
                        message,
                        found_by=queries,
                        sync_id=result.sync_id,
                        now=clock(),
                    )
            except (GmailError, MessageUnreadableError) as error:
                counts = replace(counts, not_written=counts.not_written + 1)
                write_failure = write_failure or error.reason
                continue
            except Exception:
                # Logged with its trace, counted, and the reason shown with the collection.
                logger.exception(
                    "message %s of mailbox %s not written", gmail_id, mailbox.id
                )
                counts = replace(counts, not_written=counts.not_written + 1)
                write_failure = write_failure or TECHNICAL_REASON
                continue
            if row_id is None:
                # Written meanwhile by another collection: known, not written twice.
                counts = replace(counts, known=counts.known + 1)
            else:
                counts = replace(counts, new=counts.new + 1)
                result.written.append(row_id)
    result.counts = counts
    result.status, result.reason = sync_status(
        counts, listing_failure=listing_failure, write_failure=write_failure
    )


def _list(
    reader: MailReader, start: datetime
) -> tuple[dict[str, list[Query]], str | None]:
    """The identifiers of both queries, each with the queries that found it; the first listing failure."""
    found: dict[str, list[Query]] = {}
    failure: str | None = None
    for query in Query:
        try:
            ids = reader.list_ids(gmail_query(query, start))
        except AccessLostError:
            raise
        except GmailError as error:
            failure = failure or f"{error.reason} (recherche « {QUERY_LABELS[query]} »)"
            continue
        for gmail_id in ids:
            queries = found.setdefault(gmail_id, [])
            if query not in queries:
                queries.append(query)
    return found, failure


def _close(
    storage: Storage,
    result: SyncResult,
    mailbox: Mailbox,
    *,
    trigger: Trigger,
    start: datetime,
    access_lost: bool,
    now: datetime,
) -> None:
    if result.status is SyncStatus.RUNNING:
        # Unreachable by design; a collection is never left open.
        result.status, result.reason = SyncStatus.FAILED, TECHNICAL_REASON
    if result.written and result.status is SyncStatus.FAILED:
        # Messages were written before the failure: the collection brought something in.
        result.status = SyncStatus.PARTIAL
    with storage.transaction() as store:
        store.finish_sync(
            result.sync_id,
            status=result.status,
            reason=result.reason,
            counts=result.counts,
            now=now,
        )
        store.append_event(
            NewEvent(
                type="messages.sync_finished",
                actor=TRIGGER_ACTORS[trigger],
                subject_type="mail_sync",
                subject_id=str(result.sync_id),
                payload={
                    "mailbox_id": mailbox.id,
                    "status": result.status.value,
                    "trigger": trigger.value,
                    "reason": result.reason,
                    "window_start": start.isoformat(),
                    "queries_version": QUERIES_VERSION,
                    **asdict(result.counts),
                },
                account_id=mailbox.account_id,
            )
        )
        if access_lost:
            store.set_mailbox(
                mailbox.id, status=MailboxStatus.ACCESS_LOST, sealed_token=None, now=now
            )
            store.append_event(
                _mailbox_event(
                    "mailbox_access_lost",
                    Actor.SYSTEM,
                    account_id=mailbox.account_id,
                    mailbox_id=mailbox.id,
                    address=mailbox.address,
                    reason=result.reason,
                )
            )


def recover_interrupted(storage: Storage, *, clock: Clock) -> list[int]:
    """Close the collections a stopped process left open (their mailbox's lock is free): at the start of Rocky."""
    with storage.transaction() as store:
        running = store.running_syncs()
    closed: list[int] = []
    for sync in running:
        with storage.lock(sync.mailbox_id) as free:
            if not free:
                continue  # Another process is running it.
            with storage.transaction() as store:
                current = store.get_sync(sync.id)
                if current is None or current.status is not SyncStatus.RUNNING:
                    continue
                store.finish_sync(
                    sync.id,
                    status=SyncStatus.INTERRUPTED,
                    reason=INTERRUPTED_REASON,
                    counts=sync.counts,
                    now=clock(),
                )
                store.append_event(
                    NewEvent(
                        type="messages.sync_interrupted",
                        actor=Actor.SYSTEM,
                        subject_type="mail_sync",
                        subject_id=str(sync.id),
                        payload={
                            "mailbox_id": sync.mailbox_id,
                            "started_at": sync.started_at.isoformat(),
                        },
                        account_id=sync.account_id,
                    )
                )
            closed.append(sync.id)
    return closed


def _own_mailbox(mailbox: Mailbox | None, account_id: int) -> Mailbox:
    if mailbox is None or mailbox.account_id != account_id:
        raise MailboxNotFoundError
    return mailbox


def _mailbox_event(
    fact: str,
    actor: Actor,
    *,
    account_id: int,
    mailbox_id: int,
    address: str,
    **payload: str | bool | None,
) -> NewEvent:
    return NewEvent(
        type=f"messages.{fact}",
        actor=actor,
        subject_type="mailbox",
        subject_id=str(mailbox_id),
        payload={"address": address, **payload},
        account_id=account_id,
    )
