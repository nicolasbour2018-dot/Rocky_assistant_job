"""What the step « Lettre » of an application shows, and how its form is read back (decision D4, Q7, Q11, Q14, Q17,
Q20; D6, Q3: one text per paragraph). No FastAPI here: the routes are in ``dossier_web.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from rocky.candidatures.letter import (
    CHECKS_VERSION,
    MESSAGE_LENGTH,
    WHY_YOU_LENGTH,
    Adaptation,
    Brief,
    clean_job_title,
    default_header,
    in_force,
    letter_state,
    make_header,
    signals,
    version_at,
)
from rocky.candidatures.model import (
    InvalidChangeError,
    LetterEntry,
    LetterHeader,
    LetterOrigin,
    LetterParagraph,
    LetterState,
    LetterVersion,
    MessageOrigin,
    MessageVersion,
    NewLetter,
    NewMessage,
)
from rocky.candidatures.targeting import cited_skills
from rocky.offres.analysis.model import IMPORTANCE_LABELS, PostingAnalysis
from rocky.offres.analysis.usecases import Summary
from rocky.offres.model import OfferHeading
from rocky.profil.letter import comparable, filled
from rocky.profil.model import (
    LETTER_ROLE_LABELS,
    CvLayout,
    LetterRole,
    Profile,
    StoredLetter,
)

ORIGINAL, ADAPTED, MINE = "original", "adapte", "mien"
ORIGIN_LABELS = {
    LetterOrigin.GENERIC: "ta lettre générique",
    LetterOrigin.ADAPTED: "version de Gemini",
    LetterOrigin.EDITED: "ta version",
}


@dataclass(frozen=True)
class LetterRow:
    """One paragraph of the form (D6, Q3): one text to edit, which the switch « Ta lettre · Gemini » replaces by the
    user's own paragraph or the adapted one when asked (D4, Q7, Q14)."""

    index: int
    role: str
    original: str  # the generic paragraph, for this offer
    adapted: str | None
    adapted_signals: tuple[str, ...]
    text: str  # the text kept, shown in the form
    mine: str = ""  # what the user wrote, kept while another version is shown (the switch brings it back)

    @property
    def choice(self) -> str:
        """Which version the text is: ORIGINAL, ADAPTED, or MINE (written by the user)."""
        return _version_of(self.text, self.original, self.adapted)

    @property
    def label(self) -> str:
        return LETTER_ROLE_LABELS[LetterRole(self.role)]

    @property
    def why_you(self) -> bool:
        return self.role == LetterRole.WHY_YOU.value


@dataclass(frozen=True)
class LetterView:
    language: str
    job: str
    company: str
    state: LetterState
    generic: (
        StoredLetter | None
    )  # None: no generic letter in this language (``refusal`` says why)
    refusal: str | None
    version: LetterVersion | None  # in force in this language
    header: LetterHeader  # in force, or proposed
    editing: bool
    rows: tuple[LetterRow, ...]
    adapted: bool  # the model's proposals are in the rows
    generic_changed: bool  # the generic letter changed since the version in force (Q17)
    english_outdated: bool  # the English generic letter comes from an older French one: warned, never refused
    sent_with: (
        LetterVersion | None
    )  # the version sent: of the revision sent (D5), or in force at the date (Q20)
    message: MessageVersion | None
    why_you: str  # of the version in force, for the message (Q12)


def job_and_company(offer: OfferHeading) -> tuple[str, str]:
    return clean_job_title(offer.title, offer.location), offer.company or ""


