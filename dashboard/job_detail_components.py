##############################################################################################################
# Module de fonctions pour la modification d'une annonce, recalcul du matching
# Intègre les blocs d'affichage des rapports de compatibilité ATS et d'affichage des résultats.
#############################################################################################################

"""Composants de la fiche détaillée d'une annonce Rocky.

Les fonctions regroupent l'édition contrôlée de l'offre, l'explication du
matching, l'atelier CV/lettre et la restitution ATS. Elles orchestrent les
services métier sans décider seules d'un statut ou d'une soumission.
"""

# Importation des librairies standard
from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import pymupdf
import streamlit as st

# Importation des modules internes
from dashboard.dashboard_common import matching_category_summary
from dashboard.job_analysis import SOFT_SKILLS, TECHNICAL_SKILLS
from dashboard.rocky.applications import generate_application
from dashboard.rocky.ats import (
    AtsReport,
    AtsV2Report,
    load_ats_cv_text,
)
from dashboard.rocky.config import Settings
from dashboard.rocky.contracts import CONTRACT_TYPES, WORK_SCHEDULES
from dashboard.rocky.cv_tailoring import (
    TECHNICAL_GROUPS,
    build_tailored_cv_plan,
    build_tailored_cv_plan_from_selection,
    create_tailored_cv,
)
from dashboard.rocky.errors import DocumentError, RockyError
from dashboard.rocky.job_importer import (
    description_is_probably_truncated,
    hydrate_job_offer,
)
from dashboard.rocky.letters import (
    LetterVariables,
    render_letter,
    render_letter_from_body,
    render_letter_preview_html,
)
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.matching import calculate_match
from dashboard.rocky.models import (
    CandidateProfile,
    JobOffer,
    MatchResult,
    ProfileProject,
    TailoredCvPlan,
)
from dashboard.rocky.projects import load_profile_projects
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.text_utils import ensure_list, normalize_text

#################################################################################################
# Bloc de fonctions utilitaires pour l'affichage des composants de la fiche annonce complète de Rocky.
#################################################################################################


def _letter_editor_height(_text: str) -> int:
    """Conserve un éditeur de lettre compact, avec défilement si nécessaire."""
    return 460


def _reset_ats_editor(editor_key: str, cv_path: str) -> None:
    """Réinitialise le brouillon ATS lorsque le CV ou l'annonce de référence change."""
    text, _ = load_ats_cv_text(cv_path)
    st.session_state[editor_key] = text


