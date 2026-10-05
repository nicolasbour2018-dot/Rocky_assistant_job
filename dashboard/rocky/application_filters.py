"""Filtres purs employés par l'espace de suivi des candidatures."""

from __future__ import annotations

import pandas as pd

from dashboard.rocky.application_statuses import APPLICATION_STATUS_OPTIONS


# Les segments décrivent les phases consultables du parcours sans exposer les
# annonces écartées dans la page dédiée aux candidatures.
PIPELINE_SEGMENTS = {
    "Toutes": set(APPLICATION_STATUS_OPTIONS),
    "À envoyer": {"DOSSIER PRÉPARÉ", "PRÊTE À ENVOYER"},
    "En cours": {
        "CANDIDATURE ENVOYÉE",
        "ACCUSÉ DE RÉCEPTION",
        "EN COURS",
        "ENTRETIEN",
        "TEST TECHNIQUE",
    },
    "Clôturées": {"OFFRE", "REFUS"},
}


def filter_applications(
    applications: pd.DataFrame,
    *,
    segment: str,
    statuses: list[str],
    query: str,
    minimum_score: int,
    sort_order: str,
) -> pd.DataFrame:
    """Retourne les candidatures correspondant aux filtres du suivi.

    Un seuil nul conserve les dossiers historiques sans score. Lorsqu'il est
    positif, un dossier sans score ne peut pas satisfaire le critère et est
    donc volontairement absent de la sélection.
    """
    visible = applications.copy()
    segment_statuses = PIPELINE_SEGMENTS.get(segment, PIPELINE_SEGMENTS["Toutes"])
    visible = visible[visible["status"].isin(segment_statuses)]
    if statuses:
        visible = visible[visible["status"].isin(statuses)]
    cleaned_query = query.strip()
    if cleaned_query and not visible.empty:
        mask = (
            visible["company_name"].fillna("").str.contains(
                cleaned_query, case=False, regex=False
            )
            | visible["job_title"].fillna("").str.contains(
                cleaned_query, case=False, regex=False
            )
        )
        visible = visible[mask]
    if minimum_score > 0 and not visible.empty:
        scores = pd.to_numeric(visible["match_score"], errors="coerce")
        visible = visible[scores >= minimum_score]
    if sort_order == "Entreprise":
        visible = visible.sort_values(["company_name", "job_title"])
    elif sort_order == "Meilleur score":
        visible = visible.sort_values("match_score", ascending=False, na_position="last")
    elif sort_order == "Étape du parcours":
        rank = {status: index for index, status in enumerate(APPLICATION_STATUS_OPTIONS)}
        visible = visible.assign(
            _status_rank=visible["status"].map(rank).fillna(-1)
        ).sort_values(["_status_rank", "prepared_at"], ascending=[False, False])
        visible = visible.drop(columns="_status_rank")
    else:
        visible = visible.sort_values("prepared_at", ascending=False)
    return visible.reset_index(drop=True)