def letter_view(
    *,
    language: str,
    offer: OfferHeading,
    generic: StoredLetter | None,
    english_outdated: bool,
    entries: Sequence[LetterEntry],
    messages: Sequence[MessageVersion],
    sent_at: datetime | None,
    editing: bool,
    sent_letter_id: int | None = None,
    adaptation: Adaptation | None = None,
    reference: str = "",
    sources: str = "",
    submitted: Mapping[str, str] | None = None,
    switch: tuple[int, str] | None = None,
) -> LetterView:
    """``submitted``: the form as the user left it (« Aperçu », the switch): its texts and its header are kept;
    ``switch``: the version put in one paragraph (D6, Q3)."""
    job, company = job_and_company(offer)
    version = in_force(entries, language)
    refusal = None
    if generic is None:
        refusal = (
            "Prépare d'abord ta lettre anglaise dans Profil & kit."
            if language == "en"
            else "Importe d'abord ta lettre de motivation dans Profil & kit."
        )
    rows = (
        ()
        if generic is None
        else _rows(
            generic, version, adaptation, job, company, language, reference, sources
        )
    )
    header = (
        version.header
        if version is not None
        else default_header(language, job, company or None)
    )
    if submitted is not None:
        rows = with_form(rows, submitted)
        header = make_header(
            submitted.get("objet", ""), submitted.get("destinataire", ""), header
        )
    if switch is not None:
        rows = switched(rows, *switch)
    # The version of the revision sent (decision D5); before D5, the one in force when it was sent (D4, Q20).
    sent_with = next(
        (
            entry
            for entry in entries
            if isinstance(entry, LetterVersion)
            and entry.id == sent_letter_id
            and entry.language == language
        ),
        None if sent_at is None else version_at(entries, language, sent_at),
    )
    message = next((m for m in reversed(messages) if m.language == language), None)
    return LetterView(
        language=language,
        job=job,
        company=company,
        state=letter_state(entries),
        generic=generic,
        refusal=refusal,
        version=version,
        header=header,
        editing=generic is not None
        and (editing or adaptation is not None or version is None),
        rows=rows,
        adapted=adaptation is not None,
        generic_changed=version is not None
        and generic is not None
        and version.generic_sha256 != generic.sha256,
        english_outdated=language == "en" and english_outdated,
        sent_with=sent_with,
        message=message,
        why_you=_why_you(version),
    )


def _clean(text: str) -> str:
    return " ".join(text.split())


def _version_of(text: str, original: str, adapted: str | None) -> str:
    if text == original:
        return ORIGINAL
    if adapted is not None and text == adapted:
        return ADAPTED
    return MINE


def with_form(
    rows: Sequence[LetterRow], form: Mapping[str, str]
) -> tuple[LetterRow, ...]:
    """The rows as the user left them: the text of each paragraph, and what they wrote of their own."""
    kept = []
    for row in rows:
        text = _clean(form.get(f"texte_{row.index}", row.text))
        mine = _clean(form.get(f"mien_{row.index}", row.mine))
        if _version_of(text, row.original, row.adapted) == MINE:
            mine = text
        kept.append(replace(row, text=text, mine=mine))
    return tuple(kept)


SWITCHES = (ORIGINAL, ADAPTED, MINE)


def read_switch(value: str) -> tuple[int, str] | None:
    """``"3:adapte"`` → (3, ADAPTED); None for anything else."""
    index, _, version = value.partition(":")
    if not index.isdigit() or version not in SWITCHES:
        return None
    return int(index), version


def switched(
    rows: Sequence[LetterRow], index: int, version: str
) -> tuple[LetterRow, ...]:
    """The switch « Ta lettre · Gemini » (D6, Q3): that version becomes the paragraph's text; what the user wrote stays
    one click away (« Ta version »). A version the paragraph does not have changes nothing."""
    kept = []
    for row in rows:
        texts = {ORIGINAL: row.original, ADAPTED: row.adapted, MINE: row.mine}
        chosen = texts.get(version) if row.index == index else None
        if chosen is not None and (chosen or version == ORIGINAL):
            kept.append(replace(row, text=chosen))
        else:
            kept.append(row)
    return tuple(kept)


def adaptation_from_form(
    form: Mapping[str, str], generic: StoredLetter
) -> Adaptation | None:
    """The proposals the form carries back (« Aperçu »): nothing is asked of the model again."""
    found = {
        index: " ".join(form[f"adapte_{index}"].split())
        for index in range(len(generic.letter.paragraphs))
        if form.get(f"adapte_{index}", "").strip()
    }
    if not found:
        return None
    why = next(
        (
            index
            for index, paragraph in enumerate(generic.letter.paragraphs)
            if paragraph.role is LetterRole.WHY_YOU
        ),
        None,
    )
    why_you = found.pop(why, "") if why is not None else ""
    return Adaptation(why_you=why_you, paragraphs=found)


