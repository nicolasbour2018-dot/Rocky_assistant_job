"""The rules of the classification, without effects: senders, platforms, employers, sentences, signals, levels.

Decision ``docs/decisions/E2-classification.md``. Everything is compared in the folded form of the analysis (no case,
no accent, punctuation as spaces) and as **whole words**: never a fragment of a name in a fragment of an address,
which attached a Quora digest to « French bee » and a refusal from METRO to « Ministère de la justice » in the old
Rocky. Every proof quotes the message as written. ``classify`` decides what the rules can decide; the rest goes to the
language model (``Pending``), only when the message carries a sign of the job search (Q5, Q17).
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email.utils import parseaddr
from urllib.parse import urlsplit

from rocky.candidatures.model import MailTarget
from rocky.messages.classification.model import (
    Category,
    Context,
    Level,
    MailToClassify,
    Pending,
    Proof,
    Tier,
    Verdict,
)
from rocky.offres.analysis.text import Folded, evidence, find, fold, sentences
from rocky.offres.decisions import Author

# The body is read up to this many characters for the sentences of intent; the signals only in its head (Q17).
BODY_SCAN = 20_000
SIGNAL_HEAD = 2_000
MIN_NAME = 3  # a folded employer name shorter than this is never looked for
# The offer's title is found when most of its words are in the message; alone, it attaches with three words or more.
TITLE_OVERLAP = 0.6
MIN_TITLE_WORDS = 3

# Q16 (1): addresses that send nothing but job alerts.
ALERT_SENDERS = frozenset(
    {
        "jobalerts-noreply@linkedin.com",
        "offres@alertes.cadremploi.fr",
        "notification@emails.hellowork.com",
        "donotreply@match.indeed.com",
        "alert@indeed.com",
        "mailer@jobleads.com",
        "alerte@emails.hellowork.com",
        "recommandation@emails.hellowork.com",
    }
)

# Q16 (3) and the noise of the acceptance of E1: senders that never speak of the job search.
UNRELATED_SENDERS = frozenset(
    {
        "messages-noreply@linkedin.com",
        "invitations@linkedin.com",
        "security-noreply@linkedin.com",
        "billing-noreply@linkedin.com",
        "updates-noreply@linkedin.com",
        "notifications-noreply@linkedin.com",
        "messaging-digest-noreply@linkedin.com",
        "linkedin@em.linkedin.com",
        "calendar-notification@google.com",
        "no-reply@accounts.google.com",
        "newsletter@emails.hellowork.com",
        "noreply-accounts@google.com",
    }
)
UNRELATED_DOMAINS = frozenset(
    {
        "quora.com",
        "facebookmail.com",
        "pinterest.com",
        "waze.com",
        "github.com",
    }
)

# Q16 (2): addresses of platforms that relay alerts, their own notices and the employers' answers.
RELAY_SENDERS = frozenset(
    {
        "jobs-noreply@linkedin.com",
        "emploi@emails.hellowork.com",
        "contact@emails.hellowork.com",
        "info@emails.hellowork.com",
        "noreply@indeed.com",
        "safety-notifications@indeed.com",
        "jobs@free-work.com",
        "profile@free-work.com",
        "account@free-work.com",
        "contact@free-work.com",
        "yo@collective.work",
        "ops@collective.work",
        "ne-pas-repondre@meteojob.com",
        "emails@efinancialcareers.fr",
        "no-reply@welcometothejungle.com",
        "info@mail.cadremploi.fr",
        "info@cadremploi.fr",
        "feedback@invites.starred.com",
        "support@starred.com",
    }
)
# The employer writes through the platform: the name shown is the employer's (« ATHEIA <r-c-…@reply.hellowork.com> »).
EMPLOYER_RELAY_DOMAINS = frozenset({"reply.hellowork.com"})

# Q3: the tools employers send their answers with; the domain names the tool, never the employer.
ATS_DOMAINS = frozenset(
    {
        "ashbyhq.com",
        "greenhouse-mail.io",
        "greenhouse.io",
        "smartrecruiters.com",
        "join.com",
        "beetween-software.com",
        "digitalrecruiters.com",
        "recruitee.com",
        "jobs2web.com",
        "myworkday.com",
        "myworkdayjobs.com",
        "workday.com",
        "lever.co",
        "teamtailor.com",
        "teamtailor-mail.com",
        "welcomekit.co",
        "taleo.net",
        "successfactors.com",
        "successfactors.eu",
        "icims.com",
        "jobvite.com",
        "workable.com",
        "workablemail.com",
        "flatchr.io",
        "softy.pro",
        "talent-soft.com",
        "yello.co",
        "personio.de",
        "personio.com",
        "bamboohr.com",
        "breezy.hr",
        "werecruit.io",
        "jobaffinity.fr",
        "gestmax.fr",
        "starred.com",
    }
)
# Q3: the sites an offer's link may point to without naming the employer's domain.
JOB_BOARD_DOMAINS = frozenset(
    {
        "linkedin.com",
        "indeed.com",
        "welcometothejungle.com",
        "apec.fr",
        "hellowork.com",
        "cadremploi.fr",
        "adzuna.fr",
        "adzuna.com",
        "wellfound.com",
        "free-work.com",
        "meteojob.com",
        "francetravail.fr",
        "pole-emploi.fr",
        "jobteaser.com",
        "glassdoor.fr",
        "glassdoor.com",
        "monster.fr",
        "choisirleservicepublic.gouv.fr",
        "efinancialcareers.fr",
        "jobleads.com",
        "collective.work",
        "malt.fr",
        "remoteok.com",
    }
)
# Public suffixes of two labels met in the employers' addresses (``registrable``).
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "gouv.fr",
        "co.uk",
        "org.uk",
        "ac.uk",
        "com.au",
        "co.jp",
        "com.br",
        "co.in",
        "co.nz",
        "com.cn",
    }
)

# Q8: explicit sentences of intent, folded. The decisive ones settle a message; an acknowledgement or a progress note
# is only the courtesy around them (a refusal often begins « Nous avons bien reçu votre candidature… »).
DECISIVE_PHRASES: dict[Category, tuple[str, ...]] = {
    Category.REJECTION: (
        "ne donnerons pas suite",
        "ne pouvons pas donner suite",
        "ne pouvons donner suite",
        "ne pouvons pas donner une suite favorable",
        "pas donner une suite favorable",
        "pas ete retenue",
        "n est pas retenue",
        "candidature non retenue",
        "pas ete selectionne",
        "avons retenu un autre profil",
        "avons retenu une autre candidature",
        "avons retenu d autres candidat",
        "ne convient pas pour ce poste",
        "ne correspond pas a nos besoins",
        "ne correspond pas aux besoins",
        "malheureusement votre profil ne",
        "we regret to inform",
        "not moving forward",
        "not to move forward",
        "will not be moving forward",
        "move forward with other candidates",
        "pursue other candidates",
        "not been selected",
        "unable to offer you",
        "n irons pas plus loin",
        # Indeed's refusal: « X est désormais à l'étape suivante de son processus de recrutement et votre candidature… »
        "a l etape suivante de son processus de recrutement",
        "moved to the next step in their hiring process",
    ),
    Category.INTERVIEW: (
        "convocation a un entretien",
        "convier a un entretien",
        "proposer un entretien",
        "planifier un entretien",
        "organiser un entretien",
        "fixer un entretien",
        "disponibilites pour un entretien",
        "invitation a un entretien",
        "echange telephonique",
        "invite you to an interview",
        "schedule an interview",
        "schedule a call",
        "interview invitation",
    ),
    Category.ASSESSMENT: (
        "test technique",
        "cas pratique",
        "etude de cas",
        "test de recrutement",
        "technical test",
        "take home",
        "coding challenge",
        "online assessment",
    ),
    Category.OFFER: (
        "proposition d embauche",
        "offre d embauche",
        "promesse d embauche",
        "nous souhaitons vous recruter",
        "pleased to offer you",
        "offer letter",
    ),
}
COURTESY_PHRASES: dict[Category, tuple[str, ...]] = {
    Category.ACKNOWLEDGEMENT: (
        "bien recu votre candidature",
        "bonne reception de votre candidature",
        "candidature a bien ete recue",
        "candidature a bien ete enregistree",
        "candidature a bien ete transmise",
        "candidature a ete envoyee",
        "accuse de reception",
        "merci d avoir postule",
        "merci pour votre candidature",
        "merci de votre candidature",
        "remercions pour votre candidature",
        "remercions de votre candidature",
        "remercier d avoir postule",
        "remercions d avoir postule",
        "thank you for applying",
        "thank you for your application",
        "thanks for applying",
        "received your application",
    ),
    Category.EMPLOYER_UPDATE: (
        "candidature est en cours",
        "toujours en cours d etude",
        "en cours d examen",
        "under review",
    ),
}
# Subjects of job alerts from any sender (Q16: an alert address is surer, these only reach the medium level).
ALERT_SUBJECTS = (
    "nouvelles offres",
    "nouvelle offre",
    "new jobs",
    "job alert",
    "alerte emploi",
    "offres d emploi correspondant",
    "offres a ne rater",
    "opportunites correspondant",
    "dernieres opportunites",
    "offres d emploi basees sur",
    "offres d emploi selectionnees",
)
# Q17: expressions of the job search, in the subject or the head of the body; never a lone common word.
SEARCH_EXPRESSIONS = (
    "votre candidature",
    "vos candidatures",
    "your application",
    "entretien",
    "interview",
    "processus de recrutement",
    "recruitment process",
    "hiring process",
    "suite a votre candidature",
    "candidature au poste",
    "application for",
    "merci d avoir postule",
    "job opportunity",
)
# A refusal announced on a condition is the courtesy of an acknowledgement (« Sans retour de notre part sous 3
# semaines, vous pourrez considérer que votre candidature n'a pas été retenue »).
CONDITIONAL_MARKERS = (
    "sans retour",
    "sans reponse",
    "sans nouvelles",
    "si vous ne recevez pas",
    "si vous n avez pas",
    "if you do not hear",
    "if you don t hear",
    "if you have not heard",
    "if you haven t heard",
)
_LEGAL_FORMS = re.compile(r"\s(?:sas|sasu|sa|sarl|gmbh|inc|ltd|llc|s l|sl|group)$")
_TITLE_STOP_WORDS = frozenset(
    {
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "et",
        "en",
        "au",
        "aux",
        "the",
        "of",
        "and",
        "for",
        "in",
        "to",
    }
    | {"cdi", "cdd", "stage", "alternance", "freelance", "junior", "senior"}
)
_GENDER = re.compile(r"\s(?:h f|f h|m f|f m|h f x|f h x|m w d|f m d|m f d|x f h)\b.*$")


_ENTITY = re.compile(r"&(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);")


def readable(body: str) -> str:
    """The text part as written: some senders put HTML entities in it (« bien re&ccedil;u »), read decoded.
    The stored message is never changed (E1)."""
    return html.unescape(body) if _ENTITY.search(body) else body


def registrable(host: str) -> str:
    """The domain an organisation registers: ``talent.metro.de`` → ``metro.de``, ``x.finances.gouv.fr`` →
    ``finances.gouv.fr``. Two names are compared on it, never as substrings."""
    labels = [label for label in host.strip().lower().rstrip(".").split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    keep = 3 if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def _host(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _word_pattern(folded_term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(folded_term) + r"(?![a-z0-9])")


def _found(folded: Folded, term: str) -> tuple[int, int] | None:
    """The source span of ``term`` (already folded) in ``folded``, as whole words."""
    return next(find(folded, _word_pattern(term)), None)


def employer_domains(target: MailTarget) -> tuple[str, ...]:
    """Q3: the employer's domain typed in the dossier, and those of the offer's links that are neither a job board
    nor an ATS."""
    found: list[str] = []
    if target.employer_domain:
        found.append(registrable(target.employer_domain))
    for link in target.links:
        host = urlsplit(link).hostname or ""
        domain = registrable(host)
        if domain and domain not in JOB_BOARD_DOMAINS and domain not in ATS_DOMAINS:
            found.append(domain)
    return tuple(dict.fromkeys(found))


def name_forms(company: str) -> tuple[str, ...]:
    """The folded forms an employer's name is looked for under: as written, and without its legal form."""
    full = fold(company).text
    forms = [full, _LEGAL_FORMS.sub("", full)]
    return tuple(form for form in dict.fromkeys(forms) if len(form) >= MIN_NAME)


