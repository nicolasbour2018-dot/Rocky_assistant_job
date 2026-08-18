"""Rocky V2 — cockpit de veille orienté décision."""

# Importation des librairies standardes 
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st

# Importation des modules internes
## Dépendance des fonctions d'affichage, de filtrage des données du dashboard et de chargement des données. ##
from dashboard.dashboard_common import (
    display_date,
    display_salary,
    display_score,
    filter_jobs,
    load_data,
    metric_counts,
    options,
    render_matching_category_summary,
    run_watch,
)
## Importation des constantes de statuts de jobs ##
from dashboard.rocky.statuses import JOB_STATUS_OPTIONS


st.title("Rocky Assistant Recherche d'emploi (V2)")
st.caption("Cockpit personnel de recherche d’emploi · métriques interactives")


######### -------------------------------------- Bloc de chargement des données et d'affichage du profil actif  ------------------------------------- #########


# Chargement des données depuis la base de données Rocky
## Utilisation de la fonction load_data() pour charger la configuration, le repository, le profil actif et les annonces visibles associées. ##
try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

## Affichage du profil actif
if profile:
    st.caption(f"Profil actif : **{profile.profile_name}**")


######### -------------------------------------- Bloc d'affichage des outils de veille et de filtrage des annonces ------------------------------------- #########

## Organise le containeur avec les boutons de récupération de la veille manuelle et le filtrage des resultats. ##
with st.container(border=True):
    toolbar = st.columns([1.1, 1.9], vertical_alignment="bottom")
    with toolbar[0]:
        st.caption("VEILLE MANUELLE")
        run_watch(settings, repository, "v2")
    with toolbar[1]:
        st.caption("AFFICHAGE DES CARTES")
        display_tools = st.columns([2.5, 1], vertical_alignment="bottom")
        quick_mode = display_tools[0].segmented_control(
            "Vue rapide",
            ["Toutes", "Priorités", "Candidatures"],
            default="Toutes",
            label_visibility="collapsed",
        )
        with display_tools[1]:
            with st.popover("Filtres avancés", use_container_width=True):
                query = st.text_input(
                    "Recherche",
                    placeholder="Poste ou entreprise",
                    key="cockpit_filter_query",
                )
                filter_columns = st.columns(2)
                sources = filter_columns[0].multiselect(
                    "Sources",
                    options(jobs, "source_name"),
                    key="cockpit_filter_sources",
                )
                locations = filter_columns[1].multiselect(
                    "Lieux",
                    options(jobs, "city"),
                    key="cockpit_filter_locations",
                )
                filter_options = st.columns([1, 2])
                remote_only = filter_options[0].toggle(
                    "Télétravail",
                    key="cockpit_filter_remote",
                )
                minimum_score = filter_options[1].slider(
                    "Score min.",
                    min_value=0,
                    max_value=100,
                    value=0,
                    step=5,
                    key="cockpit_filter_score",
                )


######### -------------------------------------- Bloc de préparation du filtre actif  ------------------------------------- #########

# Instanciation des filtres actifs pour affichage.
active_filters = []
if query.strip():
    active_filters.append(f"recherche « {query.strip()} »")
if sources:
    active_filters.append(f"{len(sources)} source(s)")
if locations:
    active_filters.append(f"{len(locations)} lieu(x)")
if remote_only:
    active_filters.append("télétravail")
if minimum_score:
    active_filters.append(f"score ≥ {minimum_score}")
if active_filters:
    st.caption("Filtres actifs : " + ", ".join(active_filters))

# Instanciation des statuts disponibles dans le filtre Flux, en excluant ÉCARTÉE.
flux_status_options = tuple(
    status for status in JOB_STATUS_OPTIONS if status != "ÉCARTÉE"
)

