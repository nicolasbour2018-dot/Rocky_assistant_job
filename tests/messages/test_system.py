"""What ⚙️ Système shows of the messages (decision F1, Q11): each mailbox and its last collection, the alerts by
platform; a mailbox to reconnect or a failed collection is a problem and takes the main action."""

from __future__ import annotations

from datetime import UTC, datetime

from rocky.messages.alerts.model import Platform, PlatformAlerts
from rocky.messages.model import (
    Mailbox,
    MailboxStatus,
    MailSync,
    SyncCounts,
    SyncStatus,
    Trigger,
)
from rocky.messages.service import MailboxView
from rocky.messages.web import (
    COLLECT_FROM_SYSTEM,
    CONNECT,
    RECONNECT,
    alerts_card,
    mailbox_card,
    platform_line,
)

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def view(
    status: MailboxStatus = MailboxStatus.CONNECTED,
    sync: SyncStatus | None = SyncStatus.COMPLETED,
    *,
    new: int = 3,
    reason: str | None = None,
) -> MailboxView:
    mailbox = Mailbox(1, 1, "camille@example.com", status, NOW, b"sealed")
    last = (
        None
        if sync is None
        else MailSync(
            1, 1, 1, Trigger.SCHEDULED, sync, NOW, NOW, NOW, reason, SyncCounts(new=new)
        )
    )
    return MailboxView(mailbox, last)


def test_without_a_mailbox_the_gesture_is_to_connect_one() -> None:
    card = mailbox_card([view(MailboxStatus.DISCONNECTED)])

    assert card.action == CONNECT
    assert not card.problem


def test_a_connected_mailbox_says_its_last_collection() -> None:
    card = mailbox_card([view()])

    assert card.details == (
        (
            "camille@example.com",
            "Connectée · dernier relevé le 05/10 à 14:00 : Terminée · 3 nouveaux messages",
        ),
    )
    assert (card.action, card.problem) == (COLLECT_FROM_SYSTEM, False)


def test_a_mailbox_to_reconnect_is_a_problem() -> None:
    card = mailbox_card([view(MailboxStatus.ACCESS_LOST, reason="Accès retiré")])

    assert (card.action, card.problem) == (RECONNECT, True)
    assert "À reconnecter" in card.details[0][1]
    assert "Accès retiré" in card.details[0][1]


def test_a_failed_collection_is_a_problem_and_a_running_one_is_followed() -> None:
    failed = mailbox_card([view(sync=SyncStatus.FAILED, reason="Gmail ne répond pas")])
    running = mailbox_card([view(sync=SyncStatus.RUNNING)])

    assert (failed.action, failed.problem) == (COLLECT_FROM_SYSTEM, True)
    assert (running.action, running.polling) == (None, True)
    assert "nouveau" not in running.details[0][1]


def test_the_alerts_are_told_by_platform() -> None:
    card = alerts_card(
        [
            PlatformAlerts(
                Platform.LINKEDIN, read=4, unread=1, offers=23, created=5, refused=2
            ),
            PlatformAlerts(None, unread=3),
        ]
    )

    assert card.details == (
        (
            "LinkedIn",
            "4 alertes lues · 1 non lue · 23 offres, dont 5 nouvelles · 2 fiches refusées",
        ),
        ("Formats non lus", "3 alertes sans lecteur"),
    )
    assert card.action is None


def test_no_alert_says_so() -> None:
    assert alerts_card([]).lines == ("Aucune alerte reçue ces derniers jours.",)
    assert platform_line(PlatformAlerts(Platform.HELLOWORK, read=1)) == "1 alerte lue"
