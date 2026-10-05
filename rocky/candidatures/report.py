"""📈 Bilan minimal (decision F1, Q9, Q10): what became of the sent applications, each figure with its denominator.

An acknowledgement is not an answer (plan §8, D1 → F1): « accusé seul » counts the sent applications whose only news
is an acknowledgement. Everything is computed from the changes in force (a cancelled change never counts), without
a table; the acknowledgements come from the module ``messages`` through a port given by the composition.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from rocky.candidatures.model import Change, Stage
from rocky.candidatures.rules import standing
from rocky.system.scheduler import PARIS

# The applications of an account whose message in force is an acknowledgement (``messages``, given by the composition).
type Acknowledged = Callable[[int], frozenset[int]]

# Reaching one of these stages means the application was sent (« Retirée » alone does not: it may be withdrawn before).
SENT_STAGES = frozenset(
    {
        Stage.SENT,
        Stage.IN_DISCUSSION,
        Stage.INTERVIEW,
        Stage.OFFER,
        Stage.REJECTED,
        Stage.NO_RESPONSE,
    }
)
# An answer written by a person: a discussion, an interview, an offer or a refusal (Q9).
HUMAN_ANSWERS = frozenset(
    {Stage.IN_DISCUSSION, Stage.INTERVIEW, Stage.OFFER, Stage.REJECTED}
)


@dataclass(frozen=True)
class Report:
    sent: int
    # The day of the first sending (in Paris), None before it.
    since: date | None
    acknowledged_only: int
    answered: int
    interviews: int
    offers: int

    @property
    def without_news(self) -> int:
        """Sent, and neither an answer nor an acknowledgement."""
        return self.sent - self.answered - self.acknowledged_only


def report_of(
    found: Iterable[tuple[int, Sequence[Change]]], acknowledged: frozenset[int]
) -> Report:
    """``found``: each application with its changes; ``acknowledged``: the applications with an acknowledgement."""
    sent = acknowledged_only = answered = interviews = offers = 0
    first: date | None = None
    for application_id, changes in found:
        reached = [change for change in standing(changes) if change.stage is not None]
        stages = {change.stage for change in reached}
        sendings = [change for change in reached if change.stage in SENT_STAGES]
        if not sendings:
            continue
        sent += 1
        day = sendings[0].changed_at.astimezone(PARIS).date()
        first = day if first is None else min(first, day)
        if stages & HUMAN_ANSWERS:
            answered += 1
        elif application_id in acknowledged:
            acknowledged_only += 1
        interviews += Stage.INTERVIEW in stages
        offers += Stage.OFFER in stages
    return Report(sent, first, acknowledged_only, answered, interviews, offers)
