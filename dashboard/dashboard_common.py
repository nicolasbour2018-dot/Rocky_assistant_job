"""Composants fonctionnels partagés par les pages de Rocky V2."""

# importation des librairies standard
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

#Ajoute la racine du projet au sys.path afin de rendre les modules internes de Rocky importables depuis ce script.
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Importation des modules internes de Rocky (Back-end)
from dashboard.job_analysis import (
    BUSINESS_SKILLS,
    SOFT_SKILLS,
    TECHNICAL_SKILLS,
)
from dashboard.rocky.bootstrap import bootstrap_default_profile
from dashboard.rocky.config import Settings
from dashboard.rocky.database import (
    create_db_engine,
    ensure_database_exists,
    initialize_database,
)
from dashboard.rocky.enrichment import reenrich_saved_job
from dashboard.rocky.errors import RockyError
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.matching import calculate_match
from dashboard.rocky.models import CandidateProfile, MatchResult
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.sources import build_watch_sources
from dashboard.rocky.statuses import INCOMPLETE_STATUS, JOB_STATUS_OPTIONS
from dashboard.rocky.text_utils import ensure_list, normalize_text
from dashboard.rocky.watch import WatchService


HIDDEN_JOB_STATUSES = {"ÉCARTÉE"}



###################################################################################################################################################
# Bloc de récupération et de filtrage des annonces pour le cockpit Rocky
###################################################################################################################################################

def selected_row_ids(
    frame: pd.DataFrame,
    positions: list[int] | tuple[int, ...],
    id_column: str = "id",
) -> list[int]:
    """Convertit une sélection Streamlit en ignorant les positions périmées. Évite l'erreur d'index lorsque le DataFrame est filtré ou trié."""
    if frame.empty or id_column not in frame:
        return []
    selected: list[int] = []
    for position in positions:
        if not isinstance(position, int) or not 0 <= position < len(frame):
            continue
        selected.append(int(frame.iloc[position][id_column]))
    return list(dict.fromkeys(selected))


def _optional_number(value: Any) -> float | None:
    """ Fonction utilitaire pour convertir une valeur en nombre décimal ou retourner None si la conversion échoue. """
    try:
        if value in (None, "") or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def match_from_row(row: Any) -> MatchResult | None:
    """Reconstruit le dernier résultat de matching enregistré pour la vue."""
    score = _optional_number(row.get("match_score"))
    breakdown = row.get("match_breakdown")
    if isinstance(breakdown, str):
        try:
            breakdown = json.loads(breakdown)
        except json.JSONDecodeError:
            breakdown = {}
    if score is None or not isinstance(breakdown, dict):
        return None
    skill_details = breakdown.get("skills", {})
    detected = (
        ensure_list(skill_details.get("detected_skills"))
        if isinstance(skill_details, dict)
        else []
    )
    return MatchResult(
        score=score,
        breakdown=breakdown,
        strengths=ensure_list(row.get("match_strengths")),
        gaps=ensure_list(row.get("match_gaps")),
        detected_job_skills=detected or ensure_list(row.get("required_skills")),
    )


def _coverage(
    detected: list[str], matched_keys: set[str], category_keys: set[str]
) -> dict[str, Any]:
    """ Calcule le taux de couverture des compétences détectées pour une catégorie donnée :(technical ou transversal). """
    category_skills = [
        skill for skill in detected if normalize_text(skill) in category_keys
    ]
    matched = [
        skill for skill in category_skills if normalize_text(skill) in matched_keys
    ]
    score = (
        round(100 * len(matched) / len(category_skills), 1)
        if category_skills
        else None
    )
    return {
        "score": score,
        "detected": category_skills,
        "matched": matched,
        "missing": [skill for skill in category_skills if skill not in matched],
    }