def title_form(title: str) -> str:
    """The folded title of an offer without its gender marks (« Data Analyst H/F » → « data analyst »)."""
    return _GENDER.sub("", fold(title).text).strip()


@dataclass(frozen=True)
class _Mail:
    """A message in the forms the rules read: its source text (subject, then body) folded, its head, its subject."""

    message: MailToClassify
    address: str
    domain: str
    shown_name: str
    source: str
    folded: Folded
    head: Folded
    subject: Folded

    @classmethod
    def of(cls, message: MailToClassify) -> _Mail:
        address = (message.sender_address or "").lower()
        source = f"{message.subject}\n{message.body_text[:BODY_SCAN]}"
        return cls(
            message=message,
            address=address,
            domain=registrable(_host(address)),
            shown_name=parseaddr(message.sender)[0],
            source=source,
            folded=fold(source),
            head=fold(f"{message.subject}\n{message.body_text[:SIGNAL_HEAD]}"),
            subject=fold(message.subject),
        )

    def quote(self, span: tuple[int, int]) -> str:
        return evidence(self.source, span, sentences(self.source).around(span[0]))

    @property
    def subject_excerpt(self) -> str:
        return self.message.subject.strip() or "(sans objet)"


@dataclass(frozen=True)
class _Match:
    target: MailTarget
    proof: Proof


