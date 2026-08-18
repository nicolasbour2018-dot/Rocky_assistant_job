"""Registre unique des sources utilisées par le dashboard, le cron et les tests."""

from __future__ import annotations

from ..config import Settings
from .adzuna import AdzunaSource
from .apec import ApecSource
from .base import JobSource
from .france_travail import FranceTravailSource
from .indeed import IndeedSource
from .linkedin import LinkedInSource
from .wellfound import WellfoundSource
from .wttj import WelcomeToTheJungleSource


def build_watch_sources(settings: Settings) -> list[JobSource]:
    """Construit toutes les sources dans un ordre stable.

    Ajouter ou retirer une plateforme se fait uniquement ici. Les trois points
    d'entrée (dashboard, cron et diagnostic) restent automatiquement alignés.
    """
    return [
        FranceTravailSource(settings),
        AdzunaSource(settings),
        LinkedInSource(),
        IndeedSource(settings),
        WelcomeToTheJungleSource(),
        ApecSource(),
        WellfoundSource(),
    ]
