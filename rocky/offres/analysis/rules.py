"""Analysis rules: no I/O, no side effect. A posting and the account's skills give a ``PostingAnalysis``.

Decision ``docs/decisions/C3-analyse.md``; conventions measured in ``docs/procedures/c3-mesure/``. Every fact keeps
the sentence it comes from. Source facts are decoded per source (``full_time`` is a permanent contract at Welcome to
the Jungle, a working time in JSON-LD); a code nobody knows stays empty.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from rocky.offres.analysis.model import (
    RULES_VERSION,
    AccountSkill,
    Condition,
    ConditionKind,
    ExperienceNeed,
    Importance,
    LanguageNeed,
    PostingAnalysis,
    Salary,
    SalaryPeriod,
    SkillMatch,
)
from rocky.offres.analysis.text import (
    Folded,
    Sentences,
    evidence,
    find,
    fold,
    formatted_description,
    headings,
    sentences,
    term_pattern,
)
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Contract, LanguageLevel, RemoteMode, SkillDraft
from rocky.profil.rules import normalize_term, skill_terms

# Importance markers, in comparison form (Q2). French first; English postings say the same.
_ELIMINATORY = re.compile(
    r"(?<![a-z0-9])(?:obligatoires?|indispensables?|requis|requises?|exigee?s?|exige"
    r"|imperati(?:f|fs|ve|ves)|required|essential|must ?haves?|mandatory)(?![a-z0-9])"
)
_PREFERRED = re.compile(
    r"(?<![a-z0-9])(?:un (?:vrai |gros |petit )?plus|(?:is|be) a (?:big |major |real |strong )?plus"
    r"|appreciee?s?|souhaitee?s?|souhaitable|atouts?|valorisee?s?|nice to haves?|preferred|bonus)(?![a-z0-9])"
)
# A marker denied just before it: "n'est pas requis", "not required", "aucune expérience … n'est requise".
_NEGATION = re.compile(
    r"(?:n est pas|ne sont pas|pas|non|not|no|aucune?)(?: [a-z0-9]+){0,8} $"
)
# "Python (obligatoire), SQL": a marker in brackets only concerns the word just before it.
_BRACKETED_MARKER = re.compile(r"\(\s*[^()]{0,25}\)")
_BRACKET_AFTER = re.compile(r"^\s*\(\s*([^()]{0,25})\)")
BEFORE_WINDOW = 150
AFTER_WINDOW = 130
# Sentences about applying, not about the job: never a requirement of the posting.
_APPLICATION = re.compile(
    r"(?<![a-z0-9])(?:cv|lettre de motivation|candidature|postuler|dossier)(?![a-z0-9])"
)

# Contracts written in the title or the text (comparison form).
_CONTRACT_WORDS: tuple[tuple[Contract, re.Pattern[str]], ...] = (
    (
        Contract.PERMANENT,
        re.compile(
            r"(?<![a-z0-9])(?:cdi|contrat a duree indeterminee|permanent contract|contrat permanent"
            r"|job type permanent|type de contrat permanent|permanent position)(?![a-z0-9])"
        ),
    ),
    (
        Contract.FIXED_TERM,
        re.compile(
            r"(?<![a-z0-9])(?:cdd|contrat a duree determinee|fixed term(?: contract)?)(?![a-z0-9])"
        ),
    ),
    (
        Contract.FREELANCE,
        re.compile(
            r"(?<![a-z0-9])(?:freelances?|free lance|tjm|taux journalier|independant"
            r"|type contract|contractor)(?![a-z0-9])"
        ),
    ),
    (
        Contract.INTERNSHIP,
        re.compile(
            r"(?<![a-z0-9])(?:stagiaire|internship|intern|offre de stage|stage de fin d etudes"
            r"|stage de \d+ mois)(?![a-z0-9])"
        ),
    ),
    (
        Contract.APPRENTICESHIP,
        re.compile(
            r"(?<![a-z0-9])(?:en alternance|contrat d alternance|poste en alternance|alternant|alternante"
            r"|contrat d apprentissage|contrat de professionnalisation|apprenticeship)(?![a-z0-9])"
        ),
    ),
    (
        Contract.INTERNATIONAL_VOLUNTEER,
        re.compile(r"(?<![a-z0-9])volontariat international(?![a-z0-9])"),
    ),
    (
        Contract.TEMPORARY,
        re.compile(
            r"(?<![a-z0-9])(?:interim|interimaire|mission d interim)(?![a-z0-9])"
        ),
    ),
)
# In a title, a bare word names the contract ("Stage Data Scientist", "Data Analyst - Alternance"); in a text it can
# be a past experience ("première expérience (stage, alternance ou premier emploi)").
_TITLE_ONLY: tuple[tuple[Contract, re.Pattern[str]], ...] = (
    (Contract.INTERNSHIP, re.compile(r"(?<![a-z0-9])stage(?![a-z0-9])")),
    (Contract.APPRENTICESHIP, re.compile(r"(?<![a-z0-9])alternance(?![a-z0-9])")),
)
# Written in the text but not the contract offered.
_NOT_THE_CONTRACT = re.compile(r"(?<![a-z0-9])cdi a la cle(?![a-z0-9])")
# Source facts, per source (lower case) or as JSON-LD codes (any source).
_SOURCE_CONTRACTS: Mapping[tuple[str, str], Contract] = {
    ("wttj", "full_time"): Contract.PERMANENT,
    ("wttj", "temporary"): Contract.FIXED_TERM,
    ("wttj", "internship"): Contract.INTERNSHIP,
    ("wttj", "apprenticeship"): Contract.APPRENTICESHIP,
    ("wttj", "freelance"): Contract.FREELANCE,
    ("wttj", "vie"): Contract.INTERNATIONAL_VOLUNTEER,
    ("adzuna", "permanent"): Contract.PERMANENT,
    ("wellfound", "contract"): Contract.FREELANCE,
    ("wellfound", "internship"): Contract.INTERNSHIP,
}
_JSON_LD_CONTRACTS = {
    "CONTRACTOR": Contract.FREELANCE,
    "INTERN": Contract.INTERNSHIP,
    "TEMPORARY": Contract.TEMPORARY,
}

# Remote work (comparison form). "Pas de full remote" says nothing of the mode.
_FULL_REMOTE = re.compile(
    r"(?<![a-z0-9])(?:full remote|fully remote(?:ly)?|100 remote|100 teletravail|teletravail (?:complet|total|a 100)"
    r"|remote first|remotely in|job remotely|work remotely|work from anywhere|entierement a distance"
    r"|remote global|remote worldwide)(?![a-z0-9])"
)
_NOT_FULL_REMOTE = re.compile(
    r"(?<![a-z0-9])(?:pas de|no|not) (?:full remote|fully remote)(?![a-z0-9])"
)
_HYBRID = re.compile(
    r"(?<![a-z0-9])(?:hybride?|hybrid work|teletravail partiel|flexibilite teletravail|teletravail flexible"
    r"|teletravail possible|teletravailler jusqu a \d+ jours?|\d+(?: (?:a|ou|to) \d+)? jours? de teletravail"
    r"|journees? de teletravail|teletravail \d+ jours?|\d+(?: (?:a|to) \d+)? days? (?:at|in) the office"
    r"|days? of in office|in office work|jours? (?:sur site|au bureau))(?![a-z0-9])"
)
_ON_SITE = re.compile(
    r"(?<![a-z0-9])(?:pas de teletravail|aucun teletravail|100 sur site|100 presentiel|no remote work|on site only"
    r"|fully on site)(?![a-z0-9])"
)
_SOURCE_REMOTE: Mapping[tuple[str, str], RemoteMode] = {
    ("wttj", "fulltime"): RemoteMode.FULL_REMOTE,
    ("wttj", "partial"): RemoteMode.HYBRID,
    ("wttj", "punctual"): RemoteMode.HYBRID,
    ("wttj", "no"): RemoteMode.ON_SITE,
    ("wellfound", "remote"): RemoteMode.FULL_REMOTE,
}

# Salary: an amount of money near a salary word; its period written around it, else deduced (Q5).
_AMOUNT = r"(\d{1,3}(?:[  \xa0.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_MONEY = re.compile(
    r"(?P<c1>[$€£])?\s?" + _AMOUNT + r"\s?(?P<k1>[kK](?![a-zA-Z]))?\s?(?P<c2>€|\$|£)?"
    r"(?:\s?(?:-|–|—|à|a|to)\s?(?P<c3>[$€£])?\s?"
    + _AMOUNT
    + r"\s?(?P<k2>[kK](?![a-zA-Z]))?)?"
    r"\s?(?P<c4>k€|€|\$|£|eur\b|euros?\b|usd\b|gbp\b)?",
    re.IGNORECASE,
)
_BIG_UNIT = re.compile(
    r"^\s?(?:m\b|md|mds|mn|million|milliard|billion|bn\b|b\b)", re.IGNORECASE
)
_SALARY_WORDS = re.compile(
    r"(?<![a-z0-9])(?:salaire|salary|remuneration|compensation|pay|package|tjm|taux journalier|fourchette"
    r"|brut|gross|base|ote|earnings|daily rate|day rate|rate|range)(?![a-z0-9])"
)
_PERIOD_WORDS: tuple[tuple[SalaryPeriod, re.Pattern[str]], ...] = (
    (
        SalaryPeriod.DAILY,
        re.compile(
            r"(?<![a-z0-9])(?:tjm|taux journalier|par jour|per day|daily|day rate|j)(?![a-z0-9])"
        ),
    ),
    (
        SalaryPeriod.HOURLY,
        re.compile(
            r"(?<![a-z0-9])(?:par heure|horaire|per hour|hourly|hr|h)(?![a-z0-9])"
        ),
    ),
    (
        SalaryPeriod.MONTHLY,
        re.compile(
            r"(?<![a-z0-9])(?:par mois|mensuel|mensuelle|per month|monthly|mois)(?![a-z0-9])"
        ),
    ),
    (
        SalaryPeriod.YEARLY,
        re.compile(
            r"(?<![a-z0-9])(?:par an|annuel|annuelle|per year|a year|annual|annually|yearly|an|year)(?![a-z0-9])"
        ),
    ),
)
_CURRENCIES = {
    "€": "EUR",
    "k€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
}
_UNIT_TEXT = {
    "HOUR": SalaryPeriod.HOURLY,
    "DAY": SalaryPeriod.DAILY,
    "WEEK": None,
    "MONTH": SalaryPeriod.MONTHLY,
    "YEAR": SalaryPeriod.YEARLY,
    "yearly": SalaryPeriod.YEARLY,
    "monthly": SalaryPeriod.MONTHLY,
    "daily": SalaryPeriod.DAILY,
    "hourly": SalaryPeriod.HOURLY,
}

# Years of experience asked of the candidate (comparison form); number words are read too ("two or more years").
_NUMBER_WORDS = {
    "zero": 0,
    "un": 1,
    "une": 1,
    "one": 1,
    "deux": 2,
    "two": 2,
    "trois": 3,
    "three": 3,
    "quatre": 4,
    "four": 4,
    "cinq": 5,
    "five": 5,
    "six": 6,
    "sept": 7,
    "seven": 7,
    "huit": 8,
    "eight": 8,
    "neuf": 9,
    "nine": 9,
    "dix": 10,
    "ten": 10,
}
_N = r"(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")"
_EXPERIENCE = (
    # "3 à 5 ans", "2-3 ans" (folded "2 3 ans"): the first number is the minimum.
    re.compile(
        _N
        + r"(?:(?: a| to| ou)? \d{1,2})? ans? (?:d |de |minimum|min)(?:experience|minimum|professionnelle)?"
    ),
    re.compile(r"(?:au moins|minimum|at least|minimum of) " + _N + r" (?:ans?|years?)"),
    re.compile(
        _N
        + r"(?: (?:to|or) \d{1,2})?(?: or more| plus)? years? (?:of )?(?:[a-z]+ ){0,6}experience"
    ),
    re.compile(_N + r" \d{0,2} ?years? (?:of )?(?:[a-z]+ ){0,6}experience"),
)
_EXPERIENCE_WORD = re.compile(r"(?<![a-z0-9])(?:experience|minimum|exp)(?![a-z0-9])")

# Languages (comparison form) and the words that make a mention a requirement.
_LANGUAGES = {
    "anglais": "en",
    "english": "en",
    "francais": "fr",
    "french": "fr",
    "espagnol": "es",
    "spanish": "es",
    "allemand": "de",
    "german": "de",
    "italien": "it",
    "italian": "it",
    "portugais": "pt",
    "portuguese": "pt",
    "neerlandais": "nl",
    "dutch": "nl",
    "arabe": "ar",
    "arabic": "ar",
    "chinois": "zh",
    "mandarin": "zh",
    "chinese": "zh",
    "japonais": "ja",
    "japanese": "ja",
    "russe": "ru",
    "russian": "ru",
    "polonais": "pl",
}
_LANGUAGE_NAME = re.compile(r"(?<![a-z0-9])(" + "|".join(_LANGUAGES) + r")(?![a-z0-9])")
_LANGUAGE_CUE = re.compile(
    r"(?<![a-z0-9])(?:courant|couramment|bilingue|professionnel|professionnelle|professional|maitrise|maitriser|niveau"
    r"|ecrit|oral|fluent|fluency|proficien(?:cy|t)|excellent|bon|bonne|good|strong|native|natif|parlez|parler"
    r"|speak|speaking|written|spoken|toeic|toefl|[abc][12])(?![a-z0-9])"
)
_LEVEL = re.compile(r"(?<![a-z0-9])([abc][12])(?![a-z0-9])")
_NATIVE = re.compile(
    r"(?<![a-z0-9])(?:langue maternelle|native|natif|native speaker)(?![a-z0-9])"
)
# Close enough to be about the language: "leader français de la distribution professionnelle" is not one.
LANGUAGE_WINDOW = 25

_CONDITIONS: tuple[tuple[ConditionKind, re.Pattern[str]], ...] = (
    (
        ConditionKind.NATIONALITY,
        re.compile(
            r"(?<![a-z0-9])(?:nationalite (?:francaise|europeenne|de l union europeenne|d un pays de l ue)"
            r"|ressortissants? (?:francais|europeens?|de l ue|de l union)|citoyennete (?:francaise|europeenne)"
            r"|work(?:ing)? authori[sz]ation|authori[sz]ed to work|right to work|eligible to work|permis de travail"
            r"|autorisation de travail"
            r"|(?:not|unable|cannot|can t|won t|will not|no|without)(?: [a-z]+){0,14} visa sponsorship"
            r"|visa sponsorship (?:is )?not (?:available|provided|offered))(?![a-z0-9])"
        ),
    ),
    (
        ConditionKind.CLEARANCE,
        re.compile(
            r"(?<![a-z0-9])(?:habilitation (?:secret|confidentiel|defense|de securite)|procedure d habilitation"
            r"|habilitable|secret defense|confidentiel defense|security clearance|habilite secret)(?![a-z0-9])"
        ),
    ),
    (
        ConditionKind.DRIVING_LICENCE,
        re.compile(
            r"(?<![a-z0-9])(?:permis b|permis de conduire|driving licen[cs]e|driver s licen[cs]e)(?![a-z0-9])"
        ),
    ),
)

_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_DEADLINE = re.compile(
    r"(?:date limite(?: de (?:candidature|depot|reponse))?|avant le|jusqu au|au plus tard le|deadline"
    r"|apply by|closing date|candidatures? (?:ouvertes? )?jusqu au) (?:le )?(\d{1,2})(?: er)? "
    r"(\d{1,2}|" + "|".join(_MONTHS) + r")(?: (\d{4}))?"
)


def account_skills(skills: Iterable[SkillDraft]) -> tuple[AccountSkill, ...]:
    """The account's skills and the names they answer to in a posting.

    A name "X (Y)" also answers to "X" and to "Y" (Q4): "Traitement du langage naturel (NLP)" is found as "NLP".
    """
    found: list[AccountSkill] = []
    for skill in skills:
        terms = set(skill_terms(skill))
        for name in (skill.label.fr, skill.label.en or "", *skill.aliases):
            bracket = re.fullmatch(r"\s*(.+?)\s*\(([^()]+)\)\s*", name)
            if bracket:
                terms.update(
                    term for part in bracket.groups() if (term := normalize_term(part))
                )
        found.append(AccountSkill(skill.label.fr, frozenset(terms)))
    return tuple(found)


@dataclass(frozen=True)
class _Posting:
    """The text the rules read: the title then the description, in both forms."""

    source: str
    folded: Folded
    sentences: Sentences
    headings: tuple[tuple[int, str], ...]
    title_length: int


def analyze(
    offer: CollectedOffer, skills: Iterable[AccountSkill], *, today: date
) -> PostingAnalysis:
    """The analysis of ``offer`` for an account: a pure function, it writes nothing."""
    description = formatted_description(offer.description)
    title = offer.title.strip()
    text = f"{title}\n{description}" if title else description
    posting = _Posting(text, fold(text), sentences(text), headings(text), len(title))
    matches = tuple(
        match for skill in skills if (match := _skill(posting, skill)) is not None
    )
    return PostingAnalysis(
        rules_version=RULES_VERSION,
        description=description,
        skills=matches,
        conditions=_conditions(posting),
        requirements=_requirements(posting, matches),
        contracts=_contracts(offer, posting),
        remote=_remote(offer, posting),
        salary=_salary(offer, posting),
        deadline=offer.deadline or _deadline(posting, today),
        experience=_experience(posting),
        languages=_languages(posting),
    )


# Skills and their importance.


def _skill(posting: _Posting, skill: AccountSkill) -> SkillMatch | None:
    best: SkillMatch | None = None
    for term in sorted(skill.terms, key=len, reverse=True):
        for span in find(posting.folded, term_pattern(term)):
            importance, sentence = _importance(posting, span)
            match = SkillMatch(
                skill.label,
                posting.source[span[0] : span[1]],
                importance,
                evidence(posting.source, span, sentence),
            )
            if best is None or _RANK[importance] > _RANK[best.importance]:
                best = match
    return best


_RANK = {Importance.DETECTED: 0, Importance.PREFERRED: 1, Importance.ELIMINATORY: 2}


def _importance(
    posting: _Posting, span: tuple[int, int]
) -> tuple[Importance, tuple[int, int]]:
    """The weight of a mention: a marker in brackets right after it, in its sentence nearby, or in its section."""
    source = posting.source
    sentence = posting.sentences.around(span[0])
    bracket = _BRACKET_AFTER.match(source[span[1] : span[1] + 30])
    if bracket:
        marked = _marker(normalize_term(bracket.group(1)))
        if marked is not None:
            return marked, sentence
    start = max(sentence[0], span[0] - BEFORE_WINDOW)
    end = min(sentence[1], span[1] + AFTER_WINDOW)
    # Markers in brackets belong to the word before them, not to this mention.
    context = (
        _BRACKETED_MARKER.sub(" ", source[start : span[0]])
        + " "
        + _BRACKETED_MARKER.sub(" ", source[span[1] : end])
    )
    marked = _marker(fold(context).text)
    if marked is not None:
        return marked, sentence
    heading = _heading_before(posting, span[0])
    if heading is not None:
        marked = _marker(normalize_term(heading))
        if marked is not None:
            return marked, sentence
    return Importance.DETECTED, sentence


def _marker(folded_context: str) -> Importance | None:
    for importance, pattern in (
        (Importance.ELIMINATORY, _ELIMINATORY),
        (Importance.PREFERRED, _PREFERRED),
    ):
        for match in pattern.finditer(folded_context):
            if not _NEGATION.search(
                folded_context[max(0, match.start() - 60) : match.start()]
            ):
                return importance
    return None


def _heading_before(posting: _Posting, position: int) -> str | None:
    """The heading of the section that holds ``position`` (the title is not a heading)."""
    current: str | None = None
    for start, text in posting.headings:
        if start > position:
            break
        if start > posting.title_length:
            current = text
    return current


def _requirements(
    posting: _Posting, matches: tuple[SkillMatch, ...]
) -> tuple[str, ...]:
    """Required sentences that name none of the account's skills ("Expérience impérative sur Informatica")."""
    covered = {
        match.evidence
        for match in matches
        if match.importance == Importance.ELIMINATORY
    }
    found: list[str] = []
    for start, end in posting.sentences.spans:
        folded = fold(posting.source[start:end]).text
        if _marker(folded) != Importance.ELIMINATORY or _APPLICATION.search(folded):
            continue
        quote = evidence(posting.source, (start, start), (start, end))
        if quote not in covered and quote not in found:
            found.append(quote)
    return tuple(found[:5])


