"""Connecteurs indépendants de la veille Rocky."""

from .adzuna import AdzunaSource
from .apec import ApecSource
from .base import JobSource
from .france_travail import FranceTravailSource
from .indeed import IndeedSource
from .linkedin import LinkedInSource
from .registry import build_watch_sources
from .wellfound import WellfoundSource
from .wttj import WelcomeToTheJungleSource

__all__ = [
    "AdzunaSource",
    "ApecSource",
    "FranceTravailSource",
    "IndeedSource",
    "JobSource",
    "LinkedInSource",
    "WelcomeToTheJungleSource",
    "WellfoundSource",
    "build_watch_sources",
]
