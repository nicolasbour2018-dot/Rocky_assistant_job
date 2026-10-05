"""Rules of the decisions on the messages (step E4): pure functions, without SQL nor side effect.

Decision ``docs/decisions/E4-decisions-ecran.md``: which stage a category gives (Q2), whether the transition is applied,
proposed or nothing (Q1, Q10), which rules and domains a correction may teach (Q7), how the messages of one application
are grouped (Q8).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from urllib.parse import quote

from rocky.candidatures.model import ISSUES, Stage
from rocky.candidatures.rules import automatic_transition_allowed
from rocky.messages.classification.model import (
    EMPLOYER_CATEGORIES,
    Category,
    Level,
    SortedMessage,
    StoredDecision,
)
from rocky.messages.classification.rules import (
    ALERT_SENDERS,
    ATS_DOMAINS,
    EMPLOYER_RELAY_DOMAINS,
    JOB_BOARD_DOMAINS,
    RELAY_SENDERS,
    UNRELATED_DOMAINS,
    registrable,
)
from rocky.messages.decisions.model import (
    RULE_CATEGORIES,
    MessageGroup,
    MessageRef,
    Outcome,
    TransitionPlan,
)
from rocky.offres.decisions import Author
from rocky.system.scheduler import PARIS

# Q2: the stage a category gives; an acknowledgement only proves the sending of an application « Préremplie ».
STAGE_BY_CATEGORY = {
    Category.REJECTION: Stage.REJECTED,
    Category.INTERVIEW: Stage.INTERVIEW,
    Category.ASSESSMENT: Stage.INTERVIEW,
    Category.OFFER: Stage.OFFER,
    Category.EMPLOYER_UPDATE: Stage.IN_DISCUSSION,
}

# Q7: the domains of public mail services; a recruiter writing from one of them does not name the employer's domain.
PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "outlook.fr",
        "hotmail.com",
        "hotmail.fr",
        "live.com",
        "live.fr",
        "msn.com",
        "yahoo.com",
        "yahoo.fr",
        "icloud.com",
        "me.com",
        "orange.fr",
        "wanadoo.fr",
        "free.fr",
        "sfr.fr",
        "neuf.fr",
        "laposte.net",
        "bbox.fr",
        "aol.com",
        "gmx.fr",
        "gmx.com",
        "proton.me",
        "protonmail.com",
    }
)

# Q8: the most decisive message of an application leads its group.
_DECISIVE = (
    Category.OFFER,
    Category.INTERVIEW,
    Category.ASSESSMENT,
    Category.REJECTION,
    Category.EMPLOYER_UPDATE,
    Category.PLATFORM_NOTICE,
    Category.ACKNOWLEDGEMENT,
)
# The categories a message keeps when the user creates its application from it (Q4); otherwise an acknowledgement.
ATTACHABLE = EMPLOYER_CATEGORIES | {Category.PLATFORM_NOTICE}


def target_stage(category: Category, current: Stage) -> Stage | None:
    """Q2: the stage ``category`` gives an application at ``current``; None when it gives none."""
    if category is Category.ACKNOWLEDGEMENT:
        return Stage.SENT if current is Stage.PREFILLED else None
    return STAGE_BY_CATEGORY.get(category)


def plan_transition(
    category: Category | None, level: Level, author: Author, current: Stage
) -> TransitionPlan | None:
    """What a decision gives its application at ``current``.

    Q1: a rule's decision of confidence high is applied, of confidence medium proposed, « À vérifier » nothing; a
    user's decision (correction, confirmation) is always proposed, applied by one more gesture. Q10: a transition a
    rule may not make is proposed when it leaves an outcome, nothing when it goes backwards.
    """
    if category is None or (level is Level.LOW and author is not Author.USER):
        return None
    stage = target_stage(category, current)
    if stage is None or stage is current:
        return None
    if automatic_transition_allowed(current, stage):
        applied = author is not Author.USER and level is Level.HIGH
        return TransitionPlan(Outcome.APPLIED if applied else Outcome.PROPOSED, stage)
    if current in ISSUES:
        return TransitionPlan(Outcome.PROPOSED, stage)
    return None


def _host(address: str | None) -> str:
    return address.rsplit("@", 1)[-1].lower() if address and "@" in address else ""


def rule_possible(address: str | None) -> bool:
    """Q7: « Toujours pour cet expéditeur » may be offered for this address: never a platform's alert or relay address,
    nor an ATS (they carry the answers of many employers)."""
    if not address:
        return False
    host = _host(address)
    return (
        address.lower() not in ALERT_SENDERS
        and address.lower() not in RELAY_SENDERS
        and host not in EMPLOYER_RELAY_DOMAINS
        and registrable(host) not in ATS_DOMAINS
    )


def rule_offered(address: str | None, category: Category) -> bool:
    """Q7: a rule for this address and this category may be made."""
    return category in RULE_CATEGORIES and rule_possible(address)


def domain_offered(address: str | None) -> str | None:
    """Q7: the employer's domain a correction may teach from the sender's address; None for a platform, an ATS, a job
    board or a public mail service."""
    if not address or not rule_possible(address):
        return None
    domain = registrable(_host(address))
    if not domain or domain in (
        ATS_DOMAINS | JOB_BOARD_DOMAINS | PUBLIC_MAIL_DOMAINS | UNRELATED_DOMAINS
    ):
        return None
    return domain


def paris_day(moment: datetime) -> date:
    """The day of ``moment`` in Paris (the user's day, D12)."""
    return moment.astimezone(PARIS).date()


def gmail_link(message: MessageRef) -> str:
    """The link of the message in Gmail (Q4: the offer of an application made outside Rocky points to its message)."""
    return f"https://mail.google.com/mail/u/{quote(message.mailbox_address)}/#all/{quote(message.gmail_id)}"


def quoted(message: MessageRef) -> str:
    """What a user's decision quotes of its message (the schema wants a quotation): its subject, else its sender."""
    return message.subject.strip() or message.sender.strip() or "(sans objet)"


def cited_employer(decision: StoredDecision | None) -> str | None:
    """Q4, E2 Q22: the employer a platform names in the message, as written."""
    if decision is None:
        return None
    return next(
        (proof.excerpt for proof in decision.proofs if proof.rule == "employer.cited"),
        None,
    )


# Q13 (acceptance): where a platform writes the title of the offer the user applied to, as written. The subject first,
# then the body (Hellowork: « "Finance Bi & Data Analyst H/F" pour l'entreprise GEODIS. », « Pour postuler à l'offre
# Data Analyst H/F, »).
_TITLE_FORMS = (
    re.compile(r"pour l['’]offre\s+(?P<title>[^\n]{2,150}?)\s*$", re.IGNORECASE),
    re.compile(
        r"candidature (?:au|pour le) poste (?:de |d['’])\s*(?P<title>[^\n]{2,150}?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"[\"“«]\s*(?P<title>[^\"”»\n]{2,150}?)\s*[\"”»]\s+pour l['’]entreprise",
        re.IGNORECASE,
    ),
    re.compile(r"postuler à l['’]offre\s+(?P<title>[^,\n]{2,150}?)\s*,", re.IGNORECASE),
)


def written_title(message: MessageRef) -> str | None:
    """Q13: the title of the offer as the platform writes it in the message (subject, then body), None when it writes
    none Rocky can read."""
    for place in (message.subject, message.body_text):
        for line in place.splitlines():
            for form in _TITLE_FORMS:
                found = form.search(" ".join(line.split()))
                if found is not None:
                    return found["title"].strip(" .")
    return None


def _rank(message: SortedMessage) -> int:
    category = None if message.decision is None else message.decision.category
    return _DECISIVE.index(category) if category in _DECISIVE else len(_DECISIVE)


def grouped(messages: Iterable[SortedMessage]) -> list[MessageGroup]:
    """Q8: the messages (the latest first) in groups, one per application, in the order of their latest message; the
    most decisive message leads (ties: the latest). A message without an application is a group of its own."""
    groups: dict[int, list[SortedMessage]] = {}
    order: list[int | SortedMessage] = []
    for message in messages:
        application_id = (
            None if message.decision is None else message.decision.application_id
        )
        if application_id is None:
            order.append(message)
            continue
        if application_id not in groups:
            groups[application_id] = []
            order.append(application_id)
        groups[application_id].append(message)
    result: list[MessageGroup] = []
    for item in order:
        if isinstance(item, int):
            members = groups[item]
            head = min(members, key=_rank)
            result.append(
                MessageGroup(
                    head, tuple(member for member in members if member is not head)
                )
            )
        else:
            result.append(MessageGroup(item))
    return result