def preview_version(letter: NewLetter, now: datetime) -> LetterVersion:
    """A letter not validated yet, to preview it as it would be sent."""
    return LetterVersion(
        0, letter.language, letter.paragraphs, letter.header, letter.generic_sha256, now
    )


def _why_you(version: LetterVersion | None) -> str:
    if version is None:
        return ""
    return next(
        (p.text for p in version.paragraphs if p.role == LetterRole.WHY_YOU.value), ""
    )


def _current(
    generic: StoredLetter, version: LetterVersion | None
) -> tuple[LetterParagraph, ...] | None:
    """The paragraphs in force, when they still follow the generic letter's parts (Q17)."""
    if version is None:
        return None
    roles = [p.role.value for p in generic.letter.paragraphs]
    if [p.role for p in version.paragraphs] != roles:
        return None
    return version.paragraphs


def _rows(
    generic: StoredLetter,
    version: LetterVersion | None,
    adaptation: Adaptation | None,
    job: str,
    company: str,
    language: str,
    reference: str,
    sources: str,
) -> tuple[LetterRow, ...]:
    current = _current(generic, version)
    rows = []
    for index, paragraph in enumerate(generic.letter.paragraphs):
        original = filled(paragraph.text, job, company)
        why_you = paragraph.role is LetterRole.WHY_YOU
        adapted = None
        if adaptation is not None:
            adapted = (
                (adaptation.why_you or None)
                if why_you
                else adaptation.paragraphs.get(index)
            )
        in_force_text = current[index].text if current is not None else None
        if in_force_text is not None:
            text = in_force_text
        elif adapted is not None and why_you and not original:
            text = adapted  # an empty « pourquoi vous »: Gemini's is the only one
        else:
            text = original
        rows.append(
            LetterRow(
                index=index,
                role=paragraph.role.value,
                original=original,
                adapted=adapted,
                adapted_signals=()
                if adapted is None
                else _proposal_signals(
                    adapted, language, reference, sources, original, why_you
                ),
                text=text,
                mine=text if _version_of(text, original, adapted) == MINE else "",
            )
        )
    return tuple(rows)


def _proposal_signals(
    text: str,
    language: str,
    reference: str,
    sources: str,
    original: str,
    why_you: bool,
) -> tuple[str, ...]:
    """The checks of a proposal, and whether it only copies the user's paragraph (nothing to choose then)."""
    found = _signals(text, language, reference, sources, original, why_you)
    if original and comparable(text) == comparable(original):
        return ("Identique à ton paragraphe.", *found)
    return found


def _signals(
    text: str,
    language: str,
    reference: str,
    sources: str,
    original: str,
    why_you: bool,
) -> tuple[str, ...]:
    return signals(
        text,
        language=language,
        reference=reference,
        sources=sources,
        original=None if why_you else original,
        length=WHY_YOU_LENGTH if why_you else None,
    )


