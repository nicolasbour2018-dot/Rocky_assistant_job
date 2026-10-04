"""« Vérifier mon CV » (decision D2, Q12): does each PDF reader find what the CV was meant to say?

Facts only, ported from the old ATS V3 (``dashboard/rocky/ats_v3.py``): three independent readers, the texts the CV
must carry (name, contact, section headings, titles, skills, projects, years), isolated letters, disagreement between
readers. No simulated recruiting software and no composite score: a fact is read by a reader, or it is not.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from rocky.profil.cv.content import CvContent
from rocky.system.pdf_read import Reading, read_pdf
from rocky.system.render import page_count

SPACED_LETTERS_RATIO = 0.25  # ATS V3: beyond, a reader sees letters, not words
MIN_AGREEMENT = 0.7


@dataclass(frozen=True)
class Fact:
    kind: str  # « Nom », « Section », « Compétence »… (French, shown)
    text: str


@dataclass(frozen=True)
class FactReading:
    fact: Fact
    found_by: tuple[str, ...]


@dataclass(frozen=True)
class ReaderSummary:
    reader: str
    words: int
    error: str | None


@dataclass(frozen=True)
class CvCheck:
    readers: tuple[ReaderSummary, ...]
    facts: tuple[FactReading, ...]
    agreement: float  # smallest word overlap between two readers (0–1)
    warnings: tuple[str, ...]

    @property
    def found_by_all(self) -> int:
        return sum(len(item.found_by) == len(self.readers) for item in self.facts)

    @property
    def readable(self) -> bool:
        return not self.warnings


def expected_facts(content: CvContent, headings: Sequence[str]) -> tuple[Fact, ...]:
    """What a reader must find in this CV; each text once."""
    facts = [
        Fact("Nom", content.full_name),
        Fact("Titre", content.title),
        Fact("E-mail", content.email or ""),
        Fact("Téléphone", content.phone or ""),
        *(Fact("Section", heading) for heading in headings),
    ]
    for kind, entries in (
        ("Expérience", content.experiences),
        ("Formation", content.education),
    ):
        for entry in entries:
            facts += [Fact(kind, entry.title), Fact(kind, entry.organisation)]
            facts += [
                Fact("Année", year) for year in re.findall(r"\d{4}", entry.period)
            ]
    facts += [
        Fact("Compétence", skill) for group in content.groups for skill in group.skills
    ]
    facts += [Fact("Compétence", skill) for skill in content.transversal]
    facts += [Fact("Projet", project.name) for project in content.projects]
    facts += [Fact("Langue", name) for name, _ in content.languages]
    seen: set[str] = set()
    kept = []
    for fact in facts:
        key = normalise(fact.text)
        if key and key not in seen:
            seen.add(key)
            kept.append(fact)
    return tuple(kept)


def check_cv(pdf: bytes, facts: Sequence[Fact], document: str = "le CV") -> CvCheck:
    """``document``: how the warnings name it (« la lettre » for an application's letter, decision D4, Q19)."""
    readings = read_pdf(pdf)
    working = [reading for reading in readings if reading.error is None]
    texts = {reading.reader: normalise(reading.text) for reading in working}
    fact_readings = tuple(
        FactReading(
            fact,
            tuple(r.reader for r in working if normalise(fact.text) in texts[r.reader]),
        )
        for fact in facts
    )
    agreement = _agreement([texts[r.reader] for r in working])
    return CvCheck(
        readers=tuple(
            ReaderSummary(r.reader, len(r.text.split()), r.error) for r in readings
        ),
        facts=fact_readings,
        agreement=agreement,
        warnings=_warnings(pdf, readings, fact_readings, agreement, document),
    )


def normalise(text: str) -> str:
    """Comparison form: case, typographic apostrophes, line breaks and hyphenation at a line end set aside."""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace("’", "'").replace("­", "")
    value = " ".join(value.split())
    return re.sub(r"(\w)- (\w)", r"\1-\2", value)


def spaced_letters_ratio(text: str) -> float:
    tokens = text.split()
    if not tokens:
        return 0.0
    return sum(len(token) == 1 and token.isalpha() for token in tokens) / len(tokens)


def _agreement(texts: Sequence[str]) -> float:
    words = [set(re.findall(r"\w+", text)) for text in texts]
    pairs = [
        len(a & b) / len(a | b)
        for index, a in enumerate(words)
        for b in words[index + 1 :]
        if a | b
    ]
    return min(pairs, default=1.0)


def _warnings(
    pdf: bytes,
    readings: Sequence[Reading],
    facts: Sequence[FactReading],
    agreement: float,
    document: str,
) -> tuple[str, ...]:
    warnings = []
    pages = page_count(pdf)
    if pages != 1:
        warnings.append(f"{document[0].upper()}{document[1:]} fait {pages} pages.")
    for reading in readings:
        if reading.error is not None:
            warnings.append(
                f"{reading.reader} n'a pas pu lire le PDF ({reading.error})."
            )
        elif not reading.text.strip():
            warnings.append(
                f"{reading.reader} ne trouve aucun texte : est-ce une image ?"
            )
        elif spaced_letters_ratio(reading.text) > SPACED_LETTERS_RATIO:
            warnings.append(
                f"{reading.reader} lit surtout des lettres isolées : l'espacement des lettres est trop large."
            )
    total = len([r for r in readings if r.error is None])
    for item in facts:
        if len(item.found_by) < total:
            missing = [
                r.reader
                for r in readings
                if r.error is None and r.reader not in item.found_by
            ]
            warnings.append(
                f"{item.fact.kind} « {item.fact.text} » : non lu par {', '.join(missing)}."
            )
    if agreement < MIN_AGREEMENT:
        warnings.append(
            f"Les lecteurs ne lisent pas le même texte (accord {agreement:.0%}) : "
            "ordre de lecture ou colonnes à vérifier."
        )
    return tuple(warnings)