def matching_category_summary(row: Any) -> dict[str, Any] | None:
    """Décline la composante compétences sans modifier le moteur de score.

    Les rapprochements « proches » sont uniquement des aides à la vérification
    humaine. Ils ne transforment jamais une compétence en correspondance.

    Construit un dictionnaire de vue détaillée du matching par compétences techniques et transversales, 
    et propose des rapprochements textuels pour les compétences non reconnues, uniquement 
    à titre d’aide à la vérification.
    """
    result = match_from_row(row)
    if result is None:
        return None
    details = result.breakdown.get("skills", {})
    if not isinstance(details, dict):
        details = {}
    detected = ensure_list(details.get("detected_skills")) or list(
        result.detected_job_skills
    )
    matched = ensure_list(details.get("matched_skills"))
    profile_skills = ensure_list(details.get("profile_skills"))
    matched_keys = {normalize_text(skill) for skill in matched}
    profile_by_key = {
        normalize_text(skill): skill for skill in profile_skills if normalize_text(skill)
    }
    technical_keys = {normalize_text(skill) for skill in TECHNICAL_SKILLS}
    transversal_keys = {
        normalize_text(skill) for skill in BUSINESS_SKILLS | SOFT_SKILLS
    }
    technical = _coverage(detected, matched_keys, technical_keys)
    transversal = _coverage(detected, matched_keys, transversal_keys)

    missing = [skill for skill in detected if normalize_text(skill) not in matched_keys]
    to_review: list[dict[str, Any]] = []
    for skill in missing:
        skill_key = normalize_text(skill)
        closest_name = ""
        closest_ratio = 0.0
        for profile_key, profile_name in profile_by_key.items():
            ratio = SequenceMatcher(None, skill_key, profile_key).ratio()
            if ratio > closest_ratio:
                closest_name = profile_name
                closest_ratio = ratio
        to_review.append(
            {
                "skill": skill,
                "close_profile_skill": closest_name if closest_ratio >= 0.52 else "",
                "similarity": round(closest_ratio * 100),
            }
        )
    return {
        "score": result.score,
        "technical": technical,
        "transversal": transversal,
        "to_review": to_review,
        "result": result,
    }

###################################################################################################################################################
# Bloc d'orchestration de l'affichage des détails d'une annonce.
###################################################################################################################################################

def render_matching_category_summary(row: Any) -> None:
    """ Affiche dans le cockpit le détail des compétences techniques, transversales et à vérifier."""
    if not bool(row.get("description_is_full")):
        st.warning("Description incomplète : le matching complet est suspendu.")
        return
    summary = matching_category_summary(row)
    if summary is None:
        st.info("Aucun matching enregistré pour cette annonce.")
        return
    columns = st.columns(3)
    for column, label, category in (
        (columns[0], "Techniques", summary["technical"]),
        (columns[1], "Transversales", summary["transversal"]),
    ):
        score = category["score"]
        column.metric(label, f"{score:.0f} %" if score is not None else "—")
        column.caption(
            f"{len(category['matched'])} / {len(category['detected'])} reconnue(s)"
        )
    columns[2].metric("À vérifier", len(summary["to_review"]))
    close_matches = [
        f"{item['skill']} ≈ {item['close_profile_skill']}"
        for item in summary["to_review"]
        if item["close_profile_skill"]
    ]
    columns[2].caption(
        ", ".join(close_matches[:3])
        if close_matches
        else "Compétences non reconnues dans le profil"
    )
    st.caption(
        "Ce détail explique la composante compétences ; les suggestions "
        "« à vérifier » ne sont pas comptées comme des correspondances."
    )


def visible_jobs(jobs: pd.DataFrame) -> pd.DataFrame:
    """Masque les annonces archivées de V2 sans les supprimer de la base."""
    if jobs.empty or "status" not in jobs:
        return jobs.copy()
    statuses = jobs["status"].fillna("").astype(str).str.strip().str.upper()
    return jobs[~statuses.isin(HIDDEN_JOB_STATUSES)].copy()


def jobs_to_enrich(jobs: pd.DataFrame) -> pd.DataFrame:
    """Retourne uniquement la file utilisateur au statut INCOMPLÈTE."""
    if jobs.empty or "status" not in jobs:
        return jobs.iloc[0:0].copy()
    statuses = jobs["status"].fillna("").astype(str).str.strip().str.upper()
    selected = statuses.eq(INCOMPLETE_STATUS)
    if "description_is_full" in jobs:
        selected &= ~jobs["description_is_full"].fillna(False).astype(bool)
    return jobs[selected].copy()

###################################################################################################################################################
# Bloc de chargement des données et de nettoyage pour le cockpit Rocky
####################################################################################################################################################

