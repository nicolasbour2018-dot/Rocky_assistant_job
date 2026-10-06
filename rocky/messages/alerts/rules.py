"""Rules of the job alerts, without effects: the reader of each platform, the offer of a card, the merge with its
posting.

Decision ``docs/decisions/E3-alertes.md``. A reader is chosen by the exact address of the sender (as the platforms of
E2, Q16) and was written on a real alert (Q6). Facts are kept as written (no interpretation: the posting analysis reads
them, C3). The identity of a card is the same from one alert to the next: the platform's number when its link shows
it, else a key of its title, employer and place, folded.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import replace
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, NavigableString

from rocky.messages.alerts.model import (
    PLATFORM_LABELS,
    AlertCard,
    AlertMessage,
    Platform,
)
from rocky.messages.classification.rules import readable
from rocky.offres.analysis.text import fold
from rocky.offres.imports.rules import enriched
from rocky.offres.sources.model import CollectedOffer, SourceCode

# Q6: the addresses whose alerts have a reader (the alerts of E2, and the relays' alerts classified as such).
READERS: dict[str, Platform] = {
    "notification@emails.hellowork.com": Platform.HELLOWORK,
    "alerte@emails.hellowork.com": Platform.HELLOWORK,
    "recommandation@emails.hellowork.com": Platform.HELLOWORK,
    "offres@alertes.cadremploi.fr": Platform.CADREMPLOI,
    "emails@efinancialcareers.fr": Platform.EFINANCIALCAREERS,
    "jobalerts-noreply@linkedin.com": Platform.LINKEDIN,
    "jobs-noreply@linkedin.com": Platform.LINKEDIN,
}
# The source name of an offer of each platform (C1: a connector's code, else the host of the posting).
SOURCES = {
    Platform.HELLOWORK: "hellowork.com",
    Platform.CADREMPLOI: "cadremploi.fr",
    Platform.EFINANCIALCAREERS: "efinancialcareers.fr",
    Platform.LINKEDIN: SourceCode.LINKEDIN.value,
}

# The button that closes a card (Hellowork, Cadremploi), folded.
CARD_BUTTON = "voir l offre"
# Words of a contract as the platforms write them; a fact of a card that is one is its contract.
CONTRACT_WORDS = re.compile(
    r"^(cdi|cdd|interim|stage|alternance|apprentissage|freelance|independant|contrat [a-z ]+|"
    r"stage apprentissage|temps partiel|temps plein|vie|v i e)$"
)
REMOTE_WORDS = re.compile(r"^(hybride|teletravail.*|remote|full remote|a distance)$")
# Badges of a card that are not facts of the posting.
BADGES = frozenset(
    {
        "super recruteur",
        "recrutement actif",
        "candidature simplifiee",
        "promu",
        "nouveau",
        "voir l offre",
    }
)
LINKEDIN_JOB = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})")
LINKEDIN_PLACE = re.compile(r"^(?P<place>.*?)\s*\((?P<mode>[^)]*)\)\s*$")
EFC_LINK = re.compile(r"Postuler\s*:\s*(https?://\S+)")
EFC_JOB = re.compile(r"\.id(\d+)$")
SALARY_LINE = re.compile(r"^Salaire\s*:\s*", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_INVISIBLE = "‌​͏﻿­"


def reader_of(message: AlertMessage) -> Platform | None:
    return READERS.get((message.sender_address or "").lower())


def cards(message: AlertMessage, platform: Platform) -> list[AlertCard]:
    """The cards of an alert, in their order; an empty list when the reader finds none."""
    return _READERS[platform](message)


def card_offer(
    message: AlertMessage, card: AlertCard, platform: Platform, *, reason: str
) -> CollectedOffer:
    """The offer of a card: its facts as written, no description yet (``reason`` says why)."""
    external_id = card.platform_id or card_key(card)
    return CollectedOffer(
        source=SOURCES[platform],
        external_id=external_id,
        url=card.link or message_link(message, external_id),
        title=card.title,
        description="",
        description_complete=False,
        incomplete_reason=reason,
        company=card.company,
        location=card.location,
        contract=card.contract,
        remote=card.remote,
        salary_text=card.salary_text,
    )


def card_key(card: AlertCard) -> str:
    """The identity of a card without a platform number: the same title, employer and place in another alert of the
    platform give the same key (the tracking link changes every time)."""
    parts = (
        fold(value or "").text for value in (card.title, card.company, card.location)
    )
    return "card-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def merged(card_offer: CollectedOffer, page: CollectedOffer) -> CollectedOffer:
    """The offer of a card completed by its posting: the description and the facts the card lacks; it keeps the
    identity of the card (Q2) and takes the canonical address of the posting (found again by an import or a watch).
    A card has no description: an excerpt of its posting is better than none, and stays marked incomplete."""
    result = enriched(card_offer, page)
    if not result.description and page.description:
        result = replace(
            result,
            description=page.description,
            description_complete=page.description_complete,
            incomplete_reason=page.incomplete_reason,
        )
    return replace(result, url=page.url or card_offer.url)


def message_link(message: AlertMessage, card_id: str) -> str:
    """The alert in Gmail: the address of an offer whose card gives no link (an empty address is never stored), until
    the user gives the posting's. Its own to the card (H3): an offer is also found by its address, and two cards of an
    alert at the same one would be a single offer."""
    return (
        f"https://mail.google.com/mail/u/{quote(message.mailbox_address)}/?carte={quote(card_id)}"
        f"#all/{quote(message.gmail_id)}"
    )


def platform_label(platform: Platform | None) -> str:
    return "" if platform is None else PLATFORM_LABELS[platform]


# Readers


def _button_cards(message: AlertMessage) -> list[AlertCard]:
    """Hellowork and Cadremploi: a link on the title, the facts, then the button « Voir l'offre ». The facts are plain
    strings (the employer first; Cadremploi joins « employeur • lieu • contrat ») and links without address (Hellowork's
    place, contract and salary)."""
    soup = _soup(message.body_html)
    found: list[AlertCard] = []
    title: Tag | None = None
    facts: list[tuple[str, bool]] = []
    for node in soup.descendants:
        if isinstance(node, Tag) and node.name == "a":
            words = _clean(node.get_text(" ", strip=True))
            if fold(words).text == CARD_BUTTON:
                if title is not None:
                    found.append(_button_card(len(found) + 1, title, facts))
                title, facts = None, []
            elif words and _is_link(node):
                title, facts = node, []
        elif isinstance(node, NavigableString) and not isinstance(node, Comment):
            if title is None or node.find_parent("a") is title:
                continue
            value = _clean(str(node))
            if value:
                anchor = node.find_parent("a")
                facts.append((value, anchor is not None and not _is_link(anchor)))
    return found


def _button_card(position: int, title: Tag, facts: list[tuple[str, bool]]) -> AlertCard:
    company: str | None = None
    details: list[str] = []
    for value, in_anchor in facts:
        parts = [part.strip() for part in value.split("•") if part.strip()]
        if not in_anchor and company is None and parts:
            company, parts = parts[0], parts[1:]
        details.extend(parts)
    return _with_details(
        AlertCard(
            position=position,
            title=_clean(title.get_text(" ", strip=True)),
            company=company,
            link=_href(title),
        ),
        details,
    )


def _linkedin_cards(message: AlertMessage) -> list[AlertCard]:
    """LinkedIn: every link of a card leads to ``/jobs/view/<number>``; its strings are the title, then « employeur ·
    lieu (mode) », then badges. The link kept is the public posting, without any tracking parameter."""
    soup = _soup(message.body_html)
    strings: dict[str, list[str]] = {}
    for anchor in soup.find_all("a"):
        if not isinstance(anchor, Tag):
            continue
        match = LINKEDIN_JOB.search(_href(anchor) or "")
        if match is None:
            continue
        found = strings.setdefault(match.group(1), [])
        for value in anchor.stripped_strings:
            cleaned = _clean(value)
            if cleaned and cleaned not in found:
                found.append(cleaned)
    result: list[AlertCard] = []
    for number, written in strings.items():
        values = [value for value in written if fold(value).text not in BADGES]
        if not values:
            continue
        company, place, mode = None, None, None
        details: list[str] = []
        for value in values[1:]:
            if company is None and "·" in value:
                head, _, tail = value.partition("·")
                company = head.strip() or None
                where = LINKEDIN_PLACE.match(tail.strip())
                place = (where["place"] if where else tail.strip()) or None
                mode = where["mode"] if where else None
            else:
                details.append(value)
        result.append(
            _with_details(
                AlertCard(
                    position=len(result) + 1,
                    title=values[0],
                    company=company,
                    location=place,
                    remote=mode,
                    link=f"https://www.linkedin.com/jobs/view/{number}/",
                    platform_id=number,
                ),
                details,
            )
        )
    return result


def _efc_cards(message: AlertMessage) -> list[AlertCard]:
    """eFinancialCareers, by its text part: each card ends with « Postuler : <adresse>.id<n> ». Before it, the last
    paragraph with a place (« Paris, France ») names the posting: its title (« intitulé | employeur » in some forms),
    the employer (on its own line, or before the place), the place; what follows holds the facts (contract, remote
    work, salary)."""
    text = readable(message.body_text).replace("\r\n", "\n")
    result: list[AlertCard] = []
    start = 0
    for match in EFC_LINK.finditer(text):
        block = text[start : match.start()]
        start = match.end()
        paragraphs = [
            [_clean(line) for line in paragraph.split("\n") if _clean(line)]
            for paragraph in re.split(r"\n\s*\n", block)
        ]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        if not paragraphs:
            continue
        naming = next(
            (
                index
                for index in range(len(paragraphs) - 1, -1, -1)
                if any(_is_place(line) for line in paragraphs[index][1:])
            ),
            len(paragraphs) - 1,
        )
        link = match.group(1).split("?", 1)[0].rstrip(".,;)")
        number = EFC_JOB.search(urlsplit(link).path)
        card, details = _efc_naming(
            len(result) + 1,
            paragraphs[naming],
            link,
            number.group(1) if number else None,
        )
        details += [
            line for paragraph in paragraphs[naming + 1 :] for line in paragraph
        ]
        result.append(
            _with_details(card, [SALARY_LINE.sub("", line) for line in details])
        )
    return result


def _efc_naming(
    position: int, lines: list[str], link: str, number: str | None
) -> tuple[AlertCard, list[str]]:
    """The card named by ``lines``, and the lines left for its facts."""
    title, _, written = lines[0].partition(" | ")
    company: str | None = written.strip() or None
    place: str | None = None
    rest = lines[1:]
    at = next((index for index, line in enumerate(rest) if _is_place(line)), None)
    if at is not None:
        place = rest[at]
        if company is None and at > 0:
            company = rest[0]
        elif company is None and place.count(",") >= 2:
            # « Deloitte, Paris, France »: the employer before the place.
            head, _, place = place.partition(",")
            company, place = head.strip() or None, place.strip()
        rest = rest[at + 1 :]
    card = AlertCard(
        position=position,
        title=title.strip(),
        company=company,
        location=place,
        link=link,
        platform_id=number,
    )
    return card, rest


_READERS: dict[Platform, Callable[[AlertMessage], list[AlertCard]]] = {
    Platform.HELLOWORK: _button_cards,
    Platform.CADREMPLOI: _button_cards,
    Platform.EFINANCIALCAREERS: _efc_cards,
    Platform.LINKEDIN: _linkedin_cards,
}


# Helpers


def _with_details(card: AlertCard, details: list[str]) -> AlertCard:
    """The facts of a card sorted as written: salary (an amount, « € », « TJM »), contract, remote work, then the
    first other one is the place when the card has none."""
    salary, contract, remote, place = (
        card.salary_text,
        card.contract,
        card.remote,
        card.location,
    )
    for value in details:
        folded = fold(value).text
        if folded in BADGES or not folded:
            continue
        if (
            "€" in value
            or "tjm" in folded
            or folded in ("competitive", "selon le profil")
        ):
            salary = salary or value
        elif CONTRACT_WORDS.match(folded):
            contract = contract or value
        elif REMOTE_WORDS.match(folded):
            remote = remote or value
        elif place is None:
            place = value
    return replace(
        card, salary_text=salary, contract=contract, remote=remote, location=place
    )


def _is_place(value: str) -> bool:
    """A place as eFinancialCareers writes it: « Paris, France », « Neuilly-sur-Seine, France »."""
    return bool(re.search(r",\s*[A-ZÉ][\w' -]+$", value))


def _is_link(anchor: Tag) -> bool:
    return (_href(anchor) or "").startswith(("http://", "https://"))


def _href(anchor: Tag) -> str | None:
    value = anchor.get("href")
    return value.strip() if isinstance(value, str) else None


def _soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["style", "script", "head", "title"]):
        tag.decompose()
    return soup


def _clean(value: str) -> str:
    for character in _INVISIBLE:
        value = value.replace(character, "")
    return _SPACES.sub(" ", value.replace(" ", " ")).strip()
