"""Coeur applicatif modulaire de Rocky.

L'interface Streamlit importe ce paquet, mais aucun module de ce paquet
n'importe Streamlit. Cette séparation permet de tester et déboguer la logique
métier sans lancer le dashboard.
"""

from .config import Settings
from .models import CandidateProfile, JobOffer, MatchResult

__all__ = ["CandidateProfile", "JobOffer", "MatchResult", "Settings"]
