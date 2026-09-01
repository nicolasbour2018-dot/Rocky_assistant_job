"""Cockpit opérationnel de Rocky.

Cette page transforme les annonces du profil actif en vues de décision
("Nouvelles", "Mes annonces" et "Tout le flux"). Elle applique les périodes,
statuts et seuils de matching sans modifier les données persistées ; les
actions métier restent déléguées aux services Rocky dédiés.
"""

# Importation des librairies standardes
from __future__ import annotations
from zoneinfo import ZoneInfo
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
    options,
    render_matching_category_summary,
    run_watch,
    jobs_to_enrich,
)
## Importation des constantes de statuts de jobs ##
from dashboard.rocky.statuses import JOB_STATUS_OPTIONS


st.markdown('<div class="rocky-kicker">Recherche & décisions</div>', unsafe_allow_html=True)
st.title("Rocky Assistant Recherche d'emploi · V2")
st.caption("Cockpit personnel · veille, matching et prochaines actions")
st.markdown(
    '<div class="rocky-hero"><strong>Ton terrain de jeu pour la prochaine bonne opportunité.</strong><br>'
    'Explore les suggestions, ajuste ton profil et laisse Rocky te guider vers les annonces qui comptent.</div>',
    unsafe_allow_html=True,
)


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


def _status_series(frame: pd.DataFrame) -> pd.Series:
    """Normalise le statut pour filtrer le flux, y compris sur données incomplètes."""
    return frame["status"].fillna("NOUVELLE").astype(str).str.strip().str.upper()


def _exploitable_jobs(frame: pd.DataFrame) -> pd.DataFrame:
    """Écarte les annonces techniques du cockpit pour ne garder que les pistes métier."""
    full = frame["description_is_full"].fillna(False).astype(bool)
    scores = pd.to_numeric(frame["match_score"], errors="coerce")
    return frame[full & scores.notna()].copy()


def _jobs_from_watch_run(
    frame: pd.DataFrame, watch_run: dict[str, object] | None
) -> pd.DataFrame:
    """Isole les annonces découvertes lors de la dernière veille terminée."""
    if not watch_run:
        return frame.iloc[0:0].copy()
    created = pd.to_datetime(frame["created_at"], errors="coerce", utc=True)
    started = pd.to_datetime(watch_run["started_at"], errors="coerce", utc=True)
    finished = pd.to_datetime(watch_run["finished_at"], errors="coerce", utc=True)
    if pd.isna(started) or pd.isna(finished):
        return frame.iloc[0:0].copy()
    return frame[(created >= started) & (created <= finished)].copy()


def _sort_jobs(frame: pd.DataFrame, order: str) -> pd.DataFrame:
    """Ordonne les pistes selon la priorité de consultation, sans réécrire leur score."""
    sorted_jobs = frame.copy()
    sorted_jobs["_publication"] = pd.to_datetime(
        sorted_jobs["publication_date"].astype(object),
        errors="coerce",
        utc=True,
    )
    sorted_jobs["_created"] = pd.to_datetime(
        sorted_jobs["created_at"].astype(object),
        errors="coerce",
        utc=True,
    )
    if order == "Meilleur score":
        sorted_jobs["_score"] = pd.to_numeric(
            sorted_jobs["match_score"], errors="coerce"
        )
        return sorted_jobs.sort_values(
            ["_score", "_publication", "_created"],
            ascending=[False, False, False],
        ).drop(columns=["_score", "_publication", "_created"])
    sorted_jobs["_recent"] = sorted_jobs["_publication"].fillna(
        sorted_jobs["_created"]
    )
    return sorted_jobs.sort_values(
        ["_recent", "_created"], ascending=[False, False]
    ).drop(columns=["_publication", "_created", "_recent"])


def _sort_new_jobs(frame: pd.DataFrame) -> pd.DataFrame:
    """Favorise les annonces nouvellement importées dans la carte Nouvelles."""
    sorted_jobs = frame.copy()
    sorted_jobs["_created"] = pd.to_datetime(
        sorted_jobs["created_at"].astype(object),
        errors="coerce",
        utc=True,
    )
    return sorted_jobs.sort_values("_created", ascending=False).drop(
        columns="_created"
    )