# Conditions nothing makes up for.


def _conditions(posting: _Posting) -> tuple[Condition, ...]:
    """Conditions that nothing makes up for; "Permis B apprécié" is only a plus, not a condition."""
    found: list[Condition] = []
    for kind, pattern in _CONDITIONS:
        for span in find(posting.folded, pattern):
            importance, sentence = _importance(posting, span)
            if importance == Importance.PREFERRED:
                continue
            found.append(Condition(kind, evidence(posting.source, span, sentence)))
            break
    return tuple(found)


# Contract and remote work.


def _contracts(offer: CollectedOffer, posting: _Posting) -> tuple[Contract, ...]:
    """The contracts offered: the title's if it names one, else the text's and the source's."""
    title = normalize_term(offer.title)
    in_title = {
        contract
        for contract, pattern in (*_CONTRACT_WORDS, *_TITLE_ONLY)
        if pattern.search(title)
    }
    if in_title:
        return tuple(contract for contract in Contract if contract in in_title)
    text = _NOT_THE_CONTRACT.sub(" ", posting.folded.text)
    found = {contract for contract, pattern in _CONTRACT_WORDS if pattern.search(text)}
    found.update(_source_contracts(offer))
    return tuple(contract for contract in Contract if contract in found)


def _source_contracts(offer: CollectedOffer) -> set[Contract]:
    found: set[Contract] = set()
    for token in re.split(r"[\s,/]+", offer.contract or ""):
        if not token:
            continue
        decoded = _SOURCE_CONTRACTS.get(
            (offer.source, token.lower())
        ) or _JSON_LD_CONTRACTS.get(token)
        if decoded is None:
            folded = normalize_term(token)
            decoded = next(
                (
                    contract
                    for contract, pattern in _CONTRACT_WORDS
                    if pattern.fullmatch(folded)
                ),
                None,
            )
        if decoded is not None:
            found.add(decoded)
    return found