def _by_domain(mail: _Mail, targets: Sequence[MailTarget]) -> list[_Match]:
    if not mail.domain or mail.domain in ATS_DOMAINS:
        return []
    return [
        _Match(
            target,
            Proof(
                Tier.DOMAIN,
                "employer.domain",
                mail.address,
                f"Domaine de l'expéditeur ({mail.domain}) = domaine de {target.company}.",
            ),
        )
        for target in targets
        if mail.domain in employer_domains(target)
    ]


def _by_name(
    targets: Sequence[MailTarget], places: Sequence[Folded], rule: str, reason: str
) -> list[_Match]:
    """The targets whose exact name, as whole words, is in one of ``places``."""
    found: list[_Match] = []
    for target in targets:
        place = next(
            (
                place
                for place in places
                for form in name_forms(target.company)
                if _found(place, form) is not None
            ),
            None,
        )
        if place is not None:
            found.append(
                _Match(
                    target,
                    Proof(
                        Tier.NAME,
                        rule,
                        place.source.strip()[:220],
                        reason.format(company=target.company),
                    ),
                )
            )
    return found


def _named(mail: _Mail, targets: Sequence[MailTarget], *, relay: bool) -> list[_Match]:
    """Q3: the applied employers the sender's domain, or the exact name shown or in the subject, designate. The name
    a platform shows is its own (« Hellowork »), never the employer's."""
    shown = () if relay else (fold(mail.shown_name),)
    places = [place for place in (*shown, mail.subject) if place.text]
    return _by_domain(mail, targets) + _by_name(
        targets, places, "employer.name", "Nom exact de l'employeur « {company} »."
    )


