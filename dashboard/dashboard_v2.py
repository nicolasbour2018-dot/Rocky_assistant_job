"""Point d'entrée et navigation sécurisée de Rocky.

Ce module initialise la configuration, l'authentification, la session et les
pages Streamlit. Il coordonne les composants de haut niveau sans embarquer les
règles métier, qui restent isolées dans les services Rocky.
"""

# Importation des libairies nécessaires.
from __future__ import annotations

import streamlit as st

# `st.Page` est la fabrique ; le type de ce qu'elle rend n'est pas réexporté
# sur `st`, il faut donc aller le chercher dans son module.
from streamlit.navigation.page import StreamlitPage

# importation des modules internes
from dashboard.auth_ui import render_account_sidebar, require_authenticated_user
from dashboard.dashboard_common import (
    load_data,
    load_repository,
    render_floating_chatbot,
)
from dashboard.rocky.config import Settings
from dashboard.rocky.gmail_service import GmailService
from dashboard.rocky.scheduler import ensure_local_scheduler


def _complete_gmail_oauth_callback(monitoring_page: StreamlitPage) -> None:
    """Finalise le retour Google reçu par Streamlit sur le port du Mac.

    Le callback arrive à la racine car les clients OAuth Desktop autorisent le
    loopback local. L'état signé localement permet de retrouver la boîte sans
    accepter une adresse fournie par la requête du navigateur.
    """
    state = str(st.query_params.get("state") or "")
    code = str(st.query_params.get("code") or "")
    oauth_error = str(st.query_params.get("error") or "")
    if not state or not (code or oauth_error):
        return
    notice: dict[str, str]
    try:
        settings, repository, profile, _ = load_data()
        if profile is None:
            raise RuntimeError("Aucun profil Rocky actif.")
        if repository.user_id is None:
            raise PermissionError("Un compte authentifié est requis pour Gmail.")
        account_email = GmailService.account_for_pending_authorization(
            settings, state, repository.user_id
        )
        if oauth_error:
            GmailService.discard_pending_authorization(
                settings, state, repository.user_id
            )
            notice = {
                "level": "warning",
                "message": (
                    f"Autorisation annulée pour {account_email}."
                    if oauth_error == "access_denied"
                    else f"Google a refusé l'autorisation de {account_email}."
                ),
            }
        else:
            GmailService(
                settings, repository, profile, account_email
            ).complete_browser_authorization(
                state=state,
                code=code,
                redirect_uri=settings.gmail_oauth_redirect_uri,
            )
            notice = {
                "level": "success",
                "message": f"{account_email} est autorisée en lecture seule.",
            }
    except Exception as error:
        notice = {
            "level": "error",
            "message": (
                "L'autorisation Gmail n'a pas pu être finalisée "
                f"({type(error).__name__}). Relance-la depuis Monitoring."
            ),
        }
    st.session_state["gmail_oauth_notice"] = notice
    st.query_params.clear()
    st.switch_page(monitoring_page)


# Configuration de la l'application Streamlit.
# Configure l'apparence globale de l'application avant le rendu des pages.
st.set_page_config(page_title="Rocky V2", page_icon="🐾", layout="wide")
st.markdown(
    """
    <style>
    :root { --rocky-blue:#08b5d1; --rocky-coral:#ff7f66; --rocky-lime:#b9e769; --rocky-navy:#18212b; --rocky-cream:#f7f6f1; --rocky-line:#d8e7e9; }
    .stApp { background:radial-gradient(circle at 86% 2%, rgba(185,231,105,.34) 0%, transparent 18%), radial-gradient(circle at 10% 12%, rgba(255,127,102,.18) 0%, transparent 20%), linear-gradient(140deg, #f7f6f1 0%, #ffffff 58%, #edf9fb 100%); color:var(--rocky-navy); }
    .block-container { max-width:1280px; padding-top:2.1rem; padding-bottom:4rem; }
    h1, h2, h3 { color:var(--rocky-navy); letter-spacing:-0.028em; }
    h1 { font-weight:750; margin-bottom:.18rem !important; }
    h2, h3 { margin-top:1.35rem !important; }
    div[data-testid="stMetric"] { background:rgba(255,255,255,.88); border:1px solid var(--rocky-line); border-radius:16px; padding:14px 15px; box-shadow:0 5px 18px rgba(18,66,76,.05); transition:transform .18s ease, box-shadow .18s ease; }
    div[data-testid="stMetric"]:hover { transform:translateY(-2px) rotate(-.15deg); box-shadow:0 10px 24px rgba(18,66,76,.11); }
    div[data-testid="stMetricValue"] { color:var(--rocky-navy); font-size:clamp(1.05rem, 1.65vw, 1.55rem); line-height:1.1; white-space:nowrap; overflow:visible; }
    div[data-testid="stMetricLabel"] { font-size:.72rem; white-space:nowrap; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:18px; border-color:var(--rocky-line); background:rgba(255,255,255,.76); box-shadow:0 5px 20px rgba(18,66,76,.035); }
    section[data-testid="stSidebar"] { background:linear-gradient(180deg,#eff9fa 0%,#e7f3f5 70%,#fff2e9 100%); border-right:1px solid var(--rocky-line); }
    section[data-testid="stSidebar"] a { border-radius:9px; margin:2px 8px; transition:background .18s ease, transform .18s ease; }
    section[data-testid="stSidebar"] a:hover { background:#d8f1f5; transform:translateX(2px); }
    .stButton > button { border-radius:10px; min-height:2.35rem; font-weight:650; transition:transform .15s ease, box-shadow .15s ease; }
    .stButton > button:hover:not(:disabled) { transform:translateY(-1px); box-shadow:0 5px 12px rgba(18,66,76,.12); }
    .stButton button[kind="primary"] { border-radius:10px; font-weight:750; border:0; background:linear-gradient(120deg,var(--rocky-blue),#1397c1); color:#fff; box-shadow:0 5px 14px rgba(8,181,209,.22); }
    div[data-testid="stDataFrame"] { border:1px solid var(--rocky-line); border-radius:14px; overflow:hidden; background:#fff; }
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div { border-radius:10px; border-color:var(--rocky-line); }
    .rocky-kicker { display:inline-block; color:#087f96; background:linear-gradient(90deg,rgba(8,181,209,.14),rgba(255,127,102,.15)); border:1px solid rgba(8,181,209,.18); border-radius:999px; padding:.32rem .72rem; font-size:.72rem; font-weight:850; letter-spacing:.13em; text-transform:uppercase; }
    .rocky-hero { position:relative; overflow:hidden; border-radius:24px; padding:1.15rem 1.35rem; margin:.3rem 0 1.1rem; background:linear-gradient(115deg,rgba(8,181,209,.16),rgba(185,231,105,.2) 52%,rgba(255,127,102,.16)); border:1px solid rgba(8,181,209,.2); }
    .rocky-hero::after { content:'✦'; position:absolute; right:2.2rem; top:-.35rem; color:rgba(255,127,102,.55); font-size:4.5rem; transform:rotate(16deg); }
    .rocky-hero strong { font-size:1.08rem; }
    div[data-testid="stChatMessage"] { border-radius:16px; border:1px solid rgba(8,181,209,.12); background:rgba(255,255,255,.66); }
    div[data-testid="stPopover"] button { border-radius:999px; }
    @media (max-width: 760px) { .block-container { padding:1.1rem .8rem 3rem; } h1 { font-size:2rem !important; } div[data-testid="stMetric"] { padding:10px; } }
    </style>
    """,
    unsafe_allow_html=True,
)
authenticated_user = require_authenticated_user()
account_profiles = load_repository().for_user(authenticated_user.id).fetch_profiles()
needs_onboarding = account_profiles.empty or not bool(
    account_profiles["onboarding_status"].fillna("COMPLETE").eq("COMPLETE").any()
)
ensure_local_scheduler(Settings().project_dir)