def _remote(offer: CollectedOffer, posting: _Posting) -> RemoteMode | None:
    """The source's fact when it is known, else the text: a denial first ("pas de télétravail possible"), then
    hybrid, which wins over a full-remote mention (often about the company, not the job)."""
    decoded = _SOURCE_REMOTE.get((offer.source, (offer.remote or "").strip().lower()))
    if decoded is not None:
        return decoded
    text = _NOT_FULL_REMOTE.sub(" ", posting.folded.text)
    if _ON_SITE.search(text):
        return RemoteMode.ON_SITE
    if _HYBRID.search(text):
        return RemoteMode.HYBRID
    if _FULL_REMOTE.search(text):
        return RemoteMode.FULL_REMOTE
    return None


# Salary.


@dataclass(frozen=True)
class _Money:
    minimum: float
    maximum: float
    currency: str | None
    period: SalaryPeriod | None
    span: tuple[int, int]


def _salary(offer: CollectedOffer, posting: _Posting) -> Salary | None:
    bounds = [
        value for value in (offer.salary_min, offer.salary_max) if value is not None
    ]
    if bounds:
        minimum, maximum = bounds[0], bounds[-1]
        written = _UNIT_TEXT.get(offer.salary_period or "")
        # The source gave the amounts: a bare number of the text ("TJM : 450-500") only tells their period.
        mention = next(
            (
                m
                for m in _money(posting, bare=True)
                if minimum in (m.minimum, m.maximum)
                or maximum in (m.minimum, m.maximum)
            ),
            None,
        )
        if written is None and mention is not None:
            written = mention.period
        quote = _quote(posting, mention.span) if mention else None
        return _made(minimum, maximum, offer.salary_currency, written, quote)
    mention = next(iter(_money(posting)), None)
    if mention is None:
        return None
    return _made(
        mention.minimum,
        mention.maximum,
        mention.currency,
        mention.period,
        _quote(posting, mention.span),
    )