def title_words(title: str) -> frozenset[str]:
    return frozenset(
        word
        for word in title_form(title).split()
        if len(word) > 1 and word not in _TITLE_STOP_WORDS
    )


def _title_found(mail: _Mail, target: MailTarget) -> Proof | None:
    """The offer's title in the message: as it is, or most of its words (« Data Scientist- Blitz » for « Gaming Data
    Scientist- Blitz »)."""
    exact = title_form(target.title)
    span = _found(mail.folded, exact) if len(exact) >= MIN_NAME else None
    words = title_words(target.title)
    present = words & frozenset(mail.folded.text.split())
    if span is None and (not words or len(present) / len(words) < TITLE_OVERLAP):
        return None
    if span is not None:
        return Proof(
            Tier.NAME,
            "offer.title",
            mail.quote(span),
            f"Intitulé de l'offre « {target.title} » retrouvé dans le message.",
        )
    return Proof(
        Tier.NAME,
        "offer.title_words",
        mail.subject_excerpt,
        f"Les mots de l'intitulé « {target.title} » sont dans le message.",
    )


@dataclass(frozen=True)
class _Relay:
    """What the form of a platform's subject says: a category, the employer's name, the offer's title."""

    rule: str
    category: Category | None
    employer: str = ""
    title: str = ""