def _published_in_local_period(frame: pd.DataFrame, period: str) -> pd.Series:
    """Retourne les annonces publiées dans la fenêtre calendaire Europe/Paris.

    Les filtres 1, 3 et 7 jours répondent à la fraîcheur de l'offre côté
    employeur. « Dernière veille » reste traité à part avec ``created_at`` car
    il décrit ce que Rocky vient précisément de découvrir.
    """
    days = {"1 jour": 1, "3 jours": 3, "7 jours": 7}[period]
    published = pd.to_datetime(frame["publication_date"], errors="coerce")
    today = pd.Timestamp.now(tz=ZoneInfo("Europe/Paris")).normalize().tz_localize(
        None
    )
    boundary = today - pd.Timedelta(days - 1, unit="D")
    return published.ge(boundary) & published.le(today)


def _jobs_above_threshold(frame: pd.DataFrame, threshold: int) -> pd.DataFrame:
    """Garde les annonces dont le score atteint le seuil global du Cockpit."""
    scores = pd.to_numeric(frame["match_score"], errors="coerce")
    return frame[scores >= int(threshold)].copy()


last_watch_run = (
    repository.fetch_latest_completed_watch_run(profile.id) if profile else None
)
last_watch_jobs = _jobs_from_watch_run(jobs, last_watch_run)
exploitable = _exploitable_jobs(jobs)
last_watch_exploitable = _exploitable_jobs(last_watch_jobs)
new_exploitable = exploitable[_status_series(exploitable).eq("NOUVELLE")]
cockpit_threshold = int(
    st.session_state.get("watch_threshold_v2", settings.match_threshold)
)
new_qualified = _jobs_above_threshold(new_exploitable, cockpit_threshold)
suggestions = new_exploitable.loc[
    new_exploitable.index.intersection(last_watch_exploitable.index)
]
suggestions = suggestions[
    pd.to_numeric(suggestions["match_score"], errors="coerce") >= 80
]

watch_summary = st.session_state.get("watch_summary_v2")
watch_feedback = None
if (
    watch_summary
    and watch_summary.get("status") == "SUCCESS"
    and last_watch_run
    and st.session_state.get("cockpit_feedback_watch_run")
    != watch_summary.get("run_id")
):
    inserted_count = int(last_watch_run.get("inserted_count") or 0)
    recommendation_count = int(
        (pd.to_numeric(last_watch_exploitable["match_score"], errors="coerce") >= 80).sum()
    )
    st.session_state.cockpit_view = "suggestions"
    st.session_state.cockpit_feedback_watch_run = watch_summary.get("run_id")
    watch_feedback = (
        "Veille terminée — "
        f"{inserted_count} nouvelles annonces ajoutées, dont "
        f"{recommendation_count} recommandations à 80 % ou plus."
    )


######### -------------------------------------- Bloc d'affichage des outils de veille et de filtrage des annonces ------------------------------------- #########

## Organise le containeur avec les boutons de récupération de la veille manuelle et le filtrage des resultats. ##
with st.container(border=True):
    st.caption("VEILLE MANUELLE")
    run_watch(settings, repository, "v2")

period = st.session_state.get("cockpit_new_period", "1 jour")
if period == "Dernière veille":
    new_count = len(
        new_qualified.loc[new_qualified.index.intersection(last_watch_jobs.index)]
    )
else:
    new_count = int(_published_in_local_period(new_qualified, period).sum())

my_statuses = ("À ÉTUDIER", "RETENUE", "CANDIDATURE ENVOYÉE", "ENTRETIEN", "REFUS")
my_jobs = _jobs_above_threshold(
    exploitable[_status_series(exploitable).isin(my_statuses)],
    cockpit_threshold,
)
flow_jobs = _jobs_above_threshold(
    exploitable[
        _status_series(exploitable).isin(("NOUVELLE", "ANCIENNE") + my_statuses)
    ],
    cockpit_threshold,
)
active_view = st.session_state.get("cockpit_view", "suggestions")
view_definitions = (
    ("Suggestions", "suggestions", len(suggestions)),
    ("Nouvelles", "new", new_count),
    ("À enrichir", "enrichment", len(jobs_to_enrich(jobs))),
    ("Mes annonces", "mine", len(my_jobs)),
    ("Tout le flux", "flow", len(flow_jobs)),
)
for column, (label, view_name, count) in zip(st.columns(5), view_definitions):
    if column.button(
        f"{label} · {count}", key=f"cockpit_view_{view_name}",
        type="primary" if active_view == view_name else "secondary",
        use_container_width=True,
    ):
        if view_name == "enrichment":
            st.switch_page("page_enrichment.py")
        st.session_state.cockpit_view = view_name
        st.rerun()

