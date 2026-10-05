"""Fiche de décision complète d'une annonce Rocky.

Cette destination du cockpit réunit données source, détail de matching,
édition contrôlée, diagnostics ATS et préparation de candidature. Elle
oriente vers le parcours dédié plutôt que d'envoyer une candidature elle-même.
"""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from dashboard.dashboard_common import (
    display_date,
    display_salary,
    display_score,
    load_data,
    plain_description,
)
from dashboard.job_detail_components import (
    render_edit_form,
    render_letter_workshop,
    render_matching_detail,
)
from dashboard.rocky.enrichment import reenrich_saved_job
from dashboard.rocky.statuses import JOB_STATUS_OPTIONS


if st.button("← Retour au cockpit"):
    st.switch_page("dashboard_b.py")

job_id = st.session_state.get("selected_job_id")
if not job_id:
    st.title("Fiche annonce")
    st.info("Sélectionne une annonce depuis le cockpit pour ouvrir sa fiche.")
    st.stop()

try:
    settings, repository, profile, _ = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

offer = repository.fetch_job_offer(int(job_id))
if offer is None:
    st.error("Cette annonce n’existe plus dans Rocky.")
    st.stop()

all_jobs = repository.fetch_jobs(profile.id if profile else None)
selected = all_jobs[all_jobs["id"] == int(job_id)]
if selected.empty:
    st.error("Le détail de cette annonce est indisponible.")
    st.stop()
row = selected.iloc[0]

heading = st.columns([5, 2])
heading[0].title(offer.job_title or "Annonce sans titre")
heading[0].subheader(offer.company_name or "Entreprise inconnue")
heading[0].caption(
    f"Rocky #{job_id} · {offer.source_name or 'Source inconnue'} · "
    f"{display_date(offer.publication_date)}"
)
heading[1].metric(
    "Score Rocky",
    display_score(row.get("match_score")),
)

language = st.columns([2, 1])
current_language = offer.language_override or "auto"
language_choice = language[0].selectbox(
    "Langue de l'annonce et du profil",
    ["auto", "fr", "en"],
    index=["auto", "fr", "en"].index(current_language if current_language in {"fr", "en"} else "auto"),
    format_func=lambda value: {
        "auto": f"Automatique · {(offer.detected_language or 'fr').upper()}",
        "fr": "Français",
        "en": "English",
    }[value],
)
if language[1].button("Appliquer la langue", use_container_width=True):
    repository.set_job_language(
        int(job_id), None if language_choice == "auto" else language_choice
    )
    if profile:
        repository.recalculate_job_match(int(job_id), profile.id)
    st.rerun()
if not offer.language_override and (offer.language_confidence or 0) < 0.7:
    st.caption("Détection incertaine : vérifie la langue avant de préparer le dossier.")

# Le profil reste le même, mais ses champs localisés et son kit documentaire
# suivent la langue effective de l'annonce. Cette sélection est effectuée aussi
# sur la fiche directe, pas seulement dans le parcours « Préparer candidature ».
profile_for_offer = repository.profile_for_offer(profile.id, offer) if profile else None
if profile_for_offer and profile_for_offer.locale == "en":
    english_documents = {
        document.kind: document
        for document in repository.fetch_profile_documents(profile_for_offer.id, "en")
    }
    english_cv = english_documents.get("cv")
    if english_cv:
        profile_for_offer = replace(profile_for_offer, cv_path=english_cv.source_path)

links = st.columns([2, 1])
application_url = offer.application_url or offer.source_url
if application_url:
    if links[0].button(
        "Préparer la candidature",
        type="primary",
        key=f"v2_detail_apply_{job_id}",
        use_container_width=True,
    ):
        # Ouvrir une page dédiée rend l'action explicite et évite que le
        # changement d'onglet soit perdu lors d'un rerun Streamlit.
        st.session_state.selected_job_id = int(job_id)
        st.switch_page("page_application_prepare.py")
    links[0].link_button(
        "Ouvrir le site de candidature", application_url, use_container_width=True
    )
status_index = (
    list(JOB_STATUS_OPTIONS).index(offer.status)
    if offer.status in JOB_STATUS_OPTIONS
    else 0
)
new_status = links[1].selectbox(
    "Statut",
    JOB_STATUS_OPTIONS,
    index=status_index,
    key=f"v2_detail_status_{job_id}",
)
if links[1].button(
    "Enregistrer le statut",
    key=f"v2_detail_save_status_{job_id}",
    use_container_width=True,
):
    repository.update_job_status(int(job_id), new_status)
    st.success("Statut enregistré.")
    st.rerun()

