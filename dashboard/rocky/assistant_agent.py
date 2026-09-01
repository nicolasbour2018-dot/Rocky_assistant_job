"""Interpréteur local des actions autorisées dans le chat Rocky."""

from __future__ import annotations

import re

from .application_statuses import APPLICATION_STATUS_OPTIONS
from .models import ProposedAction
from .statuses import JOB_STATUS_OPTIONS
from .text_utils import normalize_text


FIELD_LABELS = {
    "ville": "city",
    "entreprise": "company_name",
    "poste": "job_title",
    "contrat": "contract_type",
    "teletravail": "remote_policy",
    "temps de travail": "work_schedule",
    "url": "application_url",
}


def _status_in_message(message: str, options: tuple[str, ...]) -> str | None:
    """Détecte un statut autorisé dans une demande libre, sans exécuter l'action."""
    normalized = normalize_text(message)
    aliases = {
        "envoyee": "CANDIDATURE ENVOYÉE",
        "envoye": "CANDIDATURE ENVOYÉE",
        "accuse": "ACCUSÉ DE RÉCEPTION",
        "test": "TEST TECHNIQUE",
        "refusee": "REFUS",
        "refus": "REFUS",
    }
    for marker, status in aliases.items():
        if marker in normalized and status in options:
            return status
    for status in options:
        if normalize_text(status) in normalized:
            return status
    return None


def plan_rocky_action(message: str) -> ProposedAction:
    """Planifie sans exécuter et ne reconnaît aucune instruction SQL libre."""
    cleaned = " ".join(message.strip().split())
    if not cleaned:
        return ProposedAction("ANSWER", "Pose-moi une question précise.")
    application_match = re.search(
        r"(?:candidature|dossier)\s*#?\s*(\d+)", cleaned, re.I
    )
    if application_match:
        application_id = int(application_match.group(1))
        status = _status_in_message(cleaned, APPLICATION_STATUS_OPTIONS)
        if status:
            return ProposedAction(
                "UPDATE_APPLICATION_STATUS",
                f"Passer la candidature #{application_id} au statut {status}.",
                application_id,
                status,
                requires_confirmation=True,
            )
        note_match = re.search(r"(?:note|ajoute)\s*[:=]\s*(.+)$", cleaned, re.I)
        if note_match:
            note = note_match.group(1).strip()
            return ProposedAction(
                "ADD_APPLICATION_NOTE",
                f"Ajouter une note à la candidature #{application_id} : {note}",
                application_id,
                note,
                requires_confirmation=True,
            )
    job_match = re.search(r"annonce\s*#?\s*(\d+)", cleaned, re.I)
    if job_match:
        job_id = int(job_match.group(1))
        status = _status_in_message(cleaned, JOB_STATUS_OPTIONS)
        if status:
            return ProposedAction(
                "UPDATE_JOB_STATUS",
                f"Passer l'annonce #{job_id} au statut {status}.",
                job_id,
                status,
                requires_confirmation=True,
            )
        normalized = normalize_text(cleaned)
        for label, field in FIELD_LABELS.items():
            match = re.search(
                rf"{re.escape(label)}\s*[:=]\s*(.+)$", normalized, re.I
            )
            if match:
                value = cleaned[-len(match.group(1)):].strip()
                return ProposedAction(
                    "UPDATE_JOB_FIELD",
                    f"Modifier {label} de l'annonce #{job_id} : {value}",
                    job_id,
                    value,
                    field,
                    True,
                )
    if any(word in normalize_text(cleaned) for word in ("stat", "bilan", "combien", "ou en suis")):
        return ProposedAction("READ_SUMMARY", "Afficher le bilan Rocky actuel.")
    return ProposedAction("ANSWER", cleaned)
