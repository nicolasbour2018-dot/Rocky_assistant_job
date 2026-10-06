"""The other modules as the decisions on the messages see them (decision E4): ports on their public functions, on the
connection of the transaction in progress. ``messages`` never reads their tables."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Connection

from rocky.candidatures import api as candidatures_api
from rocky.candidatures.model import Stage
from rocky.offres import api as offres_api
from rocky.offres.decisions import Author
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Profile


class CandidaturesLink:
    """``Applications`` on the public functions of ``candidatures``."""

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def stage(self, account_id: int, application_id: int) -> Stage | None:
        return candidatures_api.mail_stage(self._conn, account_id, application_id)

    def move(
        self,
        account_id: int,
        application_id: int,
        stage: Stage,
        *,
        author: Author,
        message_id: int,
        now: datetime,
        today: date,
    ) -> int | None:
        return candidatures_api.move_application_by_message(
            self._conn,
            account_id=account_id,
            application_id=application_id,
            stage=stage,
            author=author,
            message_id=message_id,
            now=now,
            today=today,
        )

    def in_force(self, account_id: int, application_id: int, change_id: int) -> bool:
        return candidatures_api.change_in_force(
            self._conn, account_id, application_id, change_id
        )

    def cancel(
        self, account_id: int, application_id: int, change_id: int, now: datetime
    ) -> bool:
        return candidatures_api.cancel_message_change(
            self._conn,
            account_id=account_id,
            application_id=application_id,
            change_id=change_id,
            now=now,
        )

    def learn_domain(
        self, account_id: int, application_id: int, domain: str, now: datetime
    ) -> bool:
        return candidatures_api.learn_employer_domain(
            self._conn,
            account_id=account_id,
            application_id=application_id,
            domain=domain,
            now=now,
        )

    def open_outside(
        self, account_id: int, offer_id: int, sent_on: date, now: datetime
    ) -> int:
        return candidatures_api.open_outside_application(
            self._conn,
            account_id=account_id,
            offer_id=offer_id,
            sent_on=sent_on,
            now=now,
        )


class OffresLink:
    """``Offers`` on the public functions of ``offres``, scored with the account's ``profile``."""

    def __init__(self, connection: Connection, profile: Profile) -> None:
        self._conn = connection
        self._profile = profile

    def record_message_offer(
        self,
        account_id: int,
        *,
        message_id: int,
        company: str,
        title: str,
        link: str,
        now: datetime,
        today: date,
    ) -> int:
        return offres_api.record_message_offer(
            self._conn,
            account_id=account_id,
            message_id=message_id,
            company=company,
            title=title,
            link=link,
            profile=self._profile,
            now=now,
            today=today,
        )


class AlertOffersLink:
    """``AlertOffers`` (decision E3) on the public functions of ``offres``, scored with the account's ``profile``."""

    def __init__(self, connection: Connection, profile: Profile) -> None:
        self._conn = connection
        self._profile = profile

    def complete_keys(
        self, account_id: int, keys: Iterable[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        return offres_api.complete_offer_keys(self._conn, account_id, keys)

    def try_lock(self, account_id: int) -> bool:
        return offres_api.try_lock_offers(self._conn, account_id)

    def record(
        self, account_id: int, offer: CollectedOffer, *, now: datetime, today: date
    ) -> tuple[int, bool]:
        return offres_api.record_alert_offer(
            self._conn,
            account_id=account_id,
            offer=offer,
            profile=self._profile,
            now=now,
            today=today,
        )