# Q16 (2): the subjects of the relaying platforms, folded, the most precise first. ``None``: the employer speaks.
_RELAY_FORMS: tuple[tuple[str, Category | None, re.Pattern[str]], ...] = tuple(
    (rule, category, re.compile(pattern))
    for rule, category, pattern in (
        (
            "relay.sent_to",
            Category.ACKNOWLEDGEMENT,
            r"candidature a ete envoyee a (?P<employer>.+)",
        ),
        (
            "relay.arrived",
            Category.ACKNOWLEDGEMENT,
            r"candidature est arrivee chez (?P<employer>.+)",
        ),
        (
            "relay.seen",
            Category.EMPLOYER_UPDATE,
            r"candidature a ete vue par (?P<employer>.+)",
        ),
        (
            "relay.answer",
            None,
            r"reponse de (?P<employer>.+?) pour l offre (?P<title>.+)",
        ),
        (
            "relay.news",
            None,
            r"des nouvelles de votre candidature pour (?P<employer>.+)",
        ),
        (
            "relay.withdrawn",
            Category.EMPLOYER_UPDATE,
            r"offre supprimee candidature chez (?P<employer>.+)",
        ),
        (
            "relay.closed",
            Category.EMPLOYER_UPDATE,
            r"l offre de (?P<title>.+) n est plus disponible",
        ),
        (
            "relay.problem",
            Category.EMPLOYER_UPDATE,
            r"probleme avec votre candidature au poste de (?P<title>.+)",
        ),
        (
            "relay.answer",
            None,
            r"suite a la reponse de (?P<employer>.+?) pour l offre (?P<title>.+)",
        ),
        (
            "relay.unfinished",
            Category.EMPLOYER_UPDATE,
            r"finalisez votre candidature sur le site de (?P<employer>.+)",
        ),
        (
            "relay.unfinished",
            Category.EMPLOYER_UPDATE,
            r"avez vous finalise votre candidature au poste de (?P<title>.+)",
        ),
        (
            "relay.closed",
            Category.EMPLOYER_UPDATE,
            r"offres auxquelles vous avez postule ne sont plus disponibles",
        ),
        (
            "relay.refusals",
            Category.REJECTION,
            r"reponses negatives de plusieurs recruteurs",
        ),
        (
            "relay.confirmed",
            Category.ACKNOWLEDGEMENT,
            r"confirmation de votre candidature",
        ),
        (
            "relay.sent_for",
            Category.ACKNOWLEDGEMENT,
            r"candidature pour (?P<title>.+) envoyee",
        ),
        (
            "relay.applied",
            Category.ACKNOWLEDGEMENT,
            r"^votre candidature (?P<title>.+) chez (?P<employer>.+)$",
        ),
        (
            "relay.similar",
            Category.JOB_ALERT,
            (
                r"offres d emploi similaires|deposez votre candidature|nouvelles? opportunites?"
                r"|dernieres opportunites|offre recommandee|n oubliez pas de postuler"
            ),
        ),
        ("relay.hiring", Category.JOB_ALERT, r"(?P<employer>.+) recrute\b"),
        (
            "relay.account",
            Category.UNRELATED,
            (
                r"code de verification|bienvenue|completez vos informations|verifiez vos informations"
                r"|recapitulatif|votre cv a ete consulte|votre cv est en ligne|disponibilite"
                r"|votre experience de candidature|diffusez votre cv|nouveautes|siren|rentree pro"
                r"|consulte votre cv"
            ),
        ),
    )
)
# « transmise à UCASE CONSULTING le 27/08 » in the body of Free-Work's confirmations.
_SENT_TO_IN_BODY = re.compile(r"transmise a (?P<employer>.+?) le \d")


