"""Import use cases: a posting link gives a preview or the reason why it gives none, never silence.

Nothing is written (decision C2, Q1). A link to a platform whose pages show nothing to a plain reader (Apec) goes
through the public detail of its connector; any other link is read as a page.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Protocol

from rocky.offres.imports.model import (
    ImportMethod,
    ImportOutcome,
    ImportPreview,
    ImportResult,
)
from rocky.offres.imports.rules import check_link, parse_page
from rocky.offres.sources.http import Page
from rocky.offres.sources.model import (
    InvalidLinkError,
    JobSource,
    LinkSource,
    NotFoundError,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.offres.sources.rules import source_for_url

logger = logging.getLogger(__name__)

PASTE_HINT = "Tu peux coller la description de l'annonce ci-dessous."
NOT_FOUND_REASON = "L'annonce n'existe plus, ou le lien est faux (HTTP 404)."
TECHNICAL_REASON = (
    "Erreur technique pendant l'import (trace dans le journal de l'application)."
)


class PageReader(Protocol):
    def get_page(self, url: str) -> Page: ...


def link_sources(sources: Iterable[JobSource]) -> dict[str, LinkSource]:
    """The sources whose links are read through their detail endpoint, by source name."""
    return {source.code: source for source in sources if isinstance(source, LinkSource)}


def import_link(
    link: str,
    reader: PageReader,
    detail_sources: Mapping[str, LinkSource],
    *,
    today: date,
) -> ImportResult:
    """The preview of the posting at ``link``, or the reason why there is none."""
    try:
        address = check_link(link)
        platform = detail_sources.get(source_for_url(address) or "")
        if platform is not None:
            return ImportResult.ok(_from_platform(platform, address))
        page = reader.get_page(address)
        return ImportResult.ok(parse_page(page.html, page.url, today=today))
    except InvalidLinkError as error:
        return ImportResult.failure(ImportOutcome.INVALID, error.reason)
    except SourceRefusedError as error:
        return ImportResult.failure(
            ImportOutcome.REFUSED, f"{error.reason} {PASTE_HINT}"
        )
    except NotFoundError:
        return ImportResult.failure(ImportOutcome.FAILED, NOT_FOUND_REASON)
    except SourceFailedError as error:
        return ImportResult.failure(ImportOutcome.FAILED, error.reason)
    except Exception:
        # The link may carry personal tokens: it is not logged.
        logger.exception("import of a posting link failed unexpectedly")
        return ImportResult.failure(ImportOutcome.FAILED, TECHNICAL_REASON)


def _from_platform(platform: LinkSource, address: str) -> ImportPreview:
    # An empty detail leaves the offer as designated by its link: incomplete, with the reason set by ``from_link``.
    offer = platform.complete(platform.from_link(address))
    return ImportPreview(offer, ImportMethod.PLATFORM_DETAIL)