def _made(
    minimum: float,
    maximum: float,
    currency: str | None,
    period: SalaryPeriod | None,
    quote: str | None,
) -> Salary:
    low, high = sorted((minimum, maximum))
    if period is not None:
        return Salary(low, high, currency, period, False, quote)
    return Salary(low, high, currency, deduced_period(low), True, quote)


def deduced_period(amount: float) -> SalaryPeriod:
    """The period an amount implies when none is written (Q5): ≤ 150 hourly, ≤ 2 000 daily, ≤ 15 000 monthly."""
    if amount <= 150:
        return SalaryPeriod.HOURLY
    if amount <= 2_000:
        return SalaryPeriod.DAILY
    if amount <= 15_000:
        return SalaryPeriod.MONTHLY
    return SalaryPeriod.YEARLY


def _money(posting: _Posting, *, bare: bool = False) -> list[_Money]:
    """Amounts of money that a salary word announces, in reading order.

    ``bare``: numbers without currency nor "k" count too (only to match amounts that the source gave).
    """
    found: list[_Money] = []
    source = posting.source
    for match in _MONEY.finditer(source):
        currency_mark = (
            match.group("c1")
            or match.group("c2")
            or match.group("c3")
            or match.group("c4")
        )
        kilo = (
            bool(match.group("k1") or match.group("k2"))
            or (match.group("c4") or "").lower() == "k€"
        )
        if not currency_mark and not kilo and not bare:
            continue
        if _BIG_UNIT.match(source[match.end() : match.end() + 10]):
            continue
        before = fold(source[max(0, match.start() - 80) : match.start()]).text
        after = fold(source[match.end() : match.end() + 20]).text
        if not _SALARY_WORDS.search(before):
            continue
        values = [_number(group) for group in (match.group(2), match.group(6)) if group]
        values = [value * 1000 if kilo and value < 1000 else value for value in values]
        if not values or min(values) <= 0:
            continue
        currency = (
            _CURRENCIES.get((currency_mark or "").lower()) if currency_mark else None
        )
        found.append(
            _Money(
                min(values),
                max(values),
                currency,
                _written_period(before[-30:], after[:15]),
                (match.start(), match.end()),
            )
        )
    return found