def _relay(mail: _Mail) -> _Relay | None:
    if mail.address not in RELAY_SENDERS:
        return None
    for rule, category, pattern in _RELAY_FORMS:
        match = pattern.search(mail.subject.text)
        if match is None:
            continue
        groups = match.groupdict()
        employer = (groups.get("employer") or "").strip()
        if rule == "relay.confirmed":
            in_body = _SENT_TO_IN_BODY.search(mail.folded.text)
            employer = in_body["employer"].strip() if in_body else ""
        return _Relay(rule, category, employer, (groups.get("title") or "").strip())
    return None


def _by_relay(relay: _Relay, targets: Sequence[MailTarget]) -> list[_Match]:
    """The targets the platform's subject names: the employer's whole name, then the offer's title among them. An
    offer the employer's applications do not have is another one: nothing is attached."""
    named = (
        _by_name(
            targets,
            [fold(relay.employer)],
            "employer.name",
            "La plateforme nomme l'employeur « {company} ».",
        )
        if relay.employer
        else []
    )
    if not relay.title or (relay.employer and not named):
        return named
    wanted = title_form(relay.title)
    if len(wanted) < MIN_NAME or (
        not relay.employer and len(wanted.split()) < MIN_TITLE_WORDS
    ):
        return named
    pool = [match.target for match in named] or list(targets)
    return [
        _Match(
            target,
            Proof(
                Tier.NAME,
                "offer.title",
                relay.title,
                f"La plateforme nomme l'offre « {target.title} » ({target.company}).",
            ),
        )
        for target in pool
        if _same_title(title_form(target.title), wanted)
    ]


def _same_title(stored: str, quoted: str) -> bool:
    """A platform quotes the title as it is, or cut: « Business Analysis support Cash Management » for the offer
    « Business Analysis support Cash Management - Freelance »."""
    return bool(stored) and (
        stored == quoted or _found(fold(stored), quoted) is not None
    )


@dataclass(frozen=True)
class _Attachment:
    """The application the rules attach a message to, its proofs and its level; the candidates when several remain."""

    application_id: int | None = None
    proofs: tuple[Proof, ...] = ()
    level: Level = Level.MEDIUM
    candidates: tuple[MailTarget, ...] = ()


def _resolve(mail: _Mail, context: Context, named: list[_Match]) -> _Attachment:
    """Q9, Q11: the thread first, then the one employer named, its offer's title deciding between two applications.

    A platform's notices are no conversation: Gmail threads them by subject, so their thread lends nothing."""
    thread = context.threads.get((mail.message.mailbox_id, mail.message.thread_id))
    conversation = mail.address not in RELAY_SENDERS | ALERT_SENDERS
    if (
        conversation
        and thread is not None
        and any(t.application_id == thread for t in context.targets)
    ):
        proof = Proof(
            Tier.THREAD,
            "thread",
            mail.subject_excerpt,
            "Même fil de discussion qu'un message déjà rattaché à cette candidature.",
        )
        return _Attachment(thread, (proof,), Level.HIGH)
    unique: dict[int, _Match] = {}
    for match in named:
        unique.setdefault(match.target.application_id, match)
    if len(unique) > 1:
        # The title as it is first; most of its words only when no title is there as it is.
        titled = [
            (match, title)
            for match in unique.values()
            if (title := _title_found(mail, match.target)) is not None
        ]
        as_written = [(m, t) for m, t in titled if t.rule == "offer.title"]
        titled = as_written if len(as_written) == 1 else titled
        if len(titled) != 1:
            return _Attachment(candidates=tuple(m.target for m in unique.values()))
        match, title = titled[0]
        return _Attachment(
            match.target.application_id,
            (match.proof, title),
            Level.HIGH if match.proof.tier is Tier.DOMAIN else Level.MEDIUM,
        )
    if len(unique) == 1:
        match = next(iter(unique.values()))
        if match.proof.rule == "offer.title":  # the platform named the offer itself
            return _Attachment(
                match.target.application_id, (match.proof,), Level.MEDIUM
            )
        title = _title_found(mail, match.target)
        if title is not None:
            return _Attachment(
                match.target.application_id,
                (match.proof, title),
                Level.HIGH if match.proof.tier is Tier.DOMAIN else Level.MEDIUM,
            )
        missing = Proof(
            Tier.NAME,
            "offer.title_missing",
            mail.subject_excerpt,
            f"L'intitulé de la candidature (« {match.target.title} ») n'apparaît pas dans le message : "
            "le poste reste à vérifier.",
        )
        return _Attachment(
            match.target.application_id,
            (match.proof, missing),
            Level.MEDIUM if match.proof.tier is Tier.DOMAIN else Level.LOW,
        )
    exact = [
        target
        for target in context.targets
        if len(title_form(target.title).split()) >= MIN_TITLE_WORDS
        and _found(mail.folded, title_form(target.title)) is not None
    ]
    if len(exact) == 1:
        title = _title_found(mail, exact[0])
        if title is not None:
            return _Attachment(exact[0].application_id, (title,), Level.MEDIUM)
    return _Attachment()