@st.cache_resource
def load_repository() -> RockyRepository:
    """Charge le repo Rocky avec la base de données et le profil par défaut."""
    settings = Settings()
    ensure_database_exists(settings)
    engine = create_db_engine(settings)
    initialize_database(engine, settings)
    repository = RockyRepository(engine)
    bootstrap_default_profile(settings, repository)
    return repository


def load_data() -> tuple[
    Settings, RockyRepository, CandidateProfile | None, pd.DataFrame
]:
    """Charge les paramètres, le repo, le profil actif et les annonces visibles."""
    settings = Settings()
    repository = load_repository()
    profile = repository.fetch_active_profile()
    jobs = visible_jobs(
        repository.get_jobs_for_profile(profile.id)
        if profile
        else repository.fetch_jobs()
    )
    return settings, repository, profile, jobs


def options(frame: pd.DataFrame, column: str) -> list[str]:
    """Fonction utilitaire : Retourne les valeurs uniques d’une colonne de DataFrame, triées et nettoyées."""
    if frame.empty or column not in frame:
        return []
    values = {
        str(value).strip()
        for value in frame[column].dropna().tolist()
        if str(value).strip()
    }
    return sorted(values, key=normalize_text)


def filter_jobs(
    jobs: pd.DataFrame,
    *,
    query: str = "",
    statuses: list[str] | None = None,
    sources: list[str] | None = None,
    locations: list[str] | None = None,
    remote_only: bool = False,
    incomplete_only: bool = False,
    minimum_score: int = 0,
) -> pd.DataFrame:
    """ Filtre pour les annonces selon les critères de recherche et retourne un DataFrame filtré."""
    filtered = jobs.copy()
    if query.strip():
        needle = normalize_text(query)
        searchable = (
            filtered["job_title"].fillna("").astype(str)
            + " "
            + filtered["company_name"].fillna("").astype(str)
        ).map(normalize_text)
        filtered = filtered[searchable.str.contains(needle, regex=False)]
    for column, selected in (
        ("status", statuses or []),
        ("source_name", sources or []),
        ("city", locations or []),
    ):
        if selected:
            filtered = filtered[
                filtered[column].fillna("").astype(str).isin(selected)
            ]
    if remote_only:
        remote = filtered["remote_policy"].fillna("").astype(str)
        filtered = filtered[remote.str.strip().ne("")]
    if incomplete_only:
        filtered = jobs_to_enrich(filtered)
    if minimum_score > 0:
        score = pd.to_numeric(filtered["match_score"], errors="coerce")
        filtered = filtered[score >= minimum_score]
    return filtered


def display_score(value: Any) -> str:
    """ Formatte le score de matching en pourcentage."""
    try:
        if pd.isna(value):
            return "—"
        return f"{float(value):.0f} %"
    except (TypeError, ValueError):
        return "—"


def display_date(value: Any) -> str:
    if value in (None, ""):
        return "Date inconnue"
    try:
        parsed = pd.to_datetime(value)
        return parsed.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(value)


def display_salary(row: Any) -> str:
    """ Formatte le salaire avec la devise. """
    minimum = row.get("salary_min")
    maximum = row.get("salary_max")
    currency = str(row.get("salary_currency") or "EUR")
    try:
        has_minimum = minimum is not None and not pd.isna(minimum)
        has_maximum = maximum is not None and not pd.isna(maximum)
    except TypeError:
        has_minimum = minimum is not None
        has_maximum = maximum is not None
    if has_minimum and has_maximum:
        return f"{float(minimum):,.0f}–{float(maximum):,.0f} {currency}".replace(
            ",", " "
        )
    if has_minimum:
        return f"Dès {float(minimum):,.0f} {currency}".replace(",", " ")
    if has_maximum:
        return f"Jusqu’à {float(maximum):,.0f} {currency}".replace(",", " ")
    return "Salaire non précisé"


def plain_description(value: Any) -> str:
    """ Nettoie les descriptions HTML pour l’affichage dans Streamlit, 
    en supprimant les balises et en décodant les entités HTML. """
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return unescape(soup.get_text(" ", strip=True))

###################################################################################################################################################
# Bloc d'orchestration de la veille (Watchservices).
###################################################################################################################################################

