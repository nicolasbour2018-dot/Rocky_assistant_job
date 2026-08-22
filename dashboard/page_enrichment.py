                    ##############################################################################################################
                        # Page d’enrichissement des annonces incomplètes de Rocky.
                    #############################################################################################################

"""Page dédiée aux annonces incomplètes de Rocky V2."""

from __future__ import annotations

import hashlib

import streamlit as st

from dashboard.dashboard_common import (
    display_date,
    filter_jobs,
    jobs_to_enrich,
    load_data,
    options,
    render_job_detail,
    selected_row_ids,
)
from dashboard.job_detail_components import render_edit_form
from dashboard.rocky.enrichment import reenrich_saved_jobs
from dashboard.rocky.statuses import JOB_STATUS_OPTIONS


st.title("À enrichir")
st.caption(
    "Ces annonces sont conservées mais restent hors matching tant que leur "
    "description complète n’a pas été récupérée."
)

try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

incomplete = jobs_to_enrich(jobs)
batch_result_key = f"enrichment_batch_result_{profile.id if profile else 'none'}"
batch_result = st.session_state.pop(batch_result_key, None)
if batch_result:
    st.success(
        f"Enrichissement terminé : {batch_result['enriched']} réussie(s) sur "
        f"{batch_result['attempted']}. "
        f"{batch_result['still_incomplete']} reste(nt) incomplète(s)"
        + (
            f" · {batch_result['errors']} erreur(s) isolée(s)."
            if batch_result["errors"]
            else "."
        )
    )
bulk_status_key = f"enrichment_status_result_{profile.id if profile else 'none'}"
bulk_status_result = st.session_state.pop(bulk_status_key, None)
if bulk_status_result:
    st.success(
        f"Statut « {bulk_status_result['status']} » appliqué à "
        f"{bulk_status_result['updated']} annonce(s)."
    )

top = st.columns([1, 2, 2])
top[0].metric("À enrichir", len(incomplete))
query = top[1].text_input("Recherche", placeholder="Poste ou entreprise")
sources = top[2].multiselect(
    "Sources", options(incomplete, "source_name")
)
with st.expander("Trier les annonces"):
    sort_choice = st.selectbox(
        "Trier par",
        (
            "Dernière mise à jour",
            "Publication récente",
            "Publication ancienne",
            "Intitulé A → Z",
            "Entreprise A → Z",
            "Lieu A → Z",
            "Source A → Z",
        ),
        key=f"enrichment_sort_{profile.id if profile else 'none'}",
    )
if settings.theirstack_api_key:
    st.success(
        "Fallback TheirStack configuré. Il sera utilisé uniquement après "
        "l’échec du mécanisme de la source d’origine."
    )
else:
    st.info(
        "TheirStack n’est pas configuré : les mécanismes de la source "
        "d’origine restent disponibles."
    )

enrichment_action = st.columns([1.4, 3])
if enrichment_action[0].button(
    f"Tout enrichir ({len(incomplete)})",
    type="primary",
    disabled=incomplete.empty,
    width="stretch",
    help=(
        "Retente toute la file du profil actif. TheirStack peut être utilisé en "
        "fallback et consommer des crédits lorsque la source d’origine échoue."
    ),
):
    progress = st.progress(0, text="Préparation de la file…")

    def update_progress(current: int, total: int) -> None:
        progress.progress(
            current / max(1, total),
            text=f"Enrichissement {current} / {total}",
        )

    result = reenrich_saved_jobs(
        [int(job_id) for job_id in incomplete["id"].tolist()],
        settings,
        repository,
        profile,
        on_progress=update_progress,
    )
    st.session_state[batch_result_key] = result
    st.rerun()
enrichment_action[1].caption(
    "Action volontaire sur toutes les annonces incomplètes du profil actif. "
    "Une annonce non récupérée reste dans la file."
)