# Organise les metrics interactives.
indicator_row = st.columns(
    [1.2, 1.1, 1, 1, 1, 1, 1],
    vertical_alignment="bottom",
)
# Bouton de sélection du statut des annonces à afficher dans le flux.
flux_status = indicator_row[0].selectbox(
    "Flux — statut",
    flux_status_options,
    index=flux_status_options.index("À ÉTUDIER"),
    format_func=lambda status: status.lower().capitalize(),
    key="cockpit_flux_status",
    on_change=lambda: st.session_state.update(cockpit_metric_filter="flux"),
)
# Bouton de sélection de la période pour les annonces récentes.
recent_period = indicator_row[1].selectbox(
    "Nouvelles — période",
    ("1 jour", "3 jours", "7 jours", "1 mois"),
    index=2,
    key="cockpit_recent_period",
)

# Instanciation des valeurs des métriques temporelles. 
recent_days = {
    "1 jour": 1,
    "3 jours": 3,
    "7 jours": 7,
    "1 mois": 30,
}[recent_period]

# Récupération des métadonnées de comptage des annonces pour les métriques interactives.
counts = metric_counts(jobs, recent_days=recent_days)
# Récupération du meilleur score de matching parmi les annonces.
scores = pd.to_numeric(jobs.get("match_score"), errors="coerce")
best_score = scores.max() if not jobs.empty else None

# Récupération du filtre actif pour l'affichage des annonces.
metric_filter = st.session_state.get("cockpit_metric_filter", "flux")
# Normalisation des statuts des annonces pour permettre une comparaison fiable.
job_statuses = jobs["status"].fillna("NOUVELLE").astype(str).str.strip().str.upper()

flux_count = int(job_statuses.eq(flux_status).sum())


######### -------------------------------------- Bloc d'affichage des métriques interactives  ------------------------------------- #########

# Instanciation des paramètres d'affichage des métriques interactives.
metric_definitions = (
    (
        "Flux",
        str(flux_count),
        "flux",
        f"Afficher les annonces au statut {flux_status.lower()}",
    ),
    (
        "Nouvelles",
        str(counts["recent"]),
        "recent",
        f"Annonces publiées sur la période : {recent_period.lower()}",
    ),
    (
        "Exploitables",
        str(counts["complete"]),
        "complete",
        "Descriptions complètes et matching disponible",
    ),
    (
        "À enrichir",
        str(counts["incomplete"]),
        "enrichment",
        "Ouvrir la page dédiée au réenrichissement",
    ),
    (
        "Meilleur",
        display_score(best_score),
        "best",
        "Annonce(s) ayant le meilleur score courant",
    ),
)

for index, (label, value, filter_name, help_text) in enumerate(
    metric_definitions, start=2
):
    #Récupère les paramètres d'affichage des métriques et crée un bouton interactif pour chaque métrique.
    button_type = "primary" if metric_filter == filter_name else "secondary"
    if indicator_row[index].button(
        f"{label} · {value}",
        key=f"metric_{filter_name}",
        help=help_text,
        type=button_type,
        use_container_width=True,
    ):
        if filter_name == "enrichment":
            st.switch_page("page_enrichment.py")
        st.session_state.cockpit_metric_filter = filter_name
        st.rerun()

######### -------------------------------------- Bloc de filtrage des annonces  ------------------------------------- #########

# Filtrage pour les annonces en candidature si le mode rapide est sélectionné.
statuses: list[str] = []
if quick_mode == "Candidatures":
    statuses = ["RETENUE", "CANDIDATURE ENVOYÉE", "ENTRETIEN"]

# Instanciation des paramètres de filtrage des anonces en fonction des filtres sélectionnés par l'utilisateur.
filtered = filter_jobs(
    jobs,
    query=query,
    statuses=statuses,
    sources=sources,
    locations=locations,
    remote_only=remote_only, ### A VERIFIER : Système de filtrage du télétravail basé sur la valeur de remote_policy. ###
    minimum_score=minimum_score,
)