def run_watch(
    settings: Settings,
    repository: RockyRepository,
    key: str,
) -> None:
    """ Orchestre la veille avec les paramètres de seuil choisis par l’utilisateur et le lancement de WatchService. """
    threshold_key = f"watch_threshold_{key}"
    if threshold_key not in st.session_state:
        st.session_state[threshold_key] = max(
            0, min(100, int(settings.match_threshold))
        )
    controls = st.columns([1.4, 1])
    launch = controls[0].button(
        "Lancer la veille",
        type="primary",
        key=f"watch_{key}",
        use_container_width=True,
    )
    with controls[1]:
        with st.popover(
            f"Seuil · {int(st.session_state[threshold_key])} %",
            use_container_width=True,
        ):
            selected_threshold = st.slider(
                "Seuil minimal de matching",
                min_value=0,
                max_value=100,
                step=5,
                key=threshold_key,
                help=(
                    "Les annonces complètes sous ce score ne seront pas "
                    "enregistrées pendant cette veille."
                ),
            )
            st.caption(
                "Ce réglage s’applique aux veilles lancées dans cette session. "
                "Le seuil par défaut du .env n’est pas modifié."
            )
    # Orchestration de la veille (WatchService).
    if launch:
        watch_settings = replace(
            settings,
            match_threshold=int(selected_threshold),
        )
        with st.spinner("Recherche des nouvelles annonces…"):
            summary = WatchService(
                watch_settings,
                repository,
                build_watch_sources(watch_settings),
            ).run()
        summary["match_threshold"] = int(selected_threshold)
        st.session_state[f"watch_summary_{key}"] = summary
        st.rerun()
    summary = st.session_state.get(f"watch_summary_{key}")
    if summary:
        st.caption(
            f"Dernière veille : {summary['inserted_count']} ajout(s), "
            f"{summary['duplicate_count']} déjà connue(s), "
            f"{summary.get('incomplete_description_count', 0)} incomplète(s) · "
            f"seuil {summary.get('match_threshold', selected_threshold)} %."
        )

###################################################################################################################################################
# Bloc d'affichage des détails d'une annonce dans le cockpit Rocky.
###################################################################################################################################################

def render_job_detail(
    row: Any,
    settings: Settings,
    repository: RockyRepository,
    profile: CandidateProfile | None,
    key: str,
) -> None:

    """Affiche les détails d’une annonce dans le cockpit, avec les actions disponibles pour l’utilisateur."""
    job_id = int(row["id"])
    full = bool(row.get("description_is_full"))
    status = str(row.get("status") or "NOUVELLE")
    metadata = st.columns(4)
    metadata[0].write(f"**Lieu**  \n{row.get('city') or 'Non précisé'}")
    metadata[1].write(
        f"**Télétravail**  \n{row.get('remote_policy') or 'Non précisé'}"
    )
    metadata[2].write(f"**Salaire**  \n{display_salary(row)}")
    metadata[3].write(
        f"**Publication**  \n{display_date(row.get('publication_date'))}"
    )
    if full:
        st.success("Description complète — matching disponible")
    else:
        st.warning("Description incomplète — matching suspendu")
    st.write(
        plain_description(row.get("responsibilities"))
        or str(row.get("short_description") or "Aucun aperçu disponible.")
    )
    enrichment_source = str(row.get("description_enrichment_source") or "")
    if enrichment_source:
        st.caption(
            f"Description enrichie via {enrichment_source}. "
            f"Collecte d’origine : {row.get('source_name') or 'inconnue'}."
        )

    actions = st.columns([1.4, 1, 1.4])
    status_index = (
        list(JOB_STATUS_OPTIONS).index(status)
        if status in JOB_STATUS_OPTIONS
        else 0
    )
    next_status = actions[0].selectbox(
        "Statut",
        JOB_STATUS_OPTIONS,
        index=status_index,
        key=f"status_{key}_{job_id}",
    )
    if actions[1].button(
        "Enregistrer",
        key=f"save_status_{key}_{job_id}",
        use_container_width=True,
    ):
        repository.update_job_status(job_id, next_status)
        st.rerun()
    source_url = str(row.get("source_url") or "")
    if source_url:
        actions[2].link_button(
            "Voir l’annonce originale",
            source_url,
            use_container_width=True,
        )
    if not full and st.button(
        "Retenter l’enrichissement",
        key=f"reenrich_{key}_{job_id}",
    ):
        with st.spinner("Source d’origine, puis TheirStack si nécessaire…"):
            hydration = reenrich_saved_job(
                job_id,
                settings,
                repository,
                profile,
            )
        if hydration.is_complete:
            st.success(f"Description récupérée via {hydration.method}.")
            st.rerun()
        st.error(hydration.warning or "Description toujours indisponible.")