if offer.description_is_full:
    st.success("Description complète · matching disponible")
else:
    incomplete = st.columns([3, 1])
    incomplete[0].warning(
        "Description incomplète · le matching complet reste suspendu."
    )
    if incomplete[1].button(
        "Retenter l’enrichissement",
        key=f"v2_detail_reenrich_{job_id}",
        use_container_width=True,
    ):
        with st.spinner("Source d’origine, puis TheirStack si nécessaire…"):
            hydration = reenrich_saved_job(
                int(job_id), settings, repository, profile
            )
        if hydration.is_complete:
            st.success(f"Description récupérée via {hydration.method}.")
            st.rerun()
        st.error(hydration.warning or "Description toujours indisponible.")

tab_labels = ["Annonce et modifications", "Matching détaillé", "Lettre et candidature"]
requested_tab = st.session_state.pop("v2_detail_default_tab", None)
overview_tab, matching_tab, application_tab = st.tabs(
    tab_labels,
    default=requested_tab if requested_tab in tab_labels else None,
)

with overview_tab:
    provenance_key = f"v2_detail_show_provenance_{job_id}"
    edit_key = f"v2_detail_show_edit_{job_id}"
    quick_actions = st.columns([1, 1, 5])
    if quick_actions[0].button(
        "Provenance",
        key=f"v2_detail_toggle_provenance_{job_id}",
        width="content",
    ):
        st.session_state[provenance_key] = not st.session_state.get(
            provenance_key, False
        )
    if quick_actions[1].button(
        "Modifier l’annonce",
        key=f"v2_detail_toggle_edit_{job_id}",
        width="content",
    ):
        st.session_state[edit_key] = not st.session_state.get(edit_key, False)

    if st.session_state.get(provenance_key):
        with st.container(border=True):
            st.caption("Provenance et identifiants")
            st.write(f"**Identifiant interne Rocky :** {job_id}")
            st.write(
                f"**Source de collecte :** {offer.source_name or 'Non précisée'}"
            )
            st.write(
                f"**Identifiant externe :** {offer.external_id or 'Non précisé'}"
            )
            st.write(f"**URL source :** {offer.source_url or 'Non précisée'}")
            st.write(
                "**Source d’enrichissement :** "
                f"{offer.description_enrichment_source or 'Aucune'}"
            )
    if st.session_state.get(edit_key):
        render_edit_form(
            int(job_id),
            offer,
            repository,
            profile,
            expander_label=None,
        )

    metadata = st.columns(4)
    metadata[0].write(f"**Lieu**  \n{offer.city or 'Non précisé'}")
    metadata[1].write(
        f"**Télétravail**  \n{offer.remote_policy or 'Non précisé'}"
    )
    metadata[2].write(f"**Salaire**  \n{display_salary(row)}")
    metadata[3].write(
        f"**Contrat**  \n{offer.contract_type or 'Non précisé'}"
    )
    more_metadata = st.columns(4)
    more_metadata[0].write(
        f"**Temps de travail**  \n{offer.work_schedule or 'Non précisé'}"
    )
    more_metadata[1].write(
        f"**Expérience**  \n{offer.experience_level or 'Non précisé'}"
    )
    more_metadata[2].write(
        f"**Formation**  \n{offer.required_education or 'Non précisée'}"
    )
    more_metadata[3].write(
        "**Date limite**  \n"
        f"{display_date(offer.application_deadline)}"
    )

    st.subheader("Description")
    description = plain_description(offer.responsibilities)
    st.write(description or offer.short_description or "Aucun aperçu disponible.")
    if offer.description_enrichment_source:
        st.caption(
            f"Description enrichie via {offer.description_enrichment_source}. "
            f"La source de collecte reste {offer.source_name}."
        )

with matching_tab:
    render_matching_detail(row, offer, repository, profile_for_offer or profile)

with application_tab:
    render_letter_workshop(
        int(job_id), offer, settings, repository, profile_for_offer or profile
    )
    if application_url:
        st.info(
            "Après génération des deux PDF, ouvre la page Candidatures pour "
            "préremplir le site. Le statut envoyé ne change qu'après confirmation."
        )
