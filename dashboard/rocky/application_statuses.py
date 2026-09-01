"""Cycle de vie partagé des candidatures Rocky V2.

Les transitions empêchent notamment un accusé tardif de faire régresser un
entretien ou un refus.
"""

from __future__ import annotations


APPLICATION_STATUS_OPTIONS = (
    "DOSSIER PRÉPARÉ",
    "PRÊTE À ENVOYER",
    "CANDIDATURE ENVOYÉE",
    "ACCUSÉ DE RÉCEPTION",
    "EN COURS",
    "ENTRETIEN",
    "TEST TECHNIQUE",
    "OFFRE",
    "REFUS",
    "ÉCARTÉE",
)

STATUS_RANK = {status: rank for rank, status in enumerate(APPLICATION_STATUS_OPTIONS)}

APPLICATION_TO_JOB_STATUS = {
    "DOSSIER PRÉPARÉ": "RETENUE",
    "PRÊTE À ENVOYER": "RETENUE",
    "CANDIDATURE ENVOYÉE": "CANDIDATURE ENVOYÉE",
    "ACCUSÉ DE RÉCEPTION": "CANDIDATURE ENVOYÉE",
    "EN COURS": "CANDIDATURE ENVOYÉE",
    "ENTRETIEN": "ENTRETIEN",
    "TEST TECHNIQUE": "ENTRETIEN",
    "OFFRE": "ENTRETIEN",
    "REFUS": "REFUS",
    "ÉCARTÉE": "ÉCARTÉE",
}

TERMINAL_STATUSES = {"OFFRE", "REFUS", "ÉCARTÉE"}

# Les accusés ne sont pas une décision de l'ATS, mais constituent bien un
# retour reçu après candidature. Les statistiques les intègrent donc au taux
# de réponse, sans les confondre avec un entretien ou une offre.
RESPONSE_STATUSES = frozenset(
    {
        "ACCUSÉ DE RÉCEPTION",
        "EN COURS",
        "ENTRETIEN",
        "TEST TECHNIQUE",
        "OFFRE",
        "REFUS",
    }
)


def normalize_application_status(value: str) -> str:
    """Normalise la casse puis valide un statut public."""
    normalized = str(value or "").strip().upper()
    if normalized not in STATUS_RANK:
        raise ValueError(f"Statut de candidature inconnu : {value}")
    return normalized


def can_apply_automatic_transition(current: str, proposed: str) -> bool:
    """Autorise une évolution automatique certaine sans régression métier."""
    current = normalize_application_status(current)
    proposed = normalize_application_status(proposed)
    if current in TERMINAL_STATUSES:
        return current == proposed
    if proposed in TERMINAL_STATUSES:
        return True
    return STATUS_RANK[proposed] >= STATUS_RANK[current]
