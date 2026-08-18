"""Point d'entrée unique de l'application Rocky V2."""

# Importation des libairies nécessaires.
from __future__ import annotations
import streamlit as st

# importation des modules internes
from dashboard.dashboard_common import render_floating_chatbot

# Configuration de la l'application Streamlit.
# Configure l'apparence globale de l'application avant le rendu des pages.
st.set_page_config(page_title="Rocky V2", page_icon="🎛️", layout="wide")

# Définition des pages de l'application.
# Expose les pages et défini leur visibilité dans la navigation.
cockpit = st.Page(
    "dashboard_b.py",
    title="Cockpit",
    icon="🎛️",
    default=True,
)
all_jobs = st.Page(
    "page_all_jobs.py",
    title="Tout le Flux",
    icon="📋",
)
enrichment = st.Page(
    "page_enrichment.py",
    title="À enrichir",
    icon="🧩",
    visibility="hidden",
)
job_detail = st.Page(
    "page_job_detail.py",
    title="Fiche annonce",
    icon="📄",
    visibility="hidden",
)
add_url = st.Page(
    "page_import_url.py",
    title="Ajouter une URL",
    icon="🔗",
)
profiles = st.Page(
    "page_profiles.py",
    title="Mes profils",
    icon="👤",
)
monitoring = st.Page(
    "page_monitoring.py",
    title="Monitoring",
    icon="🩺",
)
ats_v3 = st.Page(
    "page_ats_v3.py",
    title="ATS V3",
    icon="🧪",
)

# Instanciation de la navigation du streamlit + config d'affichage.
# Organise la navigation de l'application en regroupant les pages par catégorie et en définissant leur position dans l'interface.
navigation = st.navigation(
    {
        "Rocky V2": [cockpit, all_jobs, ats_v3, enrichment, job_detail],
        "Outils V1.1": [add_url, profiles, monitoring],
    },
    position="sidebar",
    expanded=True,
)
# Affichage du footer dans la sidebar.
with st.sidebar:
    st.caption("Rocky V2 · cockpit et outils personnels")

# Affichage du chatbot flottant.
render_floating_chatbot()

# Lancement de la navigation.
# Exécute la navigation et affiche la page sélectionnée par l'utilisateur.
navigation.run()