# Définition des pages de l'application.
# Expose les pages et défini leur visibilité dans la navigation.
cockpit = st.Page(
    "dashboard_b.py",
    title="Cockpit",
    icon="🎛️",
    default=not needs_onboarding,
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
)
job_detail = st.Page(
    "page_job_detail.py",
    title="Fiche annonce",
    icon="📄",
)
application_prepare = st.Page(
    "page_application_prepare.py",
    title="Préparer une candidature",
    icon="📝",
)
add_url = st.Page(
    "page_import_url.py",
    title="Ajouter une URL",
    icon="🔗",
)
profiles = st.Page(
    "page_profiles.py",
    title="Profil & CV",
    icon="👤",
    default=needs_onboarding,
)
monitoring = st.Page(
    "page_monitoring.py",
    title="Monitoring",
    icon="🩺",
)
ats = st.Page(
    "page_ats_v3.py",
    title="ATS",
    icon="🧪",
)
applications = st.Page(
    "page_applications.py",
    title="Candidatures",
    icon="📨",
)
statistics = st.Page(
    "page_statistics.py",
    title="Statistiques",
    icon="📈",
)
assistant = st.Page(
    "page_assistant.py",
    title="Assistant Rocky",
    icon="🐾",
)

# Ces trois écrans dépendent toujours d'une annonce déjà sélectionnée. Ils
# restent donc enregistrés dans ``st.navigation`` pour que ``st.switch_page``
# puisse y conduire depuis le cockpit ou une fiche, mais sont retirés de la
# sidebar. Streamlit 1.51 ne fournit pas de visibilité par page : la règle CSS
# cible les liens de navigation sans empêcher leur ouverture contextuelle.
st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] li:has(a[href$="/page_enrichment"]),
    [data-testid="stSidebarNav"] li:has(a[href$="/page_job_detail"]),
    [data-testid="stSidebarNav"] li:has(a[href$="/page_application_prepare"]),
    [data-testid="stSidebarNav"] li:has(a[href$="/page_enrichment/"]),
    [data-testid="stSidebarNav"] li:has(a[href$="/page_job_detail/"]),
    [data-testid="stSidebarNav"] li:has(a[href$="/page_application_prepare/"]) {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Instanciation de la navigation du streamlit + config d'affichage.
# Organise la navigation de l'application en regroupant les pages par catégorie et en définissant leur position dans l'interface.
navigation = st.navigation(
    {
        "Rocky": [cockpit, applications, statistics, assistant],
        "Préparer": [
            profiles,
            ats,
            add_url,
            enrichment,
            job_detail,
            application_prepare,
        ],
        "Veille & données": [all_jobs, monitoring],
    },
    position="sidebar",
    expanded=True,
)
_complete_gmail_oauth_callback(monitoring)
# Affichage du footer dans la sidebar.
with st.sidebar:
    st.caption("Rocky · recherche d’emploi personnelle")
render_account_sidebar(authenticated_user)

# Affichage du chatbot flottant.
render_floating_chatbot()

# Lancement de la navigation.
# Exécute la navigation et affiche la page sélectionnée par l'utilisateur.
navigation.run()
