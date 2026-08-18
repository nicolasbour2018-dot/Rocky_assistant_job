                    ##############################################################################################################
                        # Page streamlit d'affichage de la base de donnée des annonces sous format dataframe paginé. 
                    #############################################################################################################

"""Vue brute et paginée de la table centrale des annonces Rocky."""

from __future__ import annotations

import math

import streamlit as st

from dashboard.dashboard_common import load_repository


BATCH_SIZE = 50
SYNTHETIC_MATCH_COLUMNS = (
    "match_score",
    "match_breakdown",
    "match_strengths",
    "match_gaps",
)


st.title("Tout le Flux")
st.caption(
    "Contenu de la table centrale des annonces, tous profils et tous statuts "
    "confondus. Cette vue est indépendante des filtres du cockpit."
)

try:
    repository = load_repository()
    jobs = repository.fetch_jobs()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

table = jobs.drop(columns=list(SYNTHETIC_MATCH_COLUMNS), errors="ignore")
total = len(table)
st.metric("Annonces en base", total)
if table.empty:
    st.info("La table des annonces est vide.")
    st.stop()

batch_count = max(1, math.ceil(total / BATCH_SIZE))
batch_key = "all_flux_batch"
if st.session_state.get(batch_key) not in range(batch_count):
    st.session_state[batch_key] = 0


def batch_label(batch_index: int) -> str:
    start = batch_index * BATCH_SIZE + 1
    end = min(total, start + BATCH_SIZE - 1)
    return f"{start} à {end} sur {total}"


batch_index = st.selectbox(
    "Tranche de 50 annonces",
    range(batch_count),
    key=batch_key,
    format_func=batch_label,
)
start = batch_index * BATCH_SIZE
end = min(total, start + BATCH_SIZE)
st.dataframe(
    table.iloc[start:end],
    hide_index=True,
    width="stretch",
    height=700,
)
