"""Import of a posting link: how its description was read, and the typed result shown to the user.

Nothing here is persisted (decision C2, Q1): the offer, its tracks and its score are written together by the watch
and the offers screen. Reasons are shown to the user, hence in French.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rocky.offres.sources.model import CollectedOffer


class ImportMethod(StrEnum):
    """Where the description of an imported offer comes from."""

    JSON_LD = "json_ld"
    TARGETED_HTML = "targeted_html"
    VISIBLE_TEXT = "visible_text"
    PLATFORM_DETAIL = "platform_detail"
    PASTED = "pasted"


METHOD_LABELS = {
    ImportMethod.JSON_LD: "données structurées de l'annonce",
    ImportMethod.TARGETED_HTML: "bloc de description de la page",
    ImportMethod.VISIBLE_TEXT: "texte visible de la page",
    ImportMethod.PLATFORM_DETAIL: "détail public de la plateforme",
    ImportMethod.PASTED: "description collée",
}


@dataclass(frozen=True)
class ImportPreview:
    offer: CollectedOffer
    method: ImportMethod
    warnings: tuple[str, ...] = ()


class ImportOutcome(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    REFUSED = "refused"
    FAILED = "failed"


@dataclass(frozen=True)
class ImportResult:
    """Either a preview (``ok``) or the reason why the link gave none."""

    outcome: ImportOutcome
    preview: ImportPreview | None = None
    reason: str | None = None

    @classmethod
    def ok(cls, preview: ImportPreview) -> ImportResult:
        return cls(ImportOutcome.OK, preview=preview)

    @classmethod
    def failure(cls, outcome: ImportOutcome, reason: str) -> ImportResult:
        return cls(outcome, reason=reason)


class InvalidPasteError(ValueError):
    """A pasted description that cannot be used as given; the message is shown to the user."""