@dataclass(frozen=True)
class _Intent:
    category: Category | None
    proofs: tuple[Proof, ...]
    contradictory: bool


def intent(mail: _Mail) -> _Intent:
    """Q8: the category an explicit sentence gives; two decisive categories contradict each other."""
    decisive: list[tuple[Category, Proof]] = []
    for category, phrases in DECISIVE_PHRASES.items():
        proof = _phrase(mail, category, phrases)
        if proof is not None:
            decisive.append((category, proof))
    if len(decisive) > 1:
        return _Intent(None, tuple(proof for _, proof in decisive), True)
    if decisive:
        category, proof = decisive[0]
        return _Intent(category, (proof,), False)
    for category, phrases in COURTESY_PHRASES.items():
        proof = _phrase(mail, category, phrases)
        if proof is not None:
            return _Intent(category, (proof,), False)
    return _Intent(None, (), False)


def _phrase(mail: _Mail, category: Category, phrases: Sequence[str]) -> Proof | None:
    for phrase in phrases:
        span = next(
            (
                span
                for span in find(mail.folded, _word_pattern(phrase))
                if category is not Category.REJECTION or not _conditional(mail, span)
            ),
            None,
        )
        if span is not None:
            return Proof(
                Tier.PHRASE,
                f"phrase.{category.value}",
                mail.quote(span),
                f"Phrase explicite : « {phrase} ».",
            )
    return None


def _conditional(mail: _Mail, span: tuple[int, int]) -> bool:
    start, end = sentences(mail.source).around(span[0])
    sentence = fold(mail.source[start:end])
    return any(_found(sentence, marker) is not None for marker in CONDITIONAL_MARKERS)


def _alert_subject(mail: _Mail) -> Proof | None:
    for phrase in ALERT_SUBJECTS:
        if _found(mail.subject, phrase) is not None:
            return Proof(
                Tier.PHRASE,
                "subject.alert",
                mail.subject_excerpt,
                f"Objet d'une alerte emploi : « {phrase} ».",
            )
    return None


def _expression(mail: _Mail) -> Proof | None:
    for expression in SEARCH_EXPRESSIONS:
        span = _found(mail.head, expression)
        if span is not None:
            source = mail.head.source
            return Proof(
                Tier.SIGNAL,
                "signal.expression",
                evidence(source, span, sentences(source).around(span[0])),
                f"Expression de recherche d'emploi : « {expression} ».",
            )
    return None


