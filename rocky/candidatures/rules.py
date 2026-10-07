"""Rules of the applications (D1): pure functions, without SQL nor side effect."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from rocky.candidatures.model import (
    BEFORE_SENDING,
    DEFAULT_LANGUAGE,
    DEFER_DAYS,
    FORWARD,
    ISSUES,
    PROPOSALS,
    Change,
    ChangeKind,
    Channel,
    Dossier,
    InvalidChangeError,
    LetterState,
    NextAction,
    Note,
    NoteRow,
    Revision,
    RevisionKind,
    Sending,
    Stage,
)

# The changes that set the next action: a creation and a stage change set it too (None: no action).
_SETS_ACTION = frozenset(
    {
        ChangeKind.CREATED,
        ChangeKind.STAGE,
        ChangeKind.NEXT_ACTION,
        ChangeKind.ACTION_DONE,
    }
)


def standing(rows: Iterable[Change]) -> list[Change]:
    """The changes not cancelled, in the order they were made."""
    ordered = sorted(rows, key=lambda row: row.id)
    cancelled = {row.cancels for row in ordered if row.kind is ChangeKind.CANCELLATION}
    return [
        row
        for row in ordered
        if row.kind is not ChangeKind.CANCELLATION and row.id not in cancelled
    ]


def dossier(rows: Iterable[Change]) -> Dossier:
    """The stage and the next action in force: those of the latest changes not cancelled.

    « Annuler » always cancels the latest change in force (``to_cancel``): a cancelled creation has no later change in
    force, and a new creation opens the application again (Q7).
    """
    changes = standing(rows)
    creation = next(
        (row for row in reversed(changes) if row.kind is ChangeKind.CREATED), None
    )
    stage = next((row.stage for row in reversed(changes) if row.stage), None)
    setter = next((row for row in reversed(changes) if row.kind in _SETS_ACTION), None)
    return Dossier(
        open=creation is not None,
        stage=stage if creation is not None else None,
        next_action=setter.next_action
        if setter is not None and creation is not None
        else None,
        creation=creation,
    )


def last_done(rows: Iterable[Change]) -> tuple[NextAction, NextAction | None] | None:
    """The action « Fait » and the one that followed it, when « Fait » is the latest change in force (decision D6,
    recette: the screen says what the gesture did)."""
    changes = standing(rows)
    if not changes or changes[-1].kind is not ChangeKind.ACTION_DONE:
        return None
    done = dossier(changes[:-1]).next_action
    return None if done is None else (done, changes[-1].next_action)


def done_message(done: NextAction, following: NextAction | None) -> str:
    """What the screen says after « Fait »: the action done, and what comes next."""
    said = f"« {done.label} » est fait."
    if following is None:
        return f"{said} Aucune prochaine action proposée : ajoute la suite quand tu la connais."
    return (
        f"{said} Prochaine action : {following.label} le "
        f"{following.due.strftime('%d/%m/%Y')}, à modifier ou différer si besoin."
    )


def to_cancel(rows: Iterable[Change]) -> Change | None:
    """The change that « Annuler » cancels: the latest one of the application still in force (Q6)."""
    changes = standing(rows)
    return changes[-1] if changes else None


def proposal(
    stage: Stage, today: date, deadline: date | None = None
) -> tuple[str, date | None] | None:
    """The next action proposed on reaching ``stage`` (Q3): its label and its date (None: a date to enter); None for
    an outcome. Before the sending, the date stops at the offer's ``deadline`` when it is not past (decision D6, Q8)."""
    proposed = PROPOSALS.get(stage)
    if proposed is None:
        return None
    due = None if proposed.days is None else today + timedelta(days=proposed.days)
    if (
        due is not None
        and deadline is not None
        and stage in BEFORE_SENDING
        and today <= deadline < due
    ):
        due = deadline
    return proposed.label, due


# Decision E4 (Q9): a message never gives the interview's date; the transition asks for it.
INTERVIEW_DATE_TO_SET = "Fixer la date de l'entretien"


def mail_next_action(stage: Stage, today: date) -> NextAction | None:
    """The next action set by a transition a message gave (decision E4): the proposal of the stage, and for an
    interview « Fixer la date de l'entretien » the next day (Q9); None for an outcome."""
    if stage is Stage.INTERVIEW:
        return NextAction(INTERVIEW_DATE_TO_SET, today + timedelta(days=1))
    proposed = proposal(stage, today)
    if proposed is None or proposed[1] is None:
        return None
    return NextAction(proposed[0], proposed[1])


