"""What the step « Envoi » of an application shows, and how its forms are read back (decision D5): the revisions to
send, the form that confirms a sending, what was sent, and what the workstation will fill. No FastAPI here: the
routes are in ``web.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from rocky.candidatures.model import (
    CHANNEL_LABELS,
    Change,
    Channel,
    InvalidChangeError,
    LetterState,
    MessageVersion,
    NewSending,
    Prefill,
    Revision,
    RevisionKind,
    Sending,
    Stage,
)
from rocky.candidatures.rules import (
    is_stale,
    latest_revisions,
    proposed_channel,
    revision_filename,
    sending_in_force,
    sent_change,
)
from rocky.profil.model import Identity
from rocky.system.clock import paris_day

NONE = "aucun"  # the choice « without this document of Rocky » (Q5)
_KIND_ORDER = (RevisionKind.CV, RevisionKind.LETTER)


def revision_label(revision: Revision) -> str:
    if revision.kind is RevisionKind.CV:
        return "CV français" if revision.language == "fr" else "CV anglais"
    return "Lettre française" if revision.language == "fr" else "Lettre anglaise"


@dataclass(frozen=True)
class RevisionLine:
    revision: Revision
    label: str
    filename: str
    stale: bool = False  # the document has changed since (only said of the latest ones)
    sent: bool = False  # linked to the sending in force

    @property
    def short_hash(self) -> str:
        return self.revision.sha256[:8]


@dataclass(frozen=True)
class Sent:
    """What was sent: the sending in force, or a stage « Envoyée » confirmed before D5 (``linked`` False)."""

    on: date
    channel: str | None
    cv: RevisionLine | None
    letter: RevisionLine | None
    message: MessageVersion | None
    linked: bool


@dataclass(frozen=True)
class SendView:
    language: str
    current: tuple[
        RevisionLine, ...
    ]  # the latest CV and letter of the language, proposed for sending
    earlier: tuple[
        RevisionLine, ...
    ]  # every other revision, newest first: still downloadable (Q2)
    letter_note: str | None  # why no letter is generated with the CV
    stale: bool
    sent: Sent | None
    prefill: (
        Prefill | None
    )  # DORMANT: the latest form prefilled, while the application is « Préremplie »
    channel: Channel  # proposed from the link (Q3)
    message: MessageVersion | None  # in force in the language
    fields: tuple[
        tuple[str, str], ...
    ]  # (key of ``workstation.FIELDS``, value) the workstation will fill

    def lines(self, kind: RevisionKind) -> tuple[RevisionLine, ...]:
        """The revisions of ``kind``, newest first: the choices of the confirmation."""
        every = sorted(
            (*self.current, *self.earlier), key=lambda line: -line.revision.id
        )
        return tuple(line for line in every if line.revision.kind is kind)

    def latest(self, kind: RevisionKind) -> RevisionLine | None:
        return next((line for line in self.current if line.revision.kind is kind), None)


def send_view(
    *,
    language: str,
    revisions: Sequence[Revision],
    inputs: Mapping[RevisionKind, str | None],
    letter: LetterState,
    letter_in_language: bool,
    messages: Sequence[MessageVersion],
    changes: Sequence[Change],
    sendings: Sequence[Sending],
    prefills: Sequence[Prefill],
    stage: Stage | None,
    identity: Identity,
    apply_url: str,
) -> SendView:
    """``inputs``: what the CV and the letter of the language are made from now (None: they cannot be made), to tell
    a revision is stale; ``letter_in_language``: a letter is validated in the language."""
    in_force = sending_in_force(changes, sendings)
    sent_ids = (
        set()
        if in_force is None
        else {in_force.cv_revision_id, in_force.letter_revision_id}
    )

    def line(revision: Revision, *, current: bool = False) -> RevisionLine:
        return RevisionLine(
            revision=revision,
            label=revision_label(revision),
            filename=revision_filename(
                revision.kind, identity.full_name, revision.language
            ),
            stale=current and is_stale(revision, inputs.get(revision.kind)),
            sent=revision.id in sent_ids,
        )

    latest = latest_revisions(revisions, language)
    current = tuple(
        line(latest[kind], current=True) for kind in _KIND_ORDER if kind in latest
    )
    shown = {found.revision.id for found in current}
    earlier = tuple(
        line(revision)
        for revision in sorted(revisions, key=lambda found: -found.id)
        if revision.id not in shown
    )
    by_id = {found.revision.id: found for found in (*current, *earlier)}
    message = next((m for m in reversed(messages) if m.language == language), None)
    return SendView(
        language=language,
        current=current,
        earlier=earlier,
        letter_note=_letter_note(letter, letter_in_language, language),
        stale=any(found.stale for found in current),
        sent=_sent(changes, in_force, by_id, messages),
        prefill=prefills[-1] if prefills and stage is Stage.PREFILLED else None,
        channel=proposed_channel(apply_url),
        message=message,
        fields=prefill_fields(identity, message),
    )


def _letter_note(letter: LetterState, in_language: bool, language: str) -> str | None:
    if letter is LetterState.SKIPPED:
        return "Pas de lettre pour cette candidature : seul le CV est généré."
    if not in_language:
        adjective = "française" if language == "fr" else "anglaise"
        return f"Pas de lettre {adjective} validée : seul le CV est généré."
    return None


def _sent(
    changes: Sequence[Change],
    in_force: Sending | None,
    lines: Mapping[int, RevisionLine],
    messages: Sequence[MessageVersion],
) -> Sent | None:
    if in_force is None:
        change = sent_change(changes)
        if change is None:
            return None
        return Sent(paris_day(change.changed_at), None, None, None, None, linked=False)
    channel = CHANNEL_LABELS[in_force.channel]
    if in_force.channel_detail:
        channel = (
            in_force.channel_detail
            if in_force.channel is Channel.OTHER
            else f"{channel} ({in_force.channel_detail})"
        )
    return Sent(
        on=in_force.sent_on,
        channel=channel,
        cv=lines.get(in_force.cv_revision_id or 0),
        letter=lines.get(in_force.letter_revision_id or 0),
        message=next((m for m in messages if m.id == in_force.message_id), None),
        linked=True,
    )


# The confirmation of a sending (Q3, Q5).


@dataclass(frozen=True)
class ConfirmForm:
    """The form « J'ai envoyé ma candidature », as proposed or as the user left it."""

    sent_on: date
    channel: Channel
    detail: str
    cv: str  # a revision id, NONE, or "" (nothing chosen: no revision to propose)
    letter: str
    with_message: bool
    error: str | None = None