def metric_counts(jobs: pd.DataFrame, recent_days: int = 1) -> dict[str, int]:
    """ Extrait les métadonnées de temps des annonces et retourne un dictionnaire de comptage. """
    if jobs.empty:
        return {"total": 0, "complete": 0, "incomplete": 0, "recent": 0}
    dates = pd.to_datetime(jobs["publication_date"], errors="coerce")
    boundary = pd.Timestamp(
        (date.today() - timedelta(days=max(1, int(recent_days)))).isoformat()
    )
    return {
        "total": len(jobs),
        "complete": int(jobs["description_is_full"].fillna(False).sum()),
        "incomplete": len(jobs_to_enrich(jobs)),
        "recent": int((dates >= boundary).sum()),
    }


###################################################################################################################################################
# Bloc d'orchestration du popover de chat avec Rocky. 
###################################################################################################################################################

def render_floating_chatbot() -> None:
    """Expose le chat V1.1 dans un popover persistant de Rocky V2."""
    st.markdown(
        """
        <style>
        div[data-testid="stElementContainer"]:has(#rocky-chat-anchor)
          + div[data-testid="stElementContainer"] {
            position: fixed;
            right: 1.5rem;
            bottom: 1.5rem;
            z-index: 1000;
            width: auto;
        }
        div[data-testid="stPopoverBody"] {
            min-width: min(420px, 88vw);
        }
        </style>
        <span id="rocky-chat-anchor"></span>
        """,
        unsafe_allow_html=True,
    )
    with st.popover(
        "Discuter avec Rocky",
        icon="🐾",
        type="primary",
        key="rocky_v2_chat_popover",
    ):
        try:
            settings, repository, profile, jobs = load_data()
        except Exception:
            st.error("Le chat ne peut pas accéder aux données Rocky.")
            return
        llm = RockyLLM(settings)
        st.caption(f"Assistant Rocky · {settings.mistral_model}")
        if profile is None:
            st.info("Crée ou active un profil pour discuter avec Rocky.")
            return
        if not llm.is_configured:
            st.warning("Ajoute MISTRAL_API_KEY dans .env puis redémarre Rocky.")
            return

        job_options = {0: "Sans annonce particulière"}
        job_options.update(
            {
                int(row["id"]): f"{row['company_name']} — {row['job_title']}"
                for _, row in jobs.head(100).iterrows()
            }
        )
        selected_job_id = st.selectbox(
            "Contexte",
            list(job_options),
            format_func=lambda value: job_options[value],
            key="rocky_v2_chat_job",
        )
        messages = st.session_state.setdefault("rocky_v2_messages", [])
        with st.container(height=300, border=True):
            if not messages:
                st.caption("Pose une question sur ton profil ou une annonce.")
            for message in messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])

        with st.form("rocky_v2_chat_form", clear_on_submit=True):
            prompt = st.text_input(
                "Message",
                placeholder="Que penses-tu de cette opportunité ?",
                label_visibility="collapsed",
            )
            send = st.form_submit_button(
                "Envoyer", type="primary", use_container_width=True
            )
        if send and prompt.strip():
            messages.append({"role": "user", "content": prompt.strip()})
            selected_offer = None
            selected_match = None
            if selected_job_id:
                selected_offer = repository.fetch_job_offer(
                    int(selected_job_id)
                )
                if selected_offer and selected_offer.description_is_full:
                    selected_match = calculate_match(
                        selected_offer,
                        profile,
                        repository.fetch_skills(profile.id),
                    )
            try:
                answer = llm.chat(
                    prompt.strip(), profile, selected_offer, selected_match
                )
            except RockyError as error:
                answer = str(error)
            messages.append({"role": "assistant", "content": answer})
            st.rerun()