def make_next_action(label: str | None, due: date | None) -> NextAction | None:
    """A next action as entered: both fields, or neither (no action)."""
    text = (label or "").strip()
    if not text and due is None:
        return None
    if not text:
        raise InvalidChangeError("Indique la prochaine action.")
    if due is None:
        raise InvalidChangeError("Indique la date de la prochaine action.")
    return NextAction(text, due)


def deferred(action: NextAction, days: int, today: date) -> NextAction:
    """The action put off by ``days``, from its date or from today when it is overdue (Q3)."""
    if days not in DEFER_DAYS:
        raise InvalidChangeError("Report inconnu.")
    return NextAction(action.label, max(action.due, today) + timedelta(days=days))


def is_overdue(action: NextAction | None, today: date) -> bool:
    return action is not None and action.due < today


def automatic_transition_allowed(current: Stage, proposed: Stage) -> bool:
    """Whether a rule or the AI (messages, E4) may move an application from ``current`` to ``proposed`` (Q5).

    Never backwards, never out of an outcome; the user moves freely.
    """
    if current in ISSUES:
        return False
    if proposed in ISSUES:
        return True
    return FORWARD.index(proposed) > FORWARD.index(current)


# The journey of the application's page (decision D3, Q25; D4, Q16): 1. CV, 2. Letter, 3. Sending.


class Step(StrEnum):
    CV = "cv"
    LETTER = "lettre"
    SEND = "envoi"
    FOLLOW = "suivi"  # decision D6, Q2


STEP_LABELS = {
    Step.CV: "CV",
    Step.LETTER: "Lettre",
    Step.SEND: "Envoi",
    Step.FOLLOW: "Suivi",
}


@dataclass(frozen=True)
class Journey:
    """Where the application stands on its page: the step to work on, the steps done, sent or closed."""

    current: Step  # « Suivi » once sent, or closed
    done: frozenset[Step]
    sent: bool
    closed: bool  # an outcome reached, or the creation cancelled


_SENT_OR_BEYOND = frozenset(
    {Stage.SENT, Stage.IN_DISCUSSION, Stage.INTERVIEW, Stage.OFFER}
)


def journey(stage: Stage | None, letter: LetterState = LetterState.NONE) -> Journey:
    """``stage``: the stage in force, None for an application whose creation is cancelled. The letter is done once
    one is validated or « Pas de lettre » chosen (D4, Q16); « Lettre prête » or « Pas de lettre » then leads to
    « Prête à envoyer ». An application made ready before D4 shows its letter not done."""
    if stage is None or stage in ISSUES:
        return Journey(Step.FOLLOW, frozenset(), sent=False, closed=True)
    letter_done = (
        frozenset({Step.LETTER}) if letter is not LetterState.NONE else frozenset()
    )
    if stage is Stage.PREPARING:
        if letter is LetterState.NONE:
            return Journey(Step.CV, frozenset(), sent=False, closed=False)
        return Journey(
            Step.LETTER, frozenset({Step.CV}) | letter_done, sent=False, closed=False
        )
    if stage in _SENT_OR_BEYOND:
        return Journey(
            Step.FOLLOW,
            frozenset({Step.CV, Step.SEND}) | letter_done,
            sent=True,
            closed=False,
        )
    return Journey(
        Step.SEND, frozenset({Step.CV}) | letter_done, sent=False, closed=False
    )


# The screen 📝 Candidatures (decision D6, Q1): tabs by stage, and « À faire » across them.


class Tab(StrEnum):
    TO_DO = "a-faire"
    TO_PREPARE = "a-preparer"
    PREPARING = "preparation"
    READY = "pretes"
    FOLLOW_UP = "suivi"
    CLOSED = "closes"


TAB_LABELS = {
    Tab.TO_DO: "À faire",
    Tab.TO_PREPARE: "À préparer",
    Tab.PREPARING: "En préparation",
    Tab.READY: "Prêtes à envoyer",
    Tab.FOLLOW_UP: "Suivi",
    Tab.CLOSED: "Closes",
}


def is_due(action: NextAction | None, today: date) -> bool:
    """The action is for today or overdue: the application is « À faire »."""
    return action is not None and action.due <= today


def stage_tab(stage: Stage) -> Tab:
    """The tab of an application by its stage; « À faire » shows it too while its action is due."""
    if stage is Stage.PREPARING:
        return Tab.PREPARING
    if stage in ISSUES:
        return Tab.CLOSED
    if stage in BEFORE_SENDING:
        return Tab.READY
    return Tab.FOLLOW_UP