def _optional_date(value: Any) -> date | None:
    """Convertit une date d'interface facultative avant persistance de l'annonce."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        if pd.isna(value):
            return None
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _badges(skills: list[str], kind: str) -> None:
    """Fonction de paramétrage des badges de compétences dans les catégories de matching."""
    palettes = {
        "matched": ("#dcfce7", "#166534", "#86efac"),
        "missing": ("#fff7ed", "#9a3412", "#fdba74"),
        "profile": ("#eff6ff", "#1e40af", "#93c5fd"),
        "offer": ("#f3f4f6", "#374151", "#d1d5db"),
    }
    if not skills:
        st.caption("Aucune compétence dans cette catégorie.")
        return
    background, color, border = palettes[kind]
    badges = " ".join(
        (
            '<span style="display:inline-block; padding:0.25rem 0.55rem; '
            f"margin:0.15rem; border-radius:999px; background:{background}; "
            f'color:{color}; border:1px solid {border}; font-size:0.85rem;">'
            f"{escape(skill)}</span>"
        )
        for skill in skills
    )
    st.markdown(f"<div>{badges}</div>", unsafe_allow_html=True)


def _profile_skill_category(skill: str) -> str:
    """Retourne la catégorie de profil correspondant à la taxonomie Rocky."""
    normalized_skill = normalize_text(skill)
    if normalized_skill in {
        normalize_text(candidate) for candidate in TECHNICAL_SKILLS
    }:
        return "technical"
    if normalized_skill in {normalize_text(candidate) for candidate in SOFT_SKILLS}:
        return "soft"
    return "business"


#################################################################################################
# Bloc de modification des informations de l'annonce.
#################################################################################################


def render_edit_form(
    job_id: int,
    offer: JobOffer,
    repository: RockyRepository,
    profile: CandidateProfile | None,
    expander_label: str | None = "Modifier les informations de l’annonce",
) -> None:
    """Fonction de modification des informations de l'annonce. ( !  Modifie la base de donnée)"""
    edit_container = (
        st.expander(expander_label) if expander_label is not None else st.container()
    )
    with edit_container:
        st.caption(
            "L’identifiant Rocky et l’identifiant externe restent inchangés afin "
            "de préserver la provenance et l’historique."
        )
        with st.form(f"v2_edit_job_{job_id}"):
            identity = st.columns(2)
            title = identity[0].text_input("Poste *", offer.job_title)
            company = identity[1].text_input("Entreprise *", offer.company_name)

            location = st.columns(2)
            city = location[0].text_input("Ville", offer.city)
            country = location[1].text_input("Pays", offer.country)

            work = st.columns(2)
            contract_options = ["Non précisé", *CONTRACT_TYPES]
            contract = work[0].selectbox(
                "Contrat",
                contract_options,
                index=(
                    contract_options.index(offer.contract_type)
                    if offer.contract_type in contract_options
                    else 0
                ),
            )
            schedule_options = ["Non précisé", *WORK_SCHEDULES]
            schedule = work[1].selectbox(
                "Temps de travail",
                schedule_options,
                index=(
                    schedule_options.index(offer.work_schedule)
                    if offer.work_schedule in schedule_options
                    else 0
                ),
            )

            context = st.columns(3)
            remote = context[0].text_input("Télétravail", offer.remote_policy)
            domain = context[1].text_input("Domaine", offer.main_domain)
            experience = context[2].text_input(
                "Niveau d’expérience", offer.experience_level
            )

            salary = st.columns(3)
            salary_min = salary[0].number_input(
                "Salaire minimum",
                min_value=0.0,
                value=float(offer.salary_min or 0),
                step=1_000.0,
            )
            salary_max = salary[1].number_input(
                "Salaire maximum",
                min_value=0.0,
                value=float(offer.salary_max or 0),
                step=1_000.0,
            )
            currency = salary[2].text_input("Devise", offer.salary_currency or "EUR")

            dates = st.columns(2)
            publication_date = dates[0].date_input(
                "Date de publication",
                value=_optional_date(offer.publication_date),
                format="DD/MM/YYYY",
            )
            deadline = dates[1].date_input(
                "Date limite de candidature",
                value=_optional_date(offer.application_deadline),
                format="DD/MM/YYYY",
            )

            education = st.text_input("Formation demandée", offer.required_education)
            minimum_experience = st.number_input(
                "Expérience minimum en années",
                min_value=0.0,
                value=float(offer.minimum_experience_years or 0),
                step=0.5,
            )
            skills = st.text_input(
                "Compétences relevées — séparées par des virgules",
                ", ".join(offer.detected_skills),
            )

            source = st.columns(2)
            source[0].text_input(
                "Source de collecte",
                offer.source_name,
                disabled=True,
                help="La provenance originale n’est pas modifiable.",
            )
            source[1].text_input(
                "URL de l’annonce source",
                offer.source_url,
                disabled=True,
                help="L’URL source originale est conservée pour la déduplication.",
            )
            application_url = st.text_input("URL de candidature", offer.application_url)
            short_description = st.text_area(
                "Résumé", offer.short_description, height=100
            )
            responsibilities = st.text_area(
                "Description complète *", offer.responsibilities, height=360
            )
            save = st.form_submit_button(
                "Enregistrer les modifications",
                type="primary",
                use_container_width=True,
            )

        if not save:
            return
        if not title.strip() or not company.strip():
            st.error("Le poste et l’entreprise sont obligatoires.")
            return
        if not responsibilities.strip():
            st.error("La description est obligatoire.")
            return
        if description_is_probably_truncated(responsibilities):
            st.error(
                "La description semble encore tronquée. Colle la suite de "
                "l’annonce avant de l’enregistrer."
            )
            return

        updated = replace(
            offer,
            job_title=title.strip(),
            company_name=company.strip(),
            city=city.strip(),
            country=country.strip(),
            remote_policy=remote.strip(),
            contract_type="" if contract == "Non précisé" else contract,
            work_schedule="" if schedule == "Non précisé" else schedule,
            experience_level=experience.strip(),
            salary_min=salary_min or None,
            salary_max=salary_max or None,
            salary_currency=currency.strip() or "EUR",
            short_description=short_description.strip(),
            description_is_full=True,
            description_enrichment_source=(
                offer.description_enrichment_source
                if offer.description_is_full
                else "Saisie manuelle"
            ),
            description_enrichment_external_id=(
                offer.description_enrichment_external_id
                if offer.description_is_full
                else ""
            ),
            responsibilities=responsibilities.strip(),
            required_education=education.strip(),
            minimum_experience_years=minimum_experience or None,
            main_domain=domain.strip(),
            publication_date=publication_date,
            application_deadline=deadline,
            source_name=offer.source_name,
            source_url=offer.source_url,
            application_url=application_url.strip(),
            detected_skills=ensure_list(skills),
            status="NOUVELLE" if offer.status == "INCOMPLÈTE" else offer.status,
        )
        repository.update_job(job_id, updated)
        if updated.status != offer.status:
            repository.update_job_status(job_id, updated.status)
        if profile:
            localized = repository.profile_for_offer(profile.id, updated) or profile
            result = calculate_match(
                updated, localized, repository.fetch_skills(profile.id)
            )
            repository.save_match(job_id, profile.id, result)
        st.success("Annonce mise à jour et matching recalculé.")
        st.rerun()


#################################################################################################
# Bloc de recalcul du matching.
##################################################################################################


def _render_category(label: str, category: dict[str, Any], icon: str) -> None:
    """Fonction d'affichage des catégories de matching avec le score et les badges de compétences."""
    score = category["score"]
    st.markdown(f"#### {icon} {label}")
    metric = f"{score:.0f} %" if score is not None else "Non calculé"
    st.metric("Couverture", metric)
    st.markdown("**Correspondances reconnues**")
    _badges(category["matched"], "matched")
    st.markdown("**Demandées et absentes du profil**")
    _badges(category["missing"], "missing")


