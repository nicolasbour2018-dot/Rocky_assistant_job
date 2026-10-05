"""The job alerts as a source (E3) on PostgreSQL, through the service as the planner uses it: every card gives an
offer (Q3), the postings are read when they can be and an unread one keeps its reason (Q2, Q5), an alert is read once
(Q4), and an alert is written whole or not at all.

Exit criterion (« au moins une offre Indeed réelle par jour ») is checked on real alerts, never here; these tests check
what it rests on: no card is lost, no link is read twice or against the stop rule, no error is silent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from rocky.messages.alerts import rules as alert_rules
from rocky.messages.alerts.model import (
    AlertsReport,
    LinkOutcome,
    NotTried,
    ReadingStatus,
)
from rocky.messages.alerts.usecases import (
    DAY_LIMIT_REASON,
    NO_PROFILE_REASON,
    TECHNICAL_REASON,
    TOO_OLD_REASON,
)
from rocky.messages.classification.model import Category
from rocky.messages.links import AlertOffersLink
from rocky.messages.model import Query
from rocky.messages.service import MessagesService
from rocky.messages.sql import SqlStore, alert_offers, alert_readings, message_decisions
from rocky.messages.usecases import connect_mailbox
from rocky.offres.imports.model import (
    ImportMethod,
    ImportOutcome,
    ImportPreview,
    ImportResult,
)
from rocky.offres.model import Origin
from rocky.offres.rules import scoring_inputs
from rocky.offres.sources.model import CollectedOffer, SourceCode
from rocky.offres.sql import SqlStorage as OffresStorage
from rocky.offres.sql import SqlStore as OffresStore
from rocky.offres.sql import job_offers, offer_scores
from rocky.offres.usecases import record_offer
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.events import events
from tests.messages.fakes import GMAIL, NOW, cipher, recorded_alert, store_mail
from tests.offres.fakes import Seeker, new_seeker, posting

RECENT = NOW - timedelta(hours=2)
DESCRIPTION = "Nous recherchons un ou une Data Analyst pour notre équipe. " * 10


@dataclass
class FakePages:
    """The reading of posting links: an answer per link (by default a complete posting), and the links asked."""

    answers: dict[str, ImportResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, link: str, *, today: date) -> ImportResult:
        self.calls.append(link)
        if link in self.answers:
            return self.answers[link]
        url = f"https://www.exemple-emplois.fr/annonce/{len(self.calls)}"
        return ImportResult.ok(
            ImportPreview(
                CollectedOffer(
                    source="exemple-emplois.fr",
                    external_id=url,
                    url=url,
                    title="Data Analyst (H/F)",
                    description=DESCRIPTION,
                    description_complete=True,
                    salary_text="45 000 € par an",
                ),
                ImportMethod.JSON_LD,
            )
        )


@dataclass
class Inbox:
    engine: Engine
    service: MessagesService
    seeker: Seeker
    mailbox_id: int
    pages: FakePages

    @property
    def account_id(self) -> int:
        return self.seeker.account_id

    def alert(self, name: str, *, received_at: Any = RECENT) -> int:
        data = recorded_alert(name)
        return store_mail(
            self.service.storage,
            self.mailbox_id,
            sender=data["sender"],
            subject=data["subject"],
            body=data["body_text"],
            body_html=data["body_html"],
            received_at=received_at,
            found_by=Query.ALERTS,
        )

    def read(self, *, links: bool = True) -> AlertsReport:
        self.service.classify(self.account_id, use_model=False)
        return self.service.read_alerts(self.account_id, links=links)

    def rows(self, table: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [
                dict(row._mapping)
                for row in connection.execute(
                    select(table)
                    .where(table.c.account_id == self.account_id)
                    .order_by(table.c.id)
                )
            ]

    def offers(self) -> list[dict[str, Any]]:
        return self.rows(job_offers)

    def event_payloads(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [
                row.payload
                for row in connection.execute(
                    select(events.c.payload)
                    .where(
                        events.c.account_id == self.account_id,
                        events.c.type == "messages.alert_read",
                    )
                    .order_by(events.c.id)
                )
            ]

    def snapshot(self) -> tuple[int, ...]:
        """What a failed transaction must leave as it was."""
        return (
            len(self.rows(alert_readings)),
            len(self.rows(alert_offers)),
            len(self.offers()),
            len(self.event_payloads()),
        )


def _service(
    engine: Engine, pages: FakePages, *, now: datetime = NOW
) -> MessagesService:
    @contextmanager
    def opened() -> Iterator[FakePages]:
        yield pages

    return MessagesService(engine, settings=GMAIL, clock=lambda: now, pages=opened)


@pytest.fixture
def inbox(migrated_engine: Engine) -> Inbox:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)
    pages = FakePages()
    service = _service(migrated_engine, pages)
    mailbox_id, _ = connect_mailbox(
        service.storage,
        cipher(),
        account_id=seeker.account_id,
        address="camille@example.com",
        refresh_token="1//rafraichissement",
        now=NOW,
    )
    return Inbox(migrated_engine, service, seeker, mailbox_id, pages)


# Q3: every card gives an offer, scored and linked to its best track, never thrown away.


def test_every_card_of_an_alert_becomes_a_scored_offer(inbox: Inbox) -> None:
    message_id = inbox.alert("hellowork_alerte")

    report = inbox.read(links=False)

    offers = inbox.offers()
    assert [offer["title"] for offer in offers] == [
        "Data Analyst H/F",
        "Analyste de Données Mesure d'Impact Social H/F",
        "CDD Data Analyst H/F",
        "Business - Data Analyst - CDD H/F",
    ]
    assert {offer["origin"] for offer in offers} == {Origin.ALERT.value}
    assert {offer["source"] for offer in offers} == {"hellowork.com"}
    with inbox.engine.connect() as connection:
        assert OffresStore(connection).unscored_or_orphan_offers(inbox.account_id) == []
        scored = connection.execute(
            select(func.count(func.distinct(offer_scores.c.offer_id))).where(
                offer_scores.c.offer_id.in_([offer["id"] for offer in offers])
            )
        ).scalar_one()
    assert scored == 4
    (reading,) = inbox.rows(alert_readings)
    assert (reading["message_id"], reading["status"], reading["cards"]) == (
        message_id,
        ReadingStatus.READ.value,
        4,
    )
    assert (report.alerts, report.offers, report.created) == (1, 4, 4)


@pytest.mark.parametrize(
    ("name", "count"),
    [
        ("hellowork_notification", 20),
        ("cadremploi_nouvelles", 5),
        ("efc_selection", 20),
        ("linkedin_alerte", 6),
        ("linkedin_relais", 4),
    ],
)
def test_the_alerts_of_each_platform_are_classified_then_read(
    inbox: Inbox, name: str, count: int
) -> None:
    message_id = inbox.alert(name)

    inbox.read(links=False)

    with inbox.engine.connect() as connection:
        category = connection.execute(
            select(message_decisions.c.category).where(
                message_decisions.c.message_id == message_id
            )
        ).scalar_one()
    assert category == Category.JOB_ALERT.value
    assert len(inbox.rows(alert_offers)) == count


def test_a_pass_replayed_writes_nothing_new(inbox: Inbox) -> None:
    """Q4: an alert is read once; the next passes, and the same card in a later alert, add no offer."""
    inbox.alert("hellowork_alerte")
    inbox.read()
    before = inbox.snapshot()
    calls = len(inbox.pages.calls)

    report = inbox.read()

    assert inbox.snapshot() == before
    assert len(inbox.pages.calls) == calls
    assert report.alerts == 0


def test_the_same_posting_in_two_alerts_is_one_offer(inbox: Inbox) -> None:
    inbox.alert("hellowork_alerte")
    inbox.alert("hellowork_alerte", received_at=RECENT - timedelta(hours=1))

    inbox.read(links=False)

    assert len(inbox.offers()) == 4
    assert [row["created"] for row in inbox.rows(alert_offers)] == [True] * 4 + [
        False
    ] * 4


# Q2, Q5: the posting of a card is read when it can be; an unread one keeps its reason.


def test_a_read_posting_completes_the_offer_and_gives_its_address(
    inbox: Inbox,
) -> None:
    inbox.alert("hellowork_recommandation")

    report = inbox.read()

    (offer,) = inbox.offers()
    assert offer["description_complete"]
    assert offer["url"] == "https://www.exemple-emplois.fr/annonce/1"
    # The card's facts stay, the posting fills what the card lacks.
    assert (offer["title"], offer["company"]) == (
        "Data Analyst - Data Engineer H/F",
        "FMA Assurances",
    )
    assert offer["salary_text"] == "45 000 € par an"
    (row,) = inbox.rows(alert_offers)
    assert (row["link_outcome"], row["reason"]) == (LinkOutcome.READ.value, None)
    assert (report.pages_read, report.pages_unread) == (1, 0)


def test_a_platform_that_refuses_is_not_asked_again_during_the_pass(
    inbox: Inbox,
) -> None:
    """The stop rule of C1: the first refusal stops the platform; each card says why it was not read."""
    inbox.alert("hellowork_alerte")
    refusal = "Refusé par le site (HTTP 403). Tu peux coller la description de l'annonce ci-dessous."
    inbox.pages.answers["https://emails.hellowork.com/clic/0003"] = (
        ImportResult.failure(ImportOutcome.REFUSED, refusal)
    )

    inbox.read()

    assert inbox.pages.calls == ["https://emails.hellowork.com/clic/0003"]
    rows = inbox.rows(alert_offers)
    assert [(row["link_outcome"], row["not_tried"]) for row in rows] == [
        (LinkOutcome.REFUSED.value, None),
        (LinkOutcome.NOT_TRIED.value, NotTried.HOST_STOPPED.value),
        (LinkOutcome.NOT_TRIED.value, NotTried.HOST_STOPPED.value),
        (LinkOutcome.NOT_TRIED.value, NotTried.HOST_STOPPED.value),
    ]
    assert rows[0]["reason"] == refusal
    first = inbox.offers()[0]
    assert not first["description_complete"]
    assert first["incomplete_reason"] == f"Tirée d'une alerte Hellowork. {refusal}"


def test_a_failed_link_keeps_its_reason_and_the_others_are_read(inbox: Inbox) -> None:
    inbox.alert("hellowork_alerte")
    gone = "L'annonce n'existe plus, ou le lien est faux (HTTP 404)."
    inbox.pages.answers["https://emails.hellowork.com/clic/0003"] = (
        ImportResult.failure(ImportOutcome.FAILED, gone)
    )

    report = inbox.read()

    assert len(inbox.pages.calls) == 4
    assert [row["link_outcome"] for row in inbox.rows(alert_offers)] == [
        LinkOutcome.FAILED.value,
        *[LinkOutcome.READ.value] * 3,
    ]
    assert inbox.rows(alert_offers)[0]["reason"] == gone
    assert (report.pages_read, report.pages_unread) == (3, 1)


def test_an_alert_older_than_three_days_gives_nothing_and_says_so(
    inbox: Inbox,
) -> None:
    """Q8: an old alert is marked « trop ancienne », without offer nor call; it does not count in the day's limit."""
    inbox.alert("hellowork_alerte", received_at=NOW - timedelta(days=3, hours=1))

    report = inbox.read()

    (reading,) = inbox.rows(alert_readings)
    assert (reading["status"], reading["platform"], reading["cards"]) == (
        ReadingStatus.TOO_OLD.value,
        "hellowork",
        0,
    )
    assert reading["reason"] == TOO_OLD_REASON
    assert inbox.offers() == [] and inbox.pages.calls == []
    assert report.too_old == 1