def tabs_of(stage: Stage, action: NextAction | None, today: date) -> frozenset[Tab]:
    tabs = {stage_tab(stage)}
    if is_due(action, today):
        tabs.add(Tab.TO_DO)
    return frozenset(tabs)


# Notes and language of an application (decision D6, Q4, Q6).


def notes_in_force(rows: Iterable[NoteRow]) -> list[Note]:
    """The notes not removed, the latest first."""
    ordered = sorted(rows, key=lambda row: row.id)
    removed = {row.removes for row in ordered if row.removes is not None}
    return [
        Note(row.id, row.text, row.created_at)
        for row in reversed(ordered)
        if row.text is not None and row.id not in removed
    ]


def language_in_force(chosen: str | None) -> str:
    return chosen or DEFAULT_LANGUAGE


# The employer's e-mail domain (decision E2, Q3): what the replies are recognised by.
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def employer_domain(typed: str) -> str | None:
    """The domain typed in the dossier, as Rocky keeps it: « RH@Recrutement.Covea.fr », « https://www.covea.fr/ » →
    « recrutement.covea.fr », « covea.fr ». Empty → None (removed). Raises ``InvalidChangeError``."""
    value = typed.strip().lower()
    if not value:
        return None
    value = re.sub(r"^[a-z]+://", "", value).split("/", 1)[0]
    value = value.rsplit("@", 1)[-1].removeprefix("www.").rstrip(".")
    if len(value) > 253 or not _DOMAIN.match(value):
        raise InvalidChangeError(
            "Domaine invalide : écris par exemple « covea.fr » (la partie après le @ des e-mails de l'employeur)."
        )
    return value


# Revisions and sendings (decision D5).


def latest_revisions(
    revisions: Iterable[Revision], language: str
) -> dict[RevisionKind, Revision]:
    """The latest revision of each kind in ``language``: the one proposed for sending (Q2, Q5)."""
    latest: dict[RevisionKind, Revision] = {}
    for revision in sorted(revisions, key=lambda found: found.id):
        if revision.language == language:
            latest[revision.kind] = revision
    return latest


def is_stale_revision(revision: Revision, inputs_sha256: str | None) -> bool:
    """The document has changed since this revision was generated (None: it cannot be made any more)."""
    return inputs_sha256 != revision.inputs_sha256


def revision_filename(kind: RevisionKind, full_name: str, language: str) -> str:
    """The name the recruiter sees: ``CV_Camille_Martin_FR.pdf``, ``Lettre_Camille_Martin_EN.pdf``."""
    prefix = "CV" if kind is RevisionKind.CV else "Lettre"
    name = "_".join(full_name.split())
    return (
        f"{prefix}_{name}_{language.upper()}.pdf"
        if name
        else f"{prefix}_{language.upper()}.pdf"
    )


# Hosts of the job platforms (Q3); any other host is the company's own site.
_CHANNEL_HOSTS: Mapping[str, Channel] = {
    "linkedin.com": Channel.LINKEDIN,
    "indeed.com": Channel.INDEED,
    "indeed.fr": Channel.INDEED,
    "welcometothejungle.com": Channel.WELCOME_TO_THE_JUNGLE,
    "apec.fr": Channel.APEC,
    "hellowork.com": Channel.HELLOWORK,
    "francetravail.fr": Channel.FRANCE_TRAVAIL,
    "pole-emploi.fr": Channel.FRANCE_TRAVAIL,
}


def proposed_channel(url: str) -> Channel:
    """The channel proposed from the address of the application link (Q3): a platform by its exact domain or one
    of its subdomains, else the company's site; ``mailto:`` is an e-mail."""
    parts = urlsplit(url.strip())
    if parts.scheme == "mailto":
        return Channel.EMAIL
    host = (parts.hostname or "").lower()
    for domain, channel in _CHANNEL_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return channel
    return Channel.COMPANY_SITE


def sending_in_force(
    rows: Iterable[Change], sendings: Iterable[Sending]
) -> Sending | None:
    """The sending of the latest stage change « Envoyée » still in force; None once it is cancelled, or for a
    sending confirmed before D5 (a change « Envoyée » without sending)."""
    change = sent_change(rows)
    if change is None:
        return None
    return next((s for s in sendings if s.change_id == change.id), None)


def sent_change(rows: Iterable[Change]) -> Change | None:
    """The latest change « Envoyée » still in force, documented by a sending or not."""
    sent = [row for row in standing(rows) if row.stage is Stage.SENT]
    return sent[-1] if sent else None
