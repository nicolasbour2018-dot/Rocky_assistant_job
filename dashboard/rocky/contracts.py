"""Normalisation du contrat et du temps de travail des annonces.

Les plateformes emploient souvent ``contract_type`` pour deux notions
différentes. Rocky conserve donc séparément :

* la nature du contrat : CDI, CDD ou VIE ;
* le temps de travail : temps plein ou temps partiel.

Les fonctions acceptent des libellés français ou anglais et n'inventent pas
de valeur lorsque l'annonce ne permet pas de conclure.
"""

from __future__ import annotations

import re
from typing import Any

from .text_utils import normalize_text


CONTRACT_TYPES = ("CDI", "CDD", "VIE")
WORK_SCHEDULES = ("Temps plein", "Temps partiel")


def _clean_label(value: Any) -> str:
    """Uniformise les séparateurs utilisés par les API d'emploi."""
    return re.sub(r"[_-]+", " ", normalize_text(value))


def normalize_contract_type(*values: Any) -> str:
    """Retourne uniquement ``CDI``, ``CDD`` ou ``VIE`` si c'est explicite."""
    for value in values:
        raw_label = str(value or "").strip()
        label = _clean_label(value)
        if not label:
            continue

        # « vie » est un mot français courant : on ne reconnaît VIE que si le
        # champ ne contient que ce sigle, si le sigle est écrit en capitales,
        # ou si son intitulé développé est présent.
        compact_label = re.sub(r"[^a-z0-9]", "", label)
        if (
            compact_label == "vie"
            or re.search(r"\bV[. ]*I[. ]*E\b", raw_label)
            or "volontariat international en entreprise" in label
        ):
            return "VIE"
        if (
            re.search(r"\bc[. ]*d[. ]*i\b", label)
            or "duree indeterminee" in label
            or re.search(r"\bpermanent\b", label)
        ):
            return "CDI"
        if (
            re.search(r"\bc[. ]*d[. ]*d\b", label)
            or "duree determinee" in label
            or "fixed term" in label
            or "temporary contract" in label
            or label in {"contract", "temporary"}
        ):
            return "CDD"
    return ""


def normalize_work_schedule(*values: Any) -> str:
    """Retourne ``Temps plein`` ou ``Temps partiel`` si l'information existe."""
    for value in values:
        label = _clean_label(value)
        if not label:
            continue
        if "temps partiel" in label or re.search(r"\bpart time\b", label):
            return "Temps partiel"
        if (
            "temps plein" in label
            or "temps complet" in label
            or re.search(r"\bfull time\b", label)
        ):
            return "Temps plein"
    return ""


def normalize_contract_details(
    contract_value: Any = "",
    work_schedule_value: Any = "",
    *context_values: Any,
) -> tuple[str, str]:
    """Sépare les deux notions en utilisant aussi le texte de l'annonce.

    Les champs structurés sont examinés en premier. La description sert de
    repli, notamment pour les plateformes dont les cartes publiques ne
    fournissent pas directement CDI/CDD/VIE.
    """
    contract_type = normalize_contract_type(contract_value, *context_values)
    work_schedule = normalize_work_schedule(
        work_schedule_value,
        contract_value,
        *context_values,
    )
    return contract_type, work_schedule