def read_letter(
    form: Mapping[str, str],
    *,
    language: str,
    generic: StoredLetter,
    entries: Sequence[LetterEntry],
    offer: OfferHeading,
    reference: str,
    sources: str,
) -> NewLetter:
    """The letter the user validated, from the form: each paragraph's text, where it comes from (the user's own
    paragraph, the adapted one, or their own writing: D6, Q3), what the model had proposed beside it, what the checks
    say of it (Q8, Q11)."""
    if form.get("empreinte") != generic.sha256:
        raise InvalidChangeError(
            "Ta lettre générique a changé pendant ce temps : recharge la page."
        )
    job, company = job_and_company(offer)
    current = _current(generic, in_force(entries, language))
    paragraphs = []
    for index, paragraph in enumerate(generic.letter.paragraphs):
        original = filled(paragraph.text, job, company)
        adapted = _clean(form.get(f"adapte_{index}", "")) or None
        why_you = paragraph.role is LetterRole.WHY_YOU
        previous = current[index] if current is not None else None
        text = _clean(
            form.get(
                f"texte_{index}", previous.text if previous is not None else original
            )
        )
        version = _version_of(text, original, adapted)
        if version == ORIGINAL:
            origin = LetterOrigin.GENERIC
        elif version == ADAPTED:
            origin = LetterOrigin.ADAPTED
        elif previous is not None and text == previous.text:
            origin = previous.origin
        else:
            origin = LetterOrigin.EDITED
        found = (
            ()
            if origin is LetterOrigin.GENERIC or not text
            else _signals(text, language, reference, sources, original, why_you)
        )
        paragraphs.append(
            LetterParagraph(paragraph.role.value, text, origin, adapted, found)
        )
    header = default_header(language, job, company or None)
    subject = " ".join(form.get("objet", "").split()) or header.subject
    recipient_lines = [
        " ".join(line.split()) for line in form.get("destinataire", "").splitlines()
    ]
    recipient = "\n".join(line for line in recipient_lines if line) or header.recipient
    return NewLetter(
        language=language,
        paragraphs=tuple(paragraphs),
        header=LetterHeader(subject, recipient),
        generic_sha256=generic.sha256,
        checks_version=CHECKS_VERSION,
    )


def read_message(
    text: str, proposed: str, *, language: str, reference: str, sources: str
) -> NewMessage:
    cleaned = " ".join(text.split())
    proposal = " ".join(proposed.split()) or None
    return NewMessage(
        language=language,
        text=cleaned,
        origin=MessageOrigin.GENERATED
        if proposal is not None and cleaned == proposal
        else MessageOrigin.EDITED,
        proposed=proposal,
        signals=message_signals(cleaned, language, reference, sources),
        checks_version=CHECKS_VERSION,
    )


def message_signals(
    text: str, language: str, reference: str, sources: str
) -> tuple[str, ...]:
    return signals(
        text,
        language=language,
        reference=reference,
        sources=sources,
        length=MESSAGE_LENGTH,
    )


def brief_of(
    *,
    language: str,
    offer: OfferHeading,
    profile: Profile,
    layout: CvLayout,
    analysis: PostingAnalysis,
    summary: Summary | None,
    interest: tuple[tuple[str, ...], str | None] | None,
    generic: StoredLetter | None,
) -> Brief:
    """What the model receives (Q15): the offer, why the user wants it, the proofs the CV targeting chose (D3), the
    generic letter for this offer."""
    job, company = job_and_company(offer)
    projects = {project.id: project.content for project in profile.projects}
    proofs = []
    for project_id in layout.projects[:3]:
        content = projects.get(project_id)
        if content is None:
            continue
        parts = [
            content.name.get(language) or content.name.fr,
            content.problem.get(language) or content.problem.fr,
            content.results.get(language) or content.results.fr,
        ]
        proofs.append(" : ".join(part for part in parts if part))
    shown = {s for group in layout.groups for s in group.skill_ids} | set(
        layout.transversal
    )
    labels = {skill.id: skill.label for skill in profile.skills}
    skills = tuple(
        f"{labels[skill_id].get(language) or labels[skill_id].fr} ({IMPORTANCE_LABELS[importance].lower()})"
        for skill_id, importance in cited_skills(profile, analysis).items()
        if skill_id in shown and skill_id in labels
    )
    reasons, note = interest if interest is not None else ((), None)
    return Brief(
        language=language,
        job=job,
        company=company,
        description=analysis.description,
        summary={}
        if summary is None
        else {
            "missions": summary.missions,
            "contexte": summary.context,
            "profil": summary.profile,
        },
        reasons=reasons,
        note=note or "",
        proofs=tuple(proofs),
        skills=skills,
        paragraphs=()
        if generic is None
        else tuple(
            (p.role.value, filled(p.text, job, company))
            for p in generic.letter.paragraphs
        ),
    )


def letter_reference(generic: StoredLetter | None) -> str:
    """The user's own letter: its typography and phrases are never flagged (Q8)."""
    if generic is None:
        return ""
    return "\n".join(p.text for p in generic.letter.paragraphs)