def test_at_most_ten_alerts_a_day_give_their_offers_the_most_recent_first(
    inbox: Inbox,
) -> None:
    """Q8: the others wait for the next day; on the screen they are not read yet, with the reason."""
    ids = [
        inbox.alert(
            "hellowork_recommandation", received_at=RECENT - timedelta(minutes=n)
        )
        for n in range(12)
    ]

    report = inbox.read(links=False)

    read = {row["message_id"] for row in inbox.rows(alert_readings)}
    assert read == set(ids[:10])
    assert (report.alerts, report.postponed) == (10, 2)
    assert report.reason == DAY_LIMIT_REASON.format(limit=10)
    assert inbox.read(links=False).alerts == 0

    tomorrow = _service(inbox.engine, inbox.pages, now=NOW + timedelta(days=1))
    assert tomorrow.read_alerts(inbox.account_id, links=False).alerts == 2


def test_a_known_complete_offer_is_not_read_again_and_stays_the_watch_s(
    inbox: Inbox,
) -> None:
    """A LinkedIn card has the identity of the watch: the offer found by the watch is the same offer."""
    with inbox.engine.begin() as connection:
        known = record_offer(
            OffresStore(connection),
            account_id=inbox.account_id,
            offer=posting(
                "4463227701",
                source=SourceCode.LINKEDIN.value,
                url="https://fr.linkedin.com/jobs/view/data-analyst-4463227701",
            ),
            inputs=scoring_inputs(inbox.seeker.profile(connection)),
            origin=Origin.WATCH,
            track_ids=[inbox.seeker.tracks["Data"]],
            now=NOW,
            today=NOW.date(),
        ).offer_id
    inbox.alert("linkedin_relais")

    inbox.read()

    first = inbox.rows(alert_offers)[0]
    assert (first["offer_id"], first["created"], first["not_tried"]) == (
        known,
        False,
        NotTried.KNOWN_COMPLETE.value,
    )
    assert "https://www.linkedin.com/jobs/view/4463227701/" not in inbox.pages.calls
    assert len(inbox.pages.calls) == 3
    assert inbox.offers()[0]["origin"] == Origin.WATCH.value