def confirm_form(
    view: SendView,
    today: date,
    submitted: Mapping[str, str] | None = None,
    error: str | None = None,
) -> ConfirmForm:
    """The latest revisions are checked by default (Q5); without any, nothing is: the user chooses."""
    cv, letter = view.latest(RevisionKind.CV), view.latest(RevisionKind.LETTER)
    proposed = ConfirmForm(
        sent_on=today,
        channel=view.channel,
        detail="",
        cv=str(cv.revision.id) if cv else "",
        letter=str(letter.revision.id) if letter else NONE,
        with_message=view.message is not None,
        error=error,
    )
    if submitted is None:
        return proposed
    try:
        sent_on = date.fromisoformat(submitted.get("date", ""))
    except ValueError:
        sent_on = proposed.sent_on
    channel = submitted.get("canal", "")
    return ConfirmForm(
        sent_on=sent_on,
        channel=Channel(channel) if channel in Channel else proposed.channel,
        detail=submitted.get("precision", ""),
        cv=submitted.get("cv", ""),
        letter=submitted.get("lettre", NONE),
        with_message="message" in submitted,
        error=error,
    )


def read_sending(form: Mapping[str, str], view: SendView) -> NewSending:
    """The sending as confirmed; refused with its reason (French). The use case checks that each document is the
    application's own."""
    try:
        sent_on = date.fromisoformat(form.get("date", ""))
    except ValueError as error:
        raise InvalidChangeError("Indique la date d'envoi.") from error
    if form.get("canal", "") not in Channel:
        raise InvalidChangeError("Choisis le canal d'envoi.")
    cv = form.get("cv", "")
    if not cv:
        raise InvalidChangeError(
            "Choisis le CV envoyé, ou « Sans document de Rocky » : génère d'abord tes PDF si besoin."
        )
    detail = " ".join(form.get("precision", "").split())
    return NewSending(
        sent_on=sent_on,
        channel=Channel(form["canal"]),
        channel_detail=detail or None,
        cv_revision_id=_revision_id(cv),
        letter_revision_id=_revision_id(form.get("lettre", NONE)),
        message_id=view.message.id
        if view.message is not None and "message" in form
        else None,
    )


def _revision_id(value: str) -> int | None:
    if value == NONE:
        return None
    if not (value.isascii() and value.isdigit()):
        raise InvalidChangeError("Document inconnu.")
    return int(value)


# What the workstation fills (Q4). DORMANT (decision D5, acceptance of 04/10): used by the prefilling only, kept
# but not run (``web.PREFILL_ENABLED``).

_LINK_HOSTS = {"linkedin.com": "linkedin", "github.com": "github"}


def prefill_fields(
    identity: Identity, message: MessageVersion | None
) -> tuple[tuple[str, str], ...]:
    """The values of the profile the workstation fills, by key of ``workstation.FIELDS``; the first link that is
    neither LinkedIn nor GitHub is the portfolio. Empty values are left out."""
    links: dict[str, str] = {}
    for link in identity.links:
        host = (urlsplit(link.url).hostname or "").lower()
        key = next(
            (
                name
                for domain, name in _LINK_HOSTS.items()
                if host == domain or host.endswith("." + domain)
            ),
            "portfolio",
        )
        links.setdefault(key, link.url)
    values = (
        ("full_name", identity.full_name),
        ("email", identity.contact_email or ""),
        ("phone", identity.phone or ""),
        ("city", identity.city or ""),
        ("postal_code", identity.postal_code or ""),
        ("linkedin", links.get("linkedin", "")),
        ("github", links.get("github", "")),
        ("portfolio", links.get("portfolio", "")),
        ("message", message.text if message else ""),
    )
    return tuple((key, value.strip()) for key, value in values if value.strip())