def _signals(
    mail: _Mail, relay: _Relay | None, attachment: _Attachment, named: bool
) -> tuple[Proof, ...]:
    """Q17: the signs of the job search that let the model read the message."""
    found: list[Proof] = []
    if mail.domain in ATS_DOMAINS or mail.domain in EMPLOYER_RELAY_DOMAINS:
        found.append(
            Proof(
                Tier.SIGNAL,
                "signal.ats",
                mail.address,
                f"Expéditeur d'un outil de recrutement ({mail.domain}).",
            )
        )
    if relay is not None and relay.category is None:
        found.append(
            Proof(
                Tier.SIGNAL,
                "signal.relay",
                mail.subject_excerpt,
                "La plateforme relaie un message d'employeur.",
            )
        )
    if named or attachment.application_id is not None:
        found.append(
            Proof(
                Tier.SIGNAL,
                "signal.employer",
                mail.subject_excerpt,
                "Un employeur candidaté est reconnu.",
            )
        )
    expression = _expression(mail)
    if expression is not None:
        found.append(expression)
    return tuple(found)


def _verdict(
    category: Category, level: Level, proof: Proof, application_id: int | None = None
) -> Verdict:
    return Verdict(category, application_id, level, Author.RULE, (proof,))


def classify(message: MailToClassify, context: Context) -> Verdict | Pending:
    """What the rules decide about ``message``, or what they found for the language model (``Pending``)."""
    mail = _Mail.of(message)
    targets = context.targets
    if mail.address in ALERT_SENDERS:
        return _verdict(
            Category.JOB_ALERT,
            Level.HIGH,
            Proof(
                Tier.SENDER,
                "sender.alert",
                mail.address,
                "Adresse qui n'envoie que des alertes emploi.",
            ),
        )
    relay = _relay(mail)
    named = (
        _by_relay(relay, targets)
        if relay is not None and (relay.employer or relay.title)
        else _named(mail, targets, relay=mail.address in RELAY_SENDERS)
    )
    if not named and (
        mail.address in UNRELATED_SENDERS or mail.domain in UNRELATED_DOMAINS
    ):
        return _verdict(
            Category.UNRELATED,
            Level.HIGH,
            Proof(
                Tier.SENDER,
                "sender.unrelated",
                mail.address,
                "Expéditeur qui ne parle pas de recherche d'emploi.",
            ),
        )
    if relay is not None and relay.category in (Category.JOB_ALERT, Category.UNRELATED):
        return _verdict(
            relay.category,
            Level.HIGH,
            Proof(
                Tier.PLATFORM,
                relay.rule,
                mail.subject_excerpt,
                "Objet de la plateforme : "
                + (
                    "une alerte emploi."
                    if relay.category is Category.JOB_ALERT
                    else "un avis sur ton compte."
                ),
            ),
        )
    attachment = _resolve(mail, context, named)
    found = intent(mail)
    category, category_proofs = found.category, found.proofs
    other_proofs: tuple[Proof, ...] = ()
    if relay is not None:
        relay_proof = Proof(
            Tier.PLATFORM,
            relay.rule,
            mail.subject_excerpt,
            "La plateforme relaie "
            + (
                "un message de l'employeur."
                if relay.category is None
                else "un avis sur une candidature."
            ),
        )
        if relay.category is not None:
            # The platform's own notice says what it is; its body may hold a survey's answers (« Non, ma
            # candidature n'a pas été retenue »), never the employer's decision.
            category, category_proofs = relay.category, (relay_proof,)
            found = _Intent(relay.category, (), False)
        else:
            other_proofs = (relay_proof,)
    proofs = category_proofs + other_proofs + attachment.proofs
    if category is not None and not attachment.candidates:
        return Verdict(
            category, attachment.application_id, attachment.level, Author.RULE, proofs
        )
    if (
        category is None
        and not found.contradictory
        and attachment.application_id is None
    ):
        alert = _alert_subject(mail)
        if alert is not None:
            return _verdict(Category.JOB_ALERT, Level.MEDIUM, alert)
    signals = _signals(mail, relay, attachment, bool(named))
    if category is None and not found.contradictory and not signals:
        return _verdict(
            Category.UNRELATED,
            Level.MEDIUM,
            Proof(
                Tier.SIGNAL,
                "signal.none",
                mail.subject_excerpt,
                "Aucun signal de recherche d'emploi (expéditeur, employeur ou expression).",
            ),
        )
    return Pending(
        candidates=attachment.candidates or tuple(targets),
        findings=proofs + signals,
        attached=attachment.application_id,
        attached_level=attachment.level,
        category=category,
    )
