"""Text tools of the analysis, no I/O: readable description, comparison form with positions, sentences, sections.

The comparison form is the one of ``rocky.profil.rules.normalize_term`` (no case, no accent, every run of other
characters a single space), so that a term of the account is found as it is stored. Each character of that form
remembers its position in the description, so that the evidence quotes the posting as written.
"""

from __future__ import annotations

import html
import re
import unicodedata
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass

from rocky.offres.sources.rules import html_to_text

_KEPT = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_HTML_TAG = re.compile(
    r"</?(?:p|br|div|ul|ol|li|strong|b|em|i|h[1-6]|span|table|tr|td)\b[^>]*>",
    re.IGNORECASE,
)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_MD_BULLET = re.compile(r"^\s*[*+•]\s+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_STRONG = re.compile(r"(\*{1,3})(\S(?:.*?\S)?)\1")
_SPACES = re.compile(r"[ \t\xa0 ]+")
# Sentence ends: . ! ? ; followed by a space, an inline bullet ("chiffrées- Une", "à l'oral, - Capacité"), a line.
_SENTENCE_END = re.compile(
    r"(?<=[.!?;])\s+|(?<=\S)-\s+(?=[A-ZÀ-Ý])|\s-\s+(?=[A-ZÀ-Ý])|\n+"
)
EVIDENCE_LENGTH = 220


def formatted_description(raw: str) -> str:
    """The description as readable text: HTML and Markdown turned into lines and ``- `` bullets, nothing dropped."""
    text = raw or ""
    text = html_to_text(text) if _HTML_TAG.search(text) else html.unescape(text)
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = _MD_HEADING.sub("", raw_line)
        line = _MD_BULLET.sub("- ", line)
        line = _MD_LINK.sub(r"\1", line)
        line = _MD_STRONG.sub(r"\2", line)
        line = _SPACES.sub(" ", line).strip()
        # One blank line at most, and none between two bullets.
        if (
            lines
            and not lines[-1]
            and line.startswith("- ")
            and len(lines) > 1
            and lines[-2].startswith("- ")
        ):
            lines.pop()
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class Folded:
    """``text`` in comparison form; ``origin[i]`` is the position in ``source`` of the character ``text[i]``."""

    source: str
    text: str
    origin: tuple[int, ...]

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        """Positions in ``source`` of the folded characters ``start`` to ``end`` (excluded)."""
        return self.origin[start], self.origin[end - 1] + 1


def fold(source: str) -> Folded:
    characters: list[str] = []
    origin: list[int] = []
    space_pending = False
    for index, character in enumerate(source):
        decomposed = unicodedata.normalize("NFKD", character.casefold())
        for part in decomposed:
            if unicodedata.combining(part):
                continue
            if part in _KEPT:
                if space_pending and characters:
                    characters.append(" ")
                    origin.append(index)
                space_pending = False
                characters.append(part)
                origin.append(index)
            else:
                space_pending = True
    return Folded(source, "".join(characters), tuple(origin))


def term_pattern(term: str) -> re.Pattern[str]:
    """A folded term as whole words, the last one possibly plural ("dashboard" also finds "dashboards")."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"s?(?![a-z0-9])")


def find(folded: Folded, pattern: re.Pattern[str]) -> Iterator[tuple[int, int]]:
    """Source spans of every match of ``pattern`` in the folded text."""
    for match in pattern.finditer(folded.text):
        yield folded.source_span(match.start(), match.end())


@dataclass(frozen=True)
class Sentences:
    """Sentence spans of a text; a sentence never crosses a line."""

    spans: tuple[tuple[int, int], ...]

    def around(self, position: int) -> tuple[int, int]:
        starts = [start for start, _ in self.spans]
        index = max(bisect_right(starts, position) - 1, 0)
        return self.spans[index] if self.spans else (0, 0)


def sentences(source: str) -> Sentences:
    spans: list[tuple[int, int]] = []
    start = 0
    for separator in _SENTENCE_END.finditer(source):
        if separator.start() > start:
            spans.append((start, separator.start()))
        start = separator.end()
    if start < len(source):
        spans.append((start, len(source)))
    return Sentences(tuple(spans))


def evidence(source: str, span: tuple[int, int], sentence: tuple[int, int]) -> str:
    """The sentence that holds ``span``, cut around it to ``EVIDENCE_LENGTH`` characters."""
    start, end = sentence
    if end - start > EVIDENCE_LENGTH:
        middle = (span[0] + span[1]) // 2
        start = max(start, middle - EVIDENCE_LENGTH // 2)
        end = min(end, start + EVIDENCE_LENGTH)
    excerpt = _SPACES.sub(" ", source[start:end].replace("\n", " ")).strip()
    prefix = "…" if start > sentence[0] else ""
    suffix = "…" if end < sentence[1] else ""
    return f"{prefix}{excerpt}{suffix}"


def headings(source: str) -> tuple[tuple[int, str], ...]:
    """Positions and texts of the lines that open a section: short, not a bullet, ending with ":" or no full stop.

    "Compétences indispensables :" or "Preferred Qualifications:" give their weight to the lines that follow.
    """
    found: list[tuple[int, str]] = []
    position = 0
    for line in source.split("\n"):
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("- ")
            and len(stripped) <= 80
            and (
                stripped.endswith(":")
                or not stripped.endswith((".", "!", "?", ";", ","))
            )
        ):
            found.append((position, stripped))
        position += len(line) + 1
    return tuple(found)