def render_matching_detail(
    row: Any,
    offer: JobOffer,
    repository: RockyRepository,
    profile: CandidateProfile | None,
) -> None:
    """Orchestre le recalcul du matching et affiche les résultats.

    Rend les catégories et le détail auditable du score Rocky.
    """
    job_id = int(row["id"])
    st.subheader("Analyse du matching")
    if profile is None:
        st.warning("Active un profil pour calculer le matching.")
        return
    added_skill_key = f"v2_profile_skill_added_{job_id}"
    added_skill = st.session_state.pop(added_skill_key, None)
    if added_skill:
        st.success(
            f"« {added_skill} » a été ajoutée au profil et le matching a été recalculé."
        )
    if st.button(
        "Recalculer le matching",
        key=f"v2_recalculate_{job_id}",
        disabled=not offer.description_is_full,
        help=(
            "Réenrichis d’abord la description."
            if not offer.description_is_full
            else None
        ),
    ):
        with st.spinner("Relecture de l’annonce et comparaison au profil…"):
            hydration = hydrate_job_offer(offer)
            if not hydration.is_complete:
                st.error(hydration.warning or "Description complète indisponible.")
                return
            recalculated = calculate_match(
                hydration.offer, profile, repository.fetch_skills(profile.id)
            )
            repository.update_job(job_id, hydration.offer)
            repository.save_match(job_id, profile.id, recalculated)
        st.success(f"Score recalculé : {recalculated.score:.1f} %.")
        st.rerun()

    summary = matching_category_summary(row)
    if summary is None:
        st.info("Aucun score enregistré. Lance le calcul pour analyser l’annonce.")
        return
    top = st.columns(4)
    top[0].metric("Score global", f"{summary['score']:.1f} %")
    technical_score = summary["technical"]["score"]
    transversal_score = summary["transversal"]["score"]
    top[1].metric(
        "Techniques",
        f"{technical_score:.0f} %" if technical_score is not None else "—",
    )
    top[2].metric(
        "Transversales",
        f"{transversal_score:.0f} %" if transversal_score is not None else "—",
    )
    top[3].metric("À vérifier", len(summary["to_review"]))

    categories = st.columns(2)
    with categories[0].container(border=True):
        _render_category("Compétences techniques", summary["technical"], "🧰")
    with categories[1].container(border=True):
        _render_category("Compétences transversales", summary["transversal"], "🤝")

    with st.container(border=True):
        st.markdown("#### 🔎 Compétences à vérifier")
        st.caption(
            "Elles sont demandées dans l’annonce mais non reconnues dans le "
            "profil. Ajoute uniquement celles que tu maîtrises : elles seront "
            "créées au niveau intermédiaire, sans ancienneté renseignée et non "
            "principales."
        )
        if not summary["to_review"]:
            st.success("Aucune compétence à vérifier.")
        existing_skills = {
            normalize_text(str(skill.get("skill_name") or ""))
            for skill in repository.fetch_skills(profile.id)
        }
        for item in summary["to_review"]:
            skill = str(item["skill"])
            skill_key = normalize_text(skill)
            details, action = st.columns([4, 1])
            if item["close_profile_skill"]:
                details.write(
                    f"**{skill}** — proche de « {item['close_profile_skill']} » "
                    f"({item['similarity']} %), à confirmer"
                )
            else:
                details.write(f"**{skill}** — non reconnue dans le profil")
            if skill_key in existing_skills:
                action.button(
                    "Déjà au profil",
                    key=f"v2_profile_skill_exists_{job_id}_{skill_key}",
                    disabled=True,
                    use_container_width=True,
                )
                continue
            if action.button(
                "Ajouter au profil",
                key=f"v2_add_profile_skill_{job_id}_{skill_key}",
                use_container_width=True,
                help=(
                    "Ajoute cette compétence comme "
                    f"{_profile_skill_category(skill)}, niveau intermédiaire, "
                    "sans ancienneté et non-principale."
                ),
            ):
                repository.add_skill(
                    profile.id,
                    skill,
                    _profile_skill_category(skill),
                    "intermédiaire",
                    None,
                    False,
                )
                rescored = calculate_match(
                    offer, profile, repository.fetch_skills(profile.id)
                )
                repository.save_match(job_id, profile.id, rescored)
                st.session_state[added_skill_key] = skill
                st.rerun()

    result: MatchResult = summary["result"]
    with st.expander("Voir la composition complète du score"):
        active_weight = sum(
            float(item.get("weight", 0))
            for item in result.breakdown.values()
            if isinstance(item, dict)
        )
        criteria = sorted(
            (item for item in result.breakdown.values() if isinstance(item, dict)),
            key=lambda item: float(item.get("weight", 0)),
            reverse=True,
        )
        columns = st.columns(2)
        for index, item in enumerate(criteria):
            raw_score = float(item.get("raw_score", 0))
            weight = float(item.get("weight", 0))
            contribution = raw_score * weight / active_weight if active_weight else 0
            with columns[index % 2].container(border=True):
                st.markdown(f"**{item.get('label', 'Critère')} — {raw_score:.1f} %**")
                st.progress(min(1.0, max(0.0, raw_score / 100)))
                st.caption(
                    f"{item.get('detail', '')} · contribution : "
                    f"{contribution:.1f} point(s)"
                )


#################################################################################################
# Bloc d'affichage des rapports de compatibilité ATS.
#################################################################################################


