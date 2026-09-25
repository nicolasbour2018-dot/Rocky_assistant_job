from __future__ import annotations

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import (
    SOURCE_LABELS,
    Availability,
    DetailSource,
    SourceCode,
)
from rocky.offres.sources.registry import build_sources
from rocky.system.config import SourcesSettings


def test_every_platform_is_built_once_in_a_stable_order() -> None:
    sources = build_sources(SourcesSettings(), PublicHttp())

    assert [source.code for source in sources] == list(SourceCode)
    assert set(SOURCE_LABELS) == set(SourceCode)


def test_availability_follows_the_settings() -> None:
    bare = {
        source.code: source.availability()
        for source in build_sources(SourcesSettings(), PublicHttp())
    }
    keyed = {
        source.code: source.availability()
        for source in build_sources(
            SourcesSettings(adzuna_app_id="id", adzuna_app_key="key"), PublicHttp()
        )
    }

    assert bare[SourceCode.ADZUNA] is Availability.NOT_CONFIGURED
    assert bare[SourceCode.FRANCE_TRAVAIL] is Availability.PENDING_ACCESS
    assert bare[SourceCode.APEC] is Availability.READY
    assert keyed[SourceCode.ADZUNA] is Availability.READY


def test_only_apec_and_wttj_have_a_public_detail() -> None:
    sources = build_sources(SourcesSettings(), PublicHttp())

    assert {source.code for source in sources if isinstance(source, DetailSource)} == {
        SourceCode.APEC,
        SourceCode.WTTJ,
    }