active_metric_label = "Toutes les annonces"
# Filtrage du statut des annonces.
if metric_filter == "flux":
    filtered_statuses = (
        filtered["status"]
        .fillna("NOUVELLE")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    filtered = filtered[filtered_statuses.eq(flux_status)]
    active_metric_label = f"Flux · {flux_status.lower().capitalize()}"
# Filtrage temporel des annonces.
elif metric_filter == "recent":
    boundary = pd.Timestamp(
        (date.today() - timedelta(days=recent_days)).isoformat()
    )
    dates = pd.to_datetime(filtered["publication_date"], errors="coerce")
    filtered = filtered[dates >= boundary]
    active_metric_label = f"Publiées sur {recent_period.lower()}"
# Filtrage des annonces exploitables.
elif metric_filter == "complete":
    filtered = filtered[filtered["description_is_full"] == True]
    active_metric_label = "Exploitables"
# Filtrage des annonces ayant le meilleur score.
elif metric_filter == "best":
    filtered_scores = pd.to_numeric(filtered["match_score"], errors="coerce")
    current_best = filtered_scores.max()
    filtered = filtered[filtered_scores == current_best]
    active_metric_label = "Meilleur score"
# Filtrage des annonces prioritaires si le mode rapide est sélectionné.
if quick_mode == "Priorités":
    filtered_scores = pd.to_numeric(filtered["match_score"], errors="coerce")
    filtered = filtered[filtered_scores >= max(70, minimum_score)]
# Tri des annonces par score et date de publication.
sort_score = pd.to_numeric(filtered.get("match_score"), errors="coerce")
filtered = (
    filtered.assign(_score=sort_score)
    .sort_values(["_score", "publication_date"], ascending=[False, False])
    .drop(columns="_score")
)

######## -------------------------------------- Bloc d'affichage des annonces filtrées  ------------------------------------- #########

# Affichage du nombre d'annonces filtrées. 
st.subheader(f"{active_metric_label} · {len(filtered)} résultat(s)")
if filtered.empty:
    st.info("Aucune annonce ne correspond à cette sélection.")

# Parcourt les annonces filtrées et affichage sous forme de cartes.
for start in range(0, len(filtered), 2):
    cards = st.columns(2)
    for column, (_, row) in zip(
        cards, filtered.iloc[start : start + 2].iterrows()
    ):
        # Organise le containeur de chaque carte d'annonce.
        with column.container(border=True):
            headline = st.columns([4, 1])
            headline[0].subheader(str(row.get("job_title") or "Sans titre"))
            headline[1].metric("Score", display_score(row.get("match_score")))
            st.write(f"**{row.get('company_name') or 'Entreprise inconnue'}**")
            st.caption(
                " · ".join(
                    value
                    for value in (
                        str(row.get("city") or "Lieu non précisé"),
                        str(row.get("remote_policy") or "Sur site / inconnu"),
                        display_salary(row),
                    )
                    if value
                )
            )
            st.write(
                f"`{row.get('status') or 'NOUVELLE'}` · "
                f"{row.get('source_name') or 'Source inconnue'} · "
                f"{display_date(row.get('publication_date'))}"
            )
            current_status = str(row.get("status") or "NOUVELLE")
            # Bouton de changement des statuts des annonces avec un popover pour sélectionner le nouveau statut.
            with st.popover(
                "Changer le statut",
                key=f"card_status_popover_{int(row['id'])}",
                use_container_width=True,
            ):
                status_index = (
                    list(JOB_STATUS_OPTIONS).index(current_status)
                    if current_status in JOB_STATUS_OPTIONS
                    else 0
                )
                card_status = st.selectbox(
                    "Nouveau statut",
                    JOB_STATUS_OPTIONS,
                    index=status_index,
                    key=f"card_status_select_{int(row['id'])}",
                )
                # Bouton d'enregistrement du nouveau statut de l'annonce et actualisation du statut dans la base de données.
                if st.button(
                    "Enregistrer",
                    key=f"card_status_save_{int(row['id'])}",
                    type="primary",
                    use_container_width=True,
                ):
                    repository.update_job_status(int(row["id"]), card_status)
                    st.rerun()
            # Affichage du matching de l'annonce avec un expander pour afficher le détail du matching.
            with st.expander("Analyse du matching"):
                render_matching_category_summary(row)
                if st.button(
                    "Ouvrir la fiche complète",
                    key=f"open_job_detail_{int(row['id'])}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state.selected_job_id = int(row["id"])
                    st.switch_page("page_job_detail.py")