if watch_feedback:
    st.success(watch_feedback)

# Petit raccourci contextuel : Rocky met en avant une action utile sans
# modifier les données. La priorité est donnée aux réponses Gmail à vérifier,
# puis aux annonces incomplètes, afin d'éviter que la prochaine étape se perde
# dans la navigation.
try:
    pending_email_count = len(repository.fetch_pending_email_messages())
except Exception:
    pending_email_count = 0
enrichment_count = len(jobs_to_enrich(jobs))
if pending_email_count:
    next_action_title = f"📬 {pending_email_count} réponse(s) à vérifier"
    next_action_hint = "Valide les retours Gmail pour garder tes candidatures à jour."
    next_action_page = "page_applications.py"
    next_action_key = "cockpit_next_email"
elif enrichment_count:
    next_action_title = f"🧩 {enrichment_count} annonce(s) à enrichir"
    next_action_hint = "Complète les annonces incomplètes avant de comparer les scores."
    next_action_page = "page_enrichment.py"
    next_action_key = "cockpit_next_enrichment"
else:
    next_action_title = "✨ Rien ne presse — explore tes suggestions"
    next_action_hint = "Ton cockpit est à jour. Lance une veille quand tu veux relancer la recherche."
    next_action_page = None
    next_action_key = "cockpit_next_suggestions"
with st.container(border=True):
    action_col, button_col = st.columns([3, 1], vertical_alignment="center")
    with action_col:
        st.caption("PROCHAINE ACTION")
        st.markdown(f"**{next_action_title}**")
        st.caption(next_action_hint)
    with button_col:
        if st.button(
            "Ouvrir" if next_action_page else "Voir mes suggestions",
            key=next_action_key,
            use_container_width=True,
        ):
            if next_action_page:
                st.switch_page(next_action_page)
            st.session_state.cockpit_view = "suggestions"
            st.rerun()

######### -------------------------------------- Bloc de filtrage des annonces  ------------------------------------- #########

query = ""
statuses: list[str] = []
sources: list[str] = []
locations: list[str] = []
remote_only = False

if active_view == "suggestions":
    filtered = _sort_jobs(suggestions, "Meilleur score")
    active_metric_label = "Suggestions"
elif active_view == "new":
    period = st.selectbox(
        "Période", ("Dernière veille", "1 jour", "3 jours", "7 jours"),
        index=("Dernière veille", "1 jour", "3 jours", "7 jours").index(period),
        key="cockpit_new_period",
        help=(
            "Les périodes 1, 3 et 7 jours utilisent la date de publication. "
            "« Dernière veille » affiche les annonces ajoutées par la dernière "
            "collecte Rocky."
        ),
    )
    if period == "Dernière veille":
        filtered = new_qualified.loc[
            new_qualified.index.intersection(last_watch_jobs.index)
        ]
    else:
        filtered = new_qualified[_published_in_local_period(new_qualified, period)]
    filtered = _sort_new_jobs(filtered)
    active_metric_label = f"Nouvelles · {period}"
    st.caption(
        f"Seuil de score appliqué : {cockpit_threshold} %. Ajuste-le depuis "
        "« Veille manuelle » si nécessaire."
    )
elif active_view == "mine":
    selected_status = st.selectbox("Statut", my_statuses, index=my_statuses.index("À ÉTUDIER"), key="cockpit_my_status")
    filtered = my_jobs[_status_series(my_jobs).eq(selected_status)]
    active_metric_label = f"Mes annonces · {selected_status.lower().capitalize()}"
    st.caption(
        f"Seuil de score appliqué : {cockpit_threshold} %. Ajuste-le depuis "
        "« Veille manuelle » si nécessaire."
    )