def render_ats_report(report: AtsReport) -> None:
    """Affiche le diagnostic ATS historique comme repère, sans modifier le matching."""
    with st.expander(
        f"Rapport ATS V1 · {report.score} / 100",
        expanded=False,
    ):
        st.markdown("#### Rapport court de compatibilité ATS")
        metrics = st.columns(4)
        metrics[0].metric("Score indicatif", f"{report.score} / 100")
        metrics[1].metric("CV", f"{report.cv_score} / 100")
        metrics[2].metric("Lettre", f"{report.letter_score} / 100")
        metrics[3].metric(
            "Mots-clés du CV",
            (
                f"{report.keyword_coverage} %"
                if report.keyword_coverage is not None
                else "Non mesuré"
            ),
        )
        st.progress(report.score / 100, text=report.rating)
        st.caption(
            f"Lecture PDF : {report.readability_score} % · "
            f"{report.cv_pages} page(s) · {report.cv_characters} caractères "
            f"extraits · lettre : {report.letter_words} mots"
        )

        keywords = st.columns(2)
        with keywords[0]:
            st.markdown("**Compétences retrouvées dans le CV**")
            if report.matched_keywords:
                st.write(", ".join(report.matched_keywords))
            else:
                st.caption("Aucune compétence reconnue automatiquement.")
        with keywords[1]:
            st.markdown("**Compétences à vérifier ou à expliciter**")
            if report.missing_keywords:
                st.write(", ".join(report.missing_keywords[:8]))
            else:
                st.caption("Aucun manque détecté sur les mots-clés reconnus.")

        findings = st.columns(2)
        with findings[0]:
            st.markdown("**Points favorables**")
            if report.strengths:
                for strength in report.strengths:
                    st.success(strength)
            else:
                st.caption("Aucun point favorable spécifique détecté.")
        with findings[1]:
            st.markdown("**Points à contrôler**")
            for alert in report.alerts:
                st.warning(alert)
        st.caption(
            "Simulation heuristique locale : ce résultat aide à relire les "
            "documents mais ne garantit ni le parsing ni la sélection par un ATS réel."
        )


def render_ats_v2_report(report: AtsV2Report) -> None:
    """Présente le rapport ATS V2 explicable dans le flux de préparation du dossier."""
    with st.expander(
        f"Rapport ATS V2 · {report.score} / 100",
        expanded=False,
    ):
        st.markdown("#### Rapport ATS V2 — lecture tolérante")
        metrics = st.columns(5)
        metrics[0].metric("Score V2", f"{report.score} / 100")
        metrics[1].metric("CV", f"{report.cv_score} / 100")
        metrics[2].metric("Lettre", f"{report.letter_score} / 100")
        metrics[3].metric(
            "Mots-clés exacts",
            (
                f"{report.exact_keyword_coverage} %"
                if report.exact_keyword_coverage is not None
                else "Non mesuré"
            ),
        )
        metrics[4].metric(
            "Couverture ajustée",
            (
                f"{report.adjusted_keyword_coverage} %"
                if report.adjusted_keyword_coverage is not None
                else "Non mesurée"
            ),
            help="Inclut un crédit partiel pour les compétences proches.",
        )
        st.progress(report.score / 100, text=report.rating)
        st.caption(
            f"Source analysée : {report.text_source} · risque de parsing : "
            f"{report.parsing_score} / 100 · {report.cv_pages} page(s) · "
            f"{report.cv_characters} caractères · lettre : {report.letter_words} mots"
        )

        matches = st.columns(3)
        with matches[0]:
            st.markdown("**Correspondances exactes**")
            st.write(", ".join(report.exact_keywords) or "Aucune")
        with matches[1]:
            st.markdown("**Compétences proches**")
            if report.related_keywords:
                for match in report.related_keywords:
                    st.write(
                        f"- **{match.required_skill}** ↔ {match.cv_evidence} "
                        f"({match.confidence} % de proximité)"
                    )
            else:
                st.caption("Aucun rapprochement partiel.")
        with matches[2]:
            st.markdown("**Sans preuve suffisante**")
            st.write(", ".join(report.missing_keywords) or "Aucune")

        findings = st.columns(2)
        with findings[0]:
            st.markdown("**Points favorables**")
            for strength in report.strengths:
                st.success(strength)
        with findings[1]:
            st.markdown("**Points à contrôler**")
            for alert in report.alerts:
                st.warning(alert)
        st.caption(
            "La couverture ajustée distingue toujours les preuves exactes des "
            "compétences seulement proches. Elle ne transforme pas un synonyme "
            "ou un outil voisin en maîtrise certaine."
        )


def _cv_source_path(settings: Settings, profile: CandidateProfile) -> Path:
    """Résout le chemin du CV canonique sans modifier le profil."""
    path = Path(profile.cv_path or "").expanduser()
    return path if path.is_absolute() else settings.project_dir / path


