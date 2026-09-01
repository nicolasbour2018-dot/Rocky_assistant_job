"""Flux exhaustif des annonces du profil actif.

La page sert à explorer, filtrer, exporter et classer les opportunités déjà
connues par Rocky. Les actions groupées restent explicites et n'effacent jamais
une candidature liée sans contrôle métier.
"""

from __future__ import annotations

import hashlib
import math

import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_repository, options, selected_row_ids
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.statuses import JOB_STATUS_OPTIONS

BATCH_SIZE = 50
SYNTHETIC_MATCH_COLUMNS = (
    "match_score",
    "match_breakdown",
    "match_strengths",
    "match_gaps",
)


def _filter_jobs(
    frame: pd.DataFrame, query: str, sources: list[str], statuses: list[str]
) -> pd.DataFrame:
    """Filtre le flux central sans altérer les enregistrements en base."""
    filtered = frame.copy()
    if query.strip():
        mask = (
            filtered["job_title"]
            .fillna("")
            .str.contains(query, case=False, regex=False)
            | filtered["company_name"]
            .fillna("")
            .str.contains(query, case=False, regex=False)
            | filtered["city"].fillna("").str.contains(query, case=False, regex=False)
        )
        filtered = filtered[mask]
    if sources:
        filtered = filtered[filtered["source_name"].fillna("Inconnue").isin(sources)]
    if statuses:
        filtered = filtered[filtered["status"].isin(statuses)]
    return filtered


def _batch_label(index: int, total: int) -> str:
    """Construit un libellé de pagination explicite pour les grands flux."""
    start = index * BATCH_SIZE + 1
    end = min(total, start + BATCH_SIZE - 1)
    return f"{start} à {end} sur {total}"


st.markdown('<div class="rocky-kicker">Base d’annonces</div>', unsafe_allow_html=True)
st.title("Tout le Flux")
st.caption(
    "Filtre, exporte et organise les annonces centralisées. La suppression est "
    "réservée aux annonces déjà écartées et sans candidature liée."
)

try:
    # Le flux est volontairement global : il reste un outil de nettoyage de la
    # base, alors que le cockpit se concentre sur le profil actif.
    repository: RockyRepository = load_repository()
    jobs = repository.fetch_jobs()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

if jobs.empty:
    st.info("La table des annonces est vide.")
    st.stop()

summary = st.columns(3)
summary[0].metric("Annonces en base", len(jobs))
summary[1].metric("Écartées", int(jobs["status"].eq("ÉCARTÉE").sum()))
summary[2].metric("Sources", int(jobs["source_name"].fillna("Inconnue").nunique()))

filters = st.columns([3, 2, 2])
query = filters[0].text_input("Rechercher", placeholder="Poste, entreprise ou lieu")
selected_sources = filters[1].multiselect("Sources", options(jobs, "source_name"))
selected_statuses = filters[2].multiselect("Statuts", list(JOB_STATUS_OPTIONS))
filtered = _filter_jobs(jobs, query, selected_sources, selected_statuses)

export_columns = [
    column for column in filtered if column not in SYNTHETIC_MATCH_COLUMNS
]
st.download_button(
    f"Exporter les {len(filtered)} annonce(s) filtrées (CSV)",
    filtered[export_columns].to_csv(index=False).encode("utf-8-sig"),
    file_name="rocky_flux_filtre.csv",
    mime="text/csv",
    width="stretch",
)

if filtered.empty:
    st.info("Aucune annonce ne correspond aux filtres actuels.")
    st.stop()

st.markdown("#### Gestion des annonces")
st.caption(
    "Sélectionne des lignes pour changer leur statut. La suppression définitive "
    "n’accepte que les annonces ÉCARTÉES sans dossier de candidature."
)
management_columns = [
    "id",
    "job_title",
    "company_name",
    "source_name",
    "city",
    "publication_date",
    "status",
]
selection_frame = filtered[management_columns].reset_index(drop=True)
selection_signature = hashlib.sha1(
    ",".join(str(job_id) for job_id in selection_frame["id"]).encode("utf-8")
).hexdigest()[:12]
selection = st.dataframe(
    selection_frame,
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="multi-row",
    key=f"all_flux_selection_{selection_signature}",
    column_config={
        "id": st.column_config.NumberColumn("ID", format="%d"),
        "job_title": "Poste",
        "company_name": "Entreprise",
        "source_name": "Source",
        "city": "Lieu",
        "publication_date": st.column_config.DateColumn(
            "Publication", format="DD/MM/YYYY"
        ),
        "status": "Statut",
    },
)
selected_ids = selected_row_ids(selection_frame, list(selection.selection.rows))
actions = st.columns([2, 1, 2])
next_status = actions[0].selectbox("Changer le statut sélectionné", JOB_STATUS_OPTIONS)
if actions[1].button(
    f"Appliquer ({len(selected_ids)})",
    disabled=not selected_ids,
    width="stretch",
):
    changed = repository.update_jobs_status(selected_ids, next_status)
    st.success(f"{changed} annonce(s) mises à jour.")
    st.rerun()

delete_confirmation = actions[2].checkbox(
    "Je confirme la suppression définitive des annonces écartées sélectionnées.",
    disabled=not selected_ids,
)
if st.button(
    f"Supprimer les écartées sélectionnées ({len(selected_ids)})",
    disabled=not selected_ids or not delete_confirmation,
    type="secondary",
    help="Les annonces non écartées ou liées à une candidature restent protégées.",
):
    result = repository.delete_discarded_jobs(selected_ids)
    st.success(f"{result['deleted']} annonce(s) écartée(s) supprimée(s).")
    if result["not_discarded"] or result["linked_to_application"]:
        st.info(
            f"Protégées : {result['not_discarded']} non écartée(s) · "
            f"{result['linked_to_application']} liée(s) à une candidature."
        )
    st.rerun()

st.markdown("#### Parcourir le résultat")
batch_count = max(1, math.ceil(len(filtered) / BATCH_SIZE))
batch_key = f"all_flux_batch_{selection_signature}"
if st.session_state.get(batch_key) not in range(batch_count):
    st.session_state[batch_key] = 0
batch_index = st.selectbox(
    "Tranche de 50 annonces",
    range(batch_count),
    key=batch_key,
    format_func=lambda index: _batch_label(index, len(filtered)),
)
start = batch_index * BATCH_SIZE
end = min(len(filtered), start + BATCH_SIZE)
st.dataframe(
    filtered.iloc[start:end][export_columns],
    hide_index=True,
    width="stretch",
    height=650,
)