def _number(raw: str) -> float:
    """``46,000`` and ``46 000`` are forty-six thousand; ``11,52`` is eleven and a half."""
    compact = re.sub(r"[  \xa0]", "", raw)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", compact):
        return float(re.sub(r"[.,]", "", compact))
    groups = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)[.,](\d{1,2})", compact)
    if groups:
        return float(re.sub(r"[.,]", "", groups.group(1)) + "." + groups.group(2))
    return float(compact.replace(",", "."))


def _written_period(before: str, after: str) -> SalaryPeriod | None:
    for period, pattern in _PERIOD_WORDS:
        if pattern.search(after) or pattern.search(before):
            return period
    return None


def _quote(posting: _Posting, span: tuple[int, int]) -> str:
    return evidence(posting.source, span, posting.sentences.around(span[0]))


# Experience, languages, closing date.


def _experience(posting: _Posting) -> ExperienceNeed | None:
    """The most demanding minimum written for the candidate ("3 à 5 ans d'expérience" asks 3)."""
    best: tuple[int, tuple[int, int]] | None = None
    text = posting.folded.text
    for pattern in _EXPERIENCE:
        for match in pattern.finditer(text):
            window = text[match.start() : match.end() + 40]
            if not _EXPERIENCE_WORD.search(window):
                continue
            raw = match.group(1)
            years = _NUMBER_WORDS[raw] if raw in _NUMBER_WORDS else int(raw)
            if years > 30:
                continue
            if best is None or years > best[0]:
                best = (years, posting.folded.source_span(match.start(), match.end()))
    if best is None:
        return None
    return ExperienceNeed(best[0], _quote(posting, best[1]))


def _languages(posting: _Posting) -> tuple[LanguageNeed, ...]:
    found: dict[str, LanguageNeed] = {}
    text = posting.folded.text
    for match in _LANGUAGE_NAME.finditer(text):
        code = _LANGUAGES[match.group(1)]
        window = text[
            max(0, match.start() - LANGUAGE_WINDOW) : match.end() + LANGUAGE_WINDOW
        ]
        if code in found or not _LANGUAGE_CUE.search(window):
            continue
        span = posting.folded.source_span(match.start(), match.end())
        level_match = _LEVEL.search(window)
        level = (
            LanguageLevel(level_match.group(1))
            if level_match
            else (LanguageLevel.NATIVE if _NATIVE.search(window) else None)
        )
        found[code] = LanguageNeed(code, level, _quote(posting, span))
    return tuple(found.values())


def _deadline(posting: _Posting, today: date) -> date | None:
    match = _DEADLINE.search(posting.folded.text)
    if match is None:
        return None
    day, month_raw, year_raw = match.groups()
    month = _MONTHS.get(month_raw) or (int(month_raw) if month_raw.isdigit() else 0)
    try:
        return date(int(year_raw) if year_raw else today.year, month, int(day))
    except ValueError:
        return None