def _profile_skill_badge_groups(
    skills: list[dict[str, object]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Classe toutes les compétences du profil dans les badges du CV.

    Chaque compétence n'apparaît qu'une fois. Les compétences métier et soft
    sont affichées dans le groupe transversal, tandis que les autres restent
    dans un groupe technique, y compris lorsqu'elles ne correspondent pas à la
    taxonomie prédéfinie.
    """
    technical: list[str] = []
    transversal: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        name = str(skill.get("skill_name") or "").strip()
        normalized = normalize_text(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        category = str(skill.get("skill_category") or "").lower()
        (transversal if category in {"soft", "business"} else technical).append(name)

    groups: list[tuple[str, tuple[str, ...]]] = []
    assigned: set[str] = set()
    for label, markers in TECHNICAL_GROUPS:
        values = tuple(
            name
            for name in technical
            if (
                normalize_text(name) not in assigned
                and any(marker in normalize_text(name) for marker in markers)
            )
        )
        if values:
            groups.append((label, values))
            assigned.update(normalize_text(name) for name in values)
    remaining = tuple(
        name for name in technical if normalize_text(name) not in assigned
    )
    if remaining:
        groups.append(("Outils et méthodes", remaining))
    if transversal:
        groups.append(("Compétences transversales", tuple(transversal)))
    return tuple(groups)


def _limit_badge_selection(widget_key: str, maximum: int) -> None:
    """Conserve les premiers badges lorsqu'un clic dépasse la limite affichée."""
    selection = st.session_state.get(widget_key, [])
    if isinstance(selection, list) and len(selection) > maximum:
        st.session_state[widget_key] = selection[:maximum]


def _render_cv_review(
    job_id: int,
    offer: JobOffer,
    settings: Settings,
    repository: RockyRepository,
    profile: CandidateProfile,
    projects: list[ProfileProject],
) -> tuple[TailoredCvPlan | None, bool]:
    """Affiche l'éditeur borné du CV et un aperçu PDF avant génération.

    Les seuls champs exposés correspondent aux rectangles déjà autorisés par le
    modèle Canva : deux blocs de compétences et trois projets maximum. Le PDF
    de prévisualisation est temporaire et n'est jamais enregistré comme version
    de candidature avant la validation explicite de l'utilisateur.
    """
    st.markdown("#### CV ciblé · vérification avant génération")
    if profile.locale == "en":
        # Le CV anglais est déjà un document Rocky structuré ou un import manuel.
        # Il ne faut pas lui appliquer les zones fixes du gabarit français.
        st.caption(
            "Pour une annonce anglaise, Rocky utilise la version EN validée sans "
            "réécrire sa mise en page ni remplacer un import manuel."
        )
        source = _cv_source_path(settings, profile)
        if source.is_file():
            st.pdf(source.read_bytes(), height=680)
        else:
            st.warning("Le CV anglais validé est introuvable.")
        cv_confirm = st.checkbox(
            "I reviewed and approve this English CV",
            key=f"v2_confirm_cv_{job_id}",
        )
        return None, cv_confirm
    st.caption(
        "Rocky pré-sélectionne les éléments les plus pertinents du profil. "
        "Clique sur un badge pour l'ajouter ou le retirer du CV ciblé."
    )
    try:
        profile_skills = repository.fetch_skills(profile.id)
        initial_plan = build_tailored_cv_plan(
            offer,
            profile_skills,
            projects,
        )
    except DocumentError as error:
        st.error(str(error))
        return None, False
    with st.container(border=True):
        st.markdown("##### Compétences du profil")
        st.info(
            "Clique sur les badges colorés pour les retirer ou sur les badges gris "
            "pour les ajouter. Tu peux sélectionner au maximum 6 compétences par "
            "type et 3 projets."
        )
        recommended_technical = {
            normalize_text(value)
            for _, values in initial_plan.technical_groups
            for value in values
        }
        recommended_transversal = {
            normalize_text(value) for value in initial_plan.transversal_skills
        }
        selected_groups: list[tuple[str, tuple[str, ...]]] = []
        selected_transversal: tuple[str, ...] = ()
        for index, (label, options) in enumerate(
            _profile_skill_badge_groups(profile_skills)
        ):
            widget_key = f"v2_cv_badges_{job_id}_{profile.id}_{index}"
            is_transversal = label == "Compétences transversales"
            recommended = (
                recommended_transversal if is_transversal else recommended_technical
            )
            defaults = [
                option for option in options if normalize_text(option) in recommended
            ][:6]
            selected_count = (
                len(defaults)
                if widget_key not in st.session_state
                else len(st.session_state[widget_key])
            )
            selected = st.pills(
                f"{label} · {selected_count}/6",
                options,
                selection_mode="multi",
                default=defaults,
                key=widget_key,
                on_change=_limit_badge_selection,
                args=(widget_key, 6),
                help="Les badges colorés seront ajoutés au CV ; les badges gris n'y figureront pas.",
            )
            selected_values = tuple(selected or ())[:6]
            if is_transversal:
                selected_transversal = selected_values
            else:
                selected_groups.append((label, selected_values))

        st.markdown("##### Projets du profil")
        active_projects = [project for project in projects if project.is_active]
        projects_by_slug = {project.slug: project for project in active_projects}
        project_widget_key = f"v2_cv_projects_{job_id}_{profile.id}"
        selected_project_count = (
            len(initial_plan.projects)
            if project_widget_key not in st.session_state
            else len(st.session_state[project_widget_key])
        )
        selected_project_slugs = st.pills(
            f"Projets retenus · {selected_project_count}/3",
            options=list(projects_by_slug),
            selection_mode="multi",
            default=[project.slug for project in initial_plan.projects],
            format_func=lambda slug: projects_by_slug[str(slug)].name,
            key=project_widget_key,
            on_change=_limit_badge_selection,
            args=(project_widget_key, 3),
            help="Les trois projets colorés au plus seront intégrés au CV ciblé.",
        )
        selected_projects = [
            projects_by_slug[slug]
            for slug in (selected_project_slugs or [])[:3]
            if slug in projects_by_slug
        ]

    plan = build_tailored_cv_plan_from_selection(
        selected_groups,
        selected_transversal,
        selected_projects,
    )
    # L'aperçu et l'enregistrement emploient la sélection visible ; le snapshot
    # enregistré plus bas continue de protéger le PDF final d'un changement futur.
    st.session_state[f"v2_cv_plan_{job_id}"] = plan

    preview_col, check_col = st.columns([1.25, 1])
    with preview_col:
        st.markdown("##### Aperçu du CV ciblé")
        source = _cv_source_path(settings, profile)
        if source.is_file() and plan.technical_groups and plan.projects:
            try:
                with tempfile.TemporaryDirectory(prefix="rocky_cv_preview_") as folder:
                    preview_path = Path(folder) / "cv_preview.pdf"
                    create_tailored_cv(source, preview_path, plan, settings)
                    with pymupdf.open(preview_path) as document:
                        pixmap = document[0].get_pixmap(
                            matrix=pymupdf.Matrix(1.25, 1.25), alpha=False
                        )
                        st.image(pixmap.tobytes("png"), width="stretch")
            except (DocumentError, OSError) as error:
                st.error(f"Aperçu CV indisponible : {error}")
        else:
            st.warning(
                "Ajoute un CV source et au moins un projet pour afficher l'aperçu."
            )
    with check_col:
        st.markdown("##### Contrôle")
        st.info(
            "Seules les compétences techniques, transversales et les trois "
            "cartes projets seront remplacées. Le profil, les expériences et "
            "la mise en page restent verrouillés."
        )
        cv_confirm = st.checkbox(
            "J’ai relu le CV ciblé et je valide son contenu",
            key=f"v2_confirm_cv_{job_id}",
        )
    return plan, cv_confirm


def render_letter_workshop(
    job_id: int,
    offer: JobOffer,
    settings: Settings,
    repository: RockyRepository,
    profile: CandidateProfile | None,
    active_section: str = "all",
) -> None:
    """Affiche l'atelier CV, lettre et PDF sans changer le flux métier.

    ``active_section`` permet à la page dédiée d'afficher un seul jalon à la
    fois. La fiche annonce conserve ``all`` : les clés de session, validations
    et appels de génération restent les mêmes dans les deux parcours. Cette
    fonction ne constitue pas un fragment Streamlit : les sauvegardes doivent
    recharger la page entière pour mettre à jour les badges et la zone
    « Postuler ! » située après l'atelier.
    """
    if profile is None:
        st.warning("Active un profil avant de préparer une candidature.")
        return
    llm = RockyLLM(settings)
    if not profile.cv_path:
        st.warning("Ajoute un CV au profil avant de créer le dossier final.")
    profile_documents = {
        document.kind: document
        for document in repository.fetch_profile_documents(profile.id, profile.locale)
    }
    if profile.locale == "en" and profile_documents.get("cv"):
        # Les anciens écrans peuvent arriver ici avec le chemin CV français
        # stocké dans le profil partagé. L'atelier doit néanmoins travailler sur
        # le PDF anglais importé dès que l'annonce a sélectionné cette locale.
        profile = replace(profile, cv_path=profile_documents["cv"].source_path)
    english_kit_ready = profile.locale != "en" or (
        {"cv", "letter"} <= set(profile_documents)
        and all(document.status == "ready" for document in profile_documents.values())
    )
    if not english_kit_ready:
        st.warning(
            "Cette annonce utilise la version anglaise. Importe le CV PDF et la "
            "lettre DOCX anglais dans Profil & CV avant de préparer le dossier."
        )
    try:
        profile_projects = load_profile_projects(
            profile.id, settings, repository, profile.locale
        )
    except RockyError as error:
        profile_projects = []
        st.warning(
            "Les projets validés ne sont pas encore utilisables pour cette "
            f"candidature : {error}"
        )
    show_cv = active_section in {"all", "cv"}
    show_letter = active_section in {"all", "letter"}
    # ``postulate`` est le nom de la troisième carte du parcours dédié. Le
    # mode ``all`` de la fiche annonce conserve l'atelier complet.
    show_postulate = active_section in {"all", "postulate", "final"}
    plan_key = f"v2_cv_plan_{job_id}"
    cv_saved_key = f"v2_prepare_cv_saved_{job_id}"
    saved_cv_plan_key = f"v2_prepare_saved_cv_plan_{job_id}"
    letter_saved_key = f"v2_prepare_letter_saved_{job_id}"
    saved_letter_key = f"v2_prepare_saved_letter_text_{job_id}"
    cv_plan = st.session_state.get(plan_key)
    cv_confirm = bool(st.session_state.get(f"v2_confirm_cv_{job_id}"))

    if show_cv:
        with st.container(border=True):
            st.markdown("#### 01 · Ton CV ciblé")
            st.caption(
                "Choisis les éléments que Rocky peut modifier, puis relis l’aperçu avant génération."
            )
            cv_plan, cv_confirm = _render_cv_review(
                job_id,
                offer,
                settings,
                repository,
                profile,
                profile_projects,
            )
        # La génération ne relit jamais le brouillon courant : elle utilisera
        # la copie explicite ci-dessous. Ainsi une retouche ultérieure ne peut
        # pas modifier silencieusement le dossier qui sera généré.
        can_save_cv = bool(
            cv_confirm
            and (
                (profile.locale == "en" and english_kit_ready)
                or (cv_plan and cv_plan.technical_groups and cv_plan.projects)
            )
            and profile.cv_path
        )
        if st.button(
            "✅ Enregistrer ce CV ciblé",
            key=f"v2_prepare_save_cv_{job_id}",
            type="primary",
            disabled=not can_save_cv,
            use_container_width=True,
        ):
            st.session_state[saved_cv_plan_key] = cv_plan
            st.session_state[cv_saved_key] = True
            # Ferme visuellement l'étape CV en basculant immédiatement sur la
            # carte suivante ; le rerun complet rend aussi son badge validé.
            st.session_state[f"v2_prepare_active_section_{job_id}"] = "letter"
            st.rerun()

    paragraph_key = f"v2_company_paragraph_{job_id}"
    if paragraph_key not in st.session_state:
        st.session_state[paragraph_key] = (
            f"Je suis particulièrement intéressé par cette opportunité chez "
            f"{offer.company_name}, dont les missions correspondent à mon projet "
            "d’utiliser la data comme outil d’aide à la décision."
        )
    message_key = f"v2_application_message_{job_id}"
    if message_key not in st.session_state:
        st.session_state[message_key] = (
            f"Bonjour, je vous adresse ma candidature au poste de "
            f"{offer.job_title or 'Data Scientist'} chez "
            f"{offer.company_name or 'votre entreprise'}. Mon parcours data et "
            "mon intérêt pour vos missions me donnent envie d'échanger avec vous."
        )

    company_paragraph = str(st.session_state[paragraph_key])
    recipient_key = f"v2_recipient_{job_id}"
    address_key = f"v2_address_{job_id}"
    recipient = str(
        st.session_state.get(
            recipient_key, "À l’attention du Service des Ressources Humaines"
        )
    )
    address = str(st.session_state.get(address_key, ""))

    if show_letter:
        # Le message est volontairement replié à l'ouverture : il est utile,
        # mais ne doit pas repousser la lettre complète hors de l'écran.
        with st.expander("02 · Ton message d’accompagnement", expanded=False):
            st.caption(
                "À coller dans le champ libre du site de candidature ; il n'est pas ajouté au PDF."
            )
            if st.button(
                "Rocky : générer le message",
                key=f"v2_llm_application_message_{job_id}",
                disabled=not llm.is_configured,
                use_container_width=True,
            ):
                try:
                    st.session_state[message_key] = (
                        llm.application_accompanying_message(
                            offer,
                            profile,
                            repository.fetch_skills(profile.id),
                            profile_projects,
                            profile.locale,
                        )
                    )
                    st.rerun()
                except RockyError as error:
                    st.error(str(error))
            st.text_area(
                "Message d’accompagnement à copier",
                key=message_key,
                height=145,
                help="Ce message reste éditable et n'est pas ajouté au PDF.",
            )

        with st.container(border=True):
            st.markdown("#### 03 · Ta lettre de motivation")
            st.caption(
                "Le paragraphe Rocky y est intégré ; adapte ensuite la lettre complète si tu le souhaites."
            )
            if st.button(
                "Rocky : générer le paragraphe pour la lettre",
                key=f"v2_llm_paragraph_{job_id}",
                disabled=not llm.is_configured,
                use_container_width=True,
            ):
                try:
                    st.session_state[paragraph_key] = llm.company_paragraph(
                        offer, profile.locale
                    )
                    st.rerun()
                except RockyError as error:
                    st.error(str(error))
            company_paragraph = st.text_area(
                "Paragraphe personnalisé pour la lettre",
                key=paragraph_key,
                height=130,
                help="Ce texte est intégré dans la lettre PDF.",
            )
            with st.expander("Personnaliser l’en-tête de la lettre", expanded=False):
                recipient = st.text_input(
                    "Destinataire",
                    recipient,
                    key=recipient_key,
                )
                address = st.text_input(
                    "Adresse de l’entreprise (facultatif)",
                    address,
                    key=address_key,
                )
        if not llm.is_configured:
            st.caption(
                "Mistral non configuré : les deux brouillons restent modifiables manuellement."
            )
    variables = LetterVariables(
        job_title=offer.job_title,
        company_name=offer.company_name,
        company_paragraph=company_paragraph,
        recipient=recipient,
        company_address=address,
        sender_name=profile.full_name or profile.profile_name,
        sender_address=" · ".join(
            value
            for value in (profile.address, profile.postal_code, profile.home_city)
            if value
        ),
        sender_phone=profile.phone,
        sender_email=profile.email,
        city=profile.home_city,
        locale=profile.locale,
    )
    letter_preview = str(st.session_state.get(f"v2_letter_editor_{job_id}") or "")
    try:
        generated = render_letter(settings, variables)
        editor_key = f"v2_letter_editor_{job_id}"
        base_key = f"v2_letter_base_{job_id}"
        previous_base = st.session_state.get(base_key)
        current_draft = st.session_state.get(editor_key)
        if current_draft is None or current_draft == previous_base:
            st.session_state[editor_key] = generated
        st.session_state[base_key] = generated

        if show_letter:
            with st.container(border=True):
                st.markdown("#### Relecture et mise en forme")
                actions, _ = st.columns([1.2, 2])
                with actions:
                    if st.button(
                        "Adapter toute la lettre avec Rocky",
                        key=f"v2_tailor_full_letter_{job_id}",
                        disabled=not llm.is_configured,
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            paragraphs = llm.tailored_letter_body(
                                offer,
                                profile,
                                repository.fetch_skills(profile.id),
                                profile_projects,
                                profile.locale,
                            )
                            tailored = render_letter_from_body(variables, paragraphs)
                            st.session_state[editor_key] = tailored
                            st.session_state[base_key] = tailored
                            st.rerun()
                        except RockyError as error:
                            st.error(str(error))
                    if st.button(
                        "Recharger depuis le modèle",
                        key=f"v2_reset_letter_{job_id}",
                        use_container_width=True,
                    ):
                        st.session_state[editor_key] = generated
                        st.rerun()
                edit_tab, preview_tab = st.tabs(["✍️ Édition", "👁 Aperçu mis en forme"])
                with edit_tab:
                    editor_height = _letter_editor_height(
                        str(st.session_state.get(editor_key) or generated)
                    )
                    letter_preview = st.text_area(
                        "Contenu de la lettre",
                        key=editor_key,
                        height=editor_height,
                        label_visibility="collapsed",
                    )
                with preview_tab:
                    st.caption("Aperçu complet de la lettre dans sa mise en forme PDF.")
                    with st.container(height=700, border=True):
                        st.markdown(
                            render_letter_preview_html(
                                variables,
                                str(st.session_state.get(editor_key) or generated),
                            ),
                            unsafe_allow_html=True,
                        )
        # Le bouton de génération reçoit le brouillon en session, y compris si
        # l'utilisateur ouvre directement la dernière carte de progression.
        letter_preview = str(st.session_state.get(editor_key) or generated)
    except RockyError as error:
        st.error(str(error))

    if show_letter:
        # La sauvegarde inclut le message d'accompagnement et la lettre. Le
        # premier reste à copier sur le portail, le second devient le PDF.
        letter_confirm = st.checkbox(
            "J’ai relu le message et la lettre, et je valide cette version",
            key=f"v2_confirm_letter_{job_id}",
        )
        if st.button(
            "✅ Enregistrer les messages et la lettre",
            key=f"v2_prepare_save_letter_{job_id}",
            type="primary",
            disabled=not bool(letter_confirm and letter_preview),
            use_container_width=True,
        ):
            st.session_state[saved_letter_key] = letter_preview
            st.session_state[letter_saved_key] = True
            # Même logique : le bloc s'efface au profit de Postuler, ce qui
            # évite de demander un second clic de navigation.
            st.session_state[f"v2_prepare_active_section_{job_id}"] = "postulate"
            st.rerun()

    if show_postulate:
        saved_cv_plan = st.session_state.get(saved_cv_plan_key)
        saved_letter = str(st.session_state.get(saved_letter_key) or "")
        cv_is_saved = bool(st.session_state.get(cv_saved_key))
        letter_is_saved = bool(st.session_state.get(letter_saved_key))
        can_generate = bool(
            cv_is_saved
            and letter_is_saved
            and (
                (profile.locale == "en" and english_kit_ready)
                or (
                    saved_cv_plan
                    and saved_cv_plan.technical_groups
                    and saved_cv_plan.projects
                )
            )
            and saved_letter
            and profile.cv_path
        )
        with st.container(border=True):
            st.markdown("#### 03 · Générer tes deux PDF")
            st.caption(
                "Rocky utilisera uniquement le CV et la lettre que tu as enregistrés dans les deux cartes précédentes."
            )
            if not cv_is_saved or not letter_is_saved:
                missing = []
                if not cv_is_saved:
                    missing.append("CV ciblé")
                if not letter_is_saved:
                    missing.append("messages et lettre")
                st.warning(
                    "À enregistrer avant la génération : " + " et ".join(missing) + "."
                )
            if st.button(
                "Créer le CV ciblé + la lettre PDF",
                key=f"v2_prepare_{job_id}",
                type="primary",
                disabled=not can_generate,
                use_container_width=True,
            ):
                try:
                    package = generate_application(
                        job_id,
                        profile,
                        offer,
                        saved_letter,
                        settings,
                        repository,
                        plan=saved_cv_plan,
                        rocky_paragraph=company_paragraph,
                    )
                    st.session_state[f"v2_files_{job_id}"] = package
                    # Le bouton fusée est rendu par la page parente, après cet
                    # atelier. Un rerun applicatif complet le rend visible dès
                    # la fin de la génération, sans attendre un téléchargement.
                    st.session_state[f"v2_prepare_active_section_{job_id}"] = (
                        "postulate"
                    )
                    st.rerun()
                except (RockyError, OSError) as error:
                    st.error(str(error))
    files = st.session_state.get(f"v2_files_{job_id}")
    if files and show_postulate:
        downloads = st.columns(2)
        for column, label, path in (
            (downloads[0], "CV ciblé", files.cv_pdf_path),
            (downloads[1], "Lettre PDF", files.letter_pdf_path),
        ):
            pdf_path = Path(path)
            column.download_button(
                f"Télécharger {label}",
                pdf_path.read_bytes(),
                file_name=pdf_path.name,
                key=f"v2_download_{job_id}_{label}",
                use_container_width=True,
            )