filtered = filter_jobs(incomplete, query=query, sources=sources)
sort_rules = {
    "Dernière mise à jour": ("updated_at", False),
    "Publication récente": ("publication_date", False),
    "Publication ancienne": ("publication_date", True),
    "Intitulé A → Z": ("job_title", True),
    "Entreprise A → Z": ("company_name", True),
    "Lieu A → Z": ("city", True),
    "Source A → Z": ("source_name", True),
}
sort_column, sort_ascending = sort_rules[sort_choice]
if sort_column in filtered:
    filtered = filtered.sort_values(
        sort_column,
        ascending=sort_ascending,
        na_position="last",
        kind="stable",
    )
st.subheader(f"Annonces en attente · {len(filtered)}")
if filtered.empty:
    st.success("Aucune annonce ne nécessite actuellement d’enrichissement.")

if not filtered.empty:
    st.markdown("#### Actions groupées")
    st.caption(
        "Sélectionne plusieurs lignes, choisis un statut, puis applique-le en une fois."
    )
    selection_frame = filtered[
        [
            "id",
            "job_title",
            "company_name",
            "city",
            "source_name",
            "publication_date",
            "status",
        ]
    ].reset_index(drop=True)
    selection_signature = hashlib.sha1(
        ",".join(str(job_id) for job_id in selection_frame["id"]).encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    selection = st.dataframe(
        selection_frame,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="multi-row",
        key=(
            f"enrichment_multi_select_{profile.id if profile else 'none'}_"
            f"{selection_signature}"
        ),
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d"),
            "job_title": "Poste",
            "company_name": "Entreprise",
            "city": "Lieu",
            "source_name": "Source",
            "publication_date": st.column_config.DateColumn(
                "Publication", format="DD/MM/YYYY"
            ),
            "status": "Statut actuel",
        },
    )
    selected_ids = selected_row_ids(
        selection_frame, list(selection.selection.rows)
    )
    bulk = st.columns([1.5, 1, 2])
    bulk_status = bulk[0].selectbox(
        "Nouveau statut",
        JOB_STATUS_OPTIONS,
        key=f"enrichment_bulk_status_{profile.id if profile else 'none'}",
    )
    if bulk[1].button(
        f"Appliquer ({len(selected_ids)})",
        disabled=not selected_ids,
        width="stretch",
        key=f"enrichment_apply_status_{profile.id if profile else 'none'}",
    ):
        updated = repository.update_jobs_status(selected_ids, bulk_status)
        st.session_state[bulk_status_key] = {
            "updated": updated,
            "status": bulk_status,
        }
        st.rerun()
    bulk[2].caption(
        f"{len(selected_ids)} annonce(s) sélectionnée(s). Les statuts qui ne sont "
        "plus « INCOMPLÈTE » sortent de cette page mais restent en base."
    )

for _, row in filtered.iterrows():
    with st.container(border=True):
        title = st.columns([4, 1])
        title[0].subheader(
            f"{row.get('job_title') or 'Sans titre'} — "
            f"{row.get('company_name') or 'Entreprise inconnue'}"
        )
        title[1].caption(display_date(row.get("publication_date")))
        st.caption(
            f"Source : {row.get('source_name') or 'inconnue'} · "
            f"Lieu : {row.get('city') or 'non précisé'}"
        )
        with st.expander("Voir l’aperçu et réenrichir"):
            job_id = int(row["id"])
            edit_key = f"enrichment_edit_job_{job_id}"
            if st.button(
                "Modifier l'annonce",
                key=f"enrichment_open_edit_{job_id}",
                use_container_width=True,
            ):
                st.session_state[edit_key] = True
            if st.session_state.get(edit_key):
                offer = repository.fetch_job_offer(job_id)
                if offer is None:
                    st.error("Cette annonce n’existe plus dans Rocky.")
                else:
                    render_edit_form(
                        job_id,
                        offer,
                        repository,
                        profile,
                        expander_label=None,
                    )
            render_job_detail(
                row, settings, repository, profile, "enrichment"
            )
