"""The only list of the sources, in a stable order: adding or removing a platform happens here."""

from __future__ import annotations

from rocky.offres.sources.adzuna import AdzunaSource
from rocky.offres.sources.apec import ApecSource
from rocky.offres.sources.france_travail import FranceTravailSource
from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.linkedin import LinkedInSource
from rocky.offres.sources.model import JobSource
from rocky.offres.sources.wellfound import WellfoundSource
from rocky.offres.sources.wttj import WelcomeToTheJungleSource
from rocky.system.config import SourcesSettings


def build_sources(settings: SourcesSettings, http: PublicHttp) -> tuple[JobSource, ...]:
    return (
        ApecSource(http),
        AdzunaSource(http, settings.adzuna_app_id, settings.adzuna_app_key),
        WelcomeToTheJungleSource(http),
        LinkedInSource(http),
        WellfoundSource(http),
        FranceTravailSource(
            http,
            enabled=settings.france_travail_enabled,
            client_id=settings.france_travail_client_id,
            client_secret=settings.france_travail_client_secret,
        ),
    )
