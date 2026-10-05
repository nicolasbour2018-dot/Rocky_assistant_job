"""📈 Bilan minimal (decision F1, Q9): the sent applications as denominator; an acknowledgement is not an answer; a
cancelled change never counts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from rocky.candidatures.model import Change, ChangeKind, Stage
from rocky.candidatures.report import Report, report_of
from rocky.offres.decisions import Author

# Each change a day after the previous one; the first sending (a day after the creation) is on 30/09 at 22:30 UTC,
# 1 October in Paris.
START = datetime(2026, 9, 29, 22, 30, tzinfo=UTC)


class Dossier:
    """The changes of one application, written in order."""

    def __init__(self, application_id: int) -> None:
        self.application_id = application_id
        self.changes: list[Change] = []

    def add(
        self,
        kind: ChangeKind,
        stage: Stage | None = None,
        *,
        cancels: int | None = None,
    ) -> int:
        change_id = self.application_id * 100 + len(self.changes) + 1
        self.changes.append(
            Change(
                change_id,
                self.application_id,
                kind,
                Author.USER,
                START + timedelta(days=len(self.changes)),
                stage=stage,
                cancels=cancels,
            )
        )
        return change_id

    def created(self, *stages: Stage) -> Dossier:
        self.add(ChangeKind.CREATED, Stage.PREPARING)
        for stage in stages:
            self.add(ChangeKind.STAGE, stage)
        return self


def report(*dossiers: Dossier, acknowledged: frozenset[int] = frozenset()) -> Report:
    return report_of(((d.application_id, d.changes) for d in dossiers), acknowledged)


def test_nothing_sent_nothing_counted() -> None:
    found = report(
        Dossier(1).created(), Dossier(2).created(Stage.READY, Stage.WITHDRAWN)
    )

    assert found == Report(0, None, 0, 0, 0, 0)


def test_each_figure_has_the_sent_applications_as_denominator() -> None:
    found = report(
        Dossier(1).created(Stage.READY, Stage.SENT),
        Dossier(2).created(Stage.SENT),  # acknowledged only
        Dossier(3).created(
            Stage.SENT, Stage.REJECTED
        ),  # acknowledged, then refused: an answer
        Dossier(4).created(Stage.SENT, Stage.INTERVIEW, Stage.OFFER),
        Dossier(5).created(Stage.SENT, Stage.NO_RESPONSE),
        Dossier(6).created(Stage.READY),  # not sent
        acknowledged=frozenset({2, 3, 6}),
    )

    assert found == Report(
        sent=5,
        since=date(2026, 10, 1),
        acknowledged_only=1,
        answered=2,
        interviews=1,
        offers=1,
    )
    assert found.without_news == 2


def test_a_cancelled_change_never_counts() -> None:
    dossier = Dossier(1).created(Stage.SENT)
    interview = dossier.add(ChangeKind.STAGE, Stage.INTERVIEW)
    dossier.add(ChangeKind.CANCELLATION, cancels=interview)
    cancelled_creation = Dossier(2)
    creation = cancelled_creation.add(ChangeKind.CREATED, Stage.SENT)
    cancelled_creation.add(ChangeKind.CANCELLATION, cancels=creation)

    found = report(dossier, cancelled_creation)

    assert (found.sent, found.answered, found.interviews) == (1, 0, 0)
