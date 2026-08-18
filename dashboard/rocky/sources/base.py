"""Contrat commun des sources d'annonces."""

from __future__ import annotations

from typing import Protocol

from ..models import CandidateProfile, JobOffer


class JobSource(Protocol):
    name: str

    def search(
        self, profile: CandidateProfile, results_per_query: int
    ) -> list[JobOffer]:
        """Retourne des annonces déjà normalisées."""