# Q6: an alert Rocky cannot read says so; an error is never silent.


def test_an_alert_of_an_unknown_format_is_shown_as_not_read(inbox: Inbox) -> None:
    store_mail(
        inbox.service.storage,
        inbox.mailbox_id,
        sender="JobLeads <mailer@jobleads.com>",
        subject="Il y a 3 nouvelles offres d’emploi correspondant à votre recherche",
        body="Data Analyst — Paris",
        received_at=RECENT,
        found_by=Query.ALERTS,
    )

    report = inbox.read()

    (reading,) = inbox.rows(alert_readings)
    assert (reading["status"], reading["platform"], reading["cards"]) == (
        ReadingStatus.UNKNOWN_FORMAT.value,
        None,
        0,
    )
    assert "mailer@jobleads.com" in reading["reason"]
    assert inbox.offers() == []
    assert report.unknown_formats == 1


def test_a_reader_that_breaks_marks_its_alert_and_the_others_go_on(
    inbox: Inbox, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    broken = inbox.alert("cadremploi_nouvelles")
    inbox.alert("hellowork_alerte", received_at=RECENT - timedelta(hours=1))
    original = alert_rules.cards

    def cards(message: Any, platform: Any) -> Any:
        if message.id == broken:
            raise RuntimeError("lecteur cassé")
        return original(message, platform)

    monkeypatch.setattr("rocky.messages.alerts.usecases.cards", cards)

    with caplog.at_level(logging.ERROR):
        report = inbox.read()

    statuses = {row["message_id"]: row["status"] for row in inbox.rows(alert_readings)}
    assert statuses[broken] == ReadingStatus.FAILED.value
    assert TECHNICAL_REASON in [row["reason"] for row in inbox.rows(alert_readings)]
    assert len(inbox.offers()) == 4
    assert report.failed == 1
    assert "failed unexpectedly" in caplog.text


def test_no_link_is_written_in_the_journal_nor_the_log(
    inbox: Inbox, caplog: pytest.LogCaptureFixture
) -> None:
    """A link of an alert may carry a personal tracking token (plan §8, C2 → E3)."""
    inbox.alert("hellowork_alerte")

    with caplog.at_level(logging.DEBUG):
        inbox.read()

    (payload,) = inbox.event_payloads()
    assert payload == {
        "platform": "hellowork",
        "status": "read",
        "cards": 4,
        "created": 4,
        "pages_read": 4,
        "pages_unread": 0,
    }
    assert "clic" not in caplog.text
    assert "exemple-emplois" not in caplog.text


# One transaction per alert; a watch holding the offers postpones it.


def test_the_alerts_wait_while_a_watch_holds_the_offers(inbox: Inbox) -> None:
    inbox.alert("hellowork_alerte")

    with OffresStorage(inbox.engine).lock(inbox.account_id) as locked:
        assert locked
        report = inbox.read()
        assert inbox.snapshot() == (0, 0, 0, 0)
    assert report.postponed == 1

    again = inbox.read()

    assert (again.alerts, again.offers) == (1, 4)


def test_an_account_without_profile_waits_with_its_reason(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        account_id = SqlAuthStore(connection).create_account(
            "sans-profil@example.com", NOW
        )
    service = _service(migrated_engine, FakePages())
    mailbox_id, _ = connect_mailbox(
        service.storage,
        cipher(),
        account_id=account_id,
        address="sans-profil@example.com",
        refresh_token="1//rafraichissement",
        now=NOW,
    )
    data = recorded_alert("hellowork_alerte")
    store_mail(
        service.storage,
        mailbox_id,
        sender=data["sender"],
        subject=data["subject"],
        body_html=data["body_html"],
        received_at=RECENT,
        found_by=Query.ALERTS,
    )
    service.classify(account_id, use_model=False)

    report = service.read_alerts(account_id)

    assert (report.postponed, report.reason) == (1, NO_PROFILE_REASON)


class _InjectedError(Exception):
    pass


# The writes of an alert: its reading, each offer (``record_offer``), each row of an offer, the event.
@pytest.mark.parametrize("fail_at", range(1, 5))
def test_a_failure_while_writing_an_alert_writes_nothing_of_it(
    inbox: Inbox, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    inbox.alert("hellowork_recommandation")
    inbox.service.classify(inbox.account_id, use_model=False)
    before = inbox.snapshot()
    _fail_at(monkeypatch, fail_at)

    with pytest.raises(_InjectedError):
        inbox.service.read_alerts(inbox.account_id)

    assert inbox.snapshot() == before
    monkeypatch.undo()
    assert inbox.service.read_alerts(inbox.account_id).alerts == 1


def test_the_failure_points_cover_every_write(
    inbox: Inbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test above injects a failure after each write of a one-card alert: there is none after the fourth."""
    inbox.alert("hellowork_recommandation")
    inbox.service.classify(inbox.account_id, use_model=False)
    _fail_at(monkeypatch, 5)

    assert inbox.service.read_alerts(inbox.account_id).alerts == 1


def _fail_at(monkeypatch: pytest.MonkeyPatch, n: int) -> None:
    """Raise at the ``n``-th write of the reading of the alerts."""
    counter = iter(range(1, 1000))
    writes: list[tuple[type, str]] = [
        (SqlStore, "add_reading"),
        (AlertOffersLink, "record"),
        (SqlStore, "add_alert_offer"),
        (SqlStore, "append_event"),
    ]
    for owner, name in writes:
        original: Callable[..., Any] = getattr(owner, name)

        def wrapped(
            *args: Any, __original: Callable[..., Any] = original, **kwargs: Any
        ) -> Any:
            result = __original(*args, **kwargs)
            if next(counter) == n:
                raise _InjectedError
            return result

        monkeypatch.setattr(owner, name, wrapped)