elif active_view == "flow":
    filtered = flow_jobs.copy()
    active_metric_label = "Tout le flux"
    st.caption(
        f"Seuil de score appliqué : {cockpit_threshold} %. Ajuste-le depuis "
        "« Veille manuelle » si nécessaire."
    )
else:
    filtered = jobs.iloc[0:0].copy()
    active_metric_label = "Suggestions"

if active_view in {"mine", "flow"}:
    with st.popover("Filtres avancés", use_container_width=True):
        query = st.text_input("Recherche", placeholder="Poste ou entreprise", key="cockpit_filter_query")
        filter_columns = st.columns(2)
        sources = filter_columns[0].multiselect("Sources", options(filtered, "source_name"), key="cockpit_filter_sources")
        locations = filter_columns[1].multiselect("Lieux", options(filtered, "city"), key="cockpit_filter_locations")
        if active_view == "flow":
            # « Mes annonces » possède déjà son sélecteur de statut dédié ; le
            # filtre multi-statut est réservé au flux complet du Cockpit.
            statuses = st.multiselect(
                "Statuts",
                options(filtered, "status"),
                key="cockpit_filter_statuses",
            )
        remote_only = st.toggle("Télétravail", key="cockpit_filter_remote")
    filtered = filter_jobs(
        filtered,
        query=query,
        statuses=statuses,
        sources=sources,
        locations=locations,
        remote_only=remote_only,
    )
    sort_order = st.selectbox("Tri", ("Plus récentes", "Meilleur score"), key=f"cockpit_sort_{active_view}")
    filtered = _sort_jobs(filtered, sort_order)
    active_filters = []
    if query.strip():
        active_filters.append(f"recherche « {query.strip()} »")
    if statuses:
        active_filters.append(f"{len(statuses)} statut(s)")
    if sources:
        active_filters.append(f"{len(sources)} source(s)")
    if locations:
        active_filters.append(f"{len(locations)} lieu(x)")
    if remote_only:
        active_filters.append("télétravail")
    if active_filters:
        st.caption("Filtres actifs : " + ", ".join(active_filters))

######## -------------------------------------- Bloc d'affichage des annonces filtrées  ------------------------------------- #########

# Affichage du nombre d'annonces filtrées.
st.subheader(f"{active_metric_label} · {len(filtered)} résultat(s)")
if filtered.empty:
    if active_view == "suggestions":
        last_inserted = int(last_watch_run.get("inserted_count") or 0) if last_watch_run else 0
        recommendation_count = int((pd.to_numeric(last_watch_exploitable["match_score"], errors="coerce") >= 80).sum())
        if not last_watch_run:
            st.info("Aucune veille terminée pour ce profil. Lance une veille pour obtenir des suggestions.")
        elif last_inserted == 0:
            st.info("Dernière veille terminée : aucune nouvelle annonce ajoutée.")
        elif recommendation_count == 0:
            st.info("Dernière veille : aucune nouvelle recommandation à 80 % ou plus.")
        else:
            st.info("Toutes les recommandations de la dernière veille ont été traitées.")
    elif active_view == "new":
        st.info("Aucune nouvelle annonce non traitée sur la période sélectionnée.")
    elif active_view == "mine":
        st.info(f"Aucune annonce au statut « {selected_status} ».")
    else:
        st.info("Aucune annonce exploitable ne correspond aux filtres.")

# Parcourt les annonces filtrées et affichage sous forme de cartes.
for start in range(0, len(filtered), 2):
    cards = st.columns(2)
    for column, (_, row) in zip(
        cards, filtered.iloc[start : start + 2].iterrows()
    ):
        # Organise le containeur de chaque carte d'annonce.
        with column.container(border=True):
            # Réserver assez d'espace au score pour éviter le tronquage dans
            # les cartes à deux colonnes, notamment sur les écrans étroits.
            headline = st.columns([3.25, 1.75])
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
            if st.button(
                "Ouvrir la fiche complète",
                key=f"open_job_detail_{int(row['id'])}",
                type="primary",
                use_container_width=True,
            ):
                st.session_state.selected_job_id = int(row["id"])
                st.switch_page("page_job_detail.py")
            # Bouton de changement des statuts des annonces avec un popover pour sélectionner le nouveau statut.
            with st.popover(
                f"Changer le statut · #{int(row['id'])}",
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
