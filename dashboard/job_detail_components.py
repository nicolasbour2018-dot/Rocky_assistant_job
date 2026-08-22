                    ##############################################################################################################
                        # Module de fonctions pour la modification d'une annonce, recalcul du matching 
                        # Intègre les blocs d'affichage des rapports de compatibilité ATS et d'affichage des résultats. 
                    #############################################################################################################

"""Composants de la fiche annonce complète de Rocky V2."""

# Importation des librairies standard
from __future__ import annotations

from dataclasses import replace
from datetime import date
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

# Importation des modules internes
from dashboard.dashboard_common import matching_category_summary
from dashboard.job_analysis import SOFT_SKILLS, TECHNICAL_SKILLS
from dashboard.rocky.ats import (
    AtsReport,
    AtsV2Report,
    analyze_application_ats,
    analyze_application_ats_v2,
    ats_text_path,
    load_ats_cv_text,
    save_ats_cv_text,
)
from dashboard.rocky.config import Settings
from dashboard.rocky.contracts import CONTRACT_TYPES, WORK_SCHEDULES
from dashboard.rocky.errors import RockyError
from dashboard.rocky.job_importer import (
    description_is_probably_truncated,
    hydrate_job_offer,
)
from dashboard.rocky.letters import (
    LetterVariables,
    prepare_application,
    render_letter,
    render_letter_preview_html,
)
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.matching import calculate_match
from dashboard.rocky.models import CandidateProfile, JobOffer, MatchResult
from dashboard.rocky.repository import RockyRepository
from dashboard.rocky.text_utils import ensure_list, normalize_text, project_relative

#################################################################################################
# Bloc de fonctions utilitaires pour l'affichage des composants de la fiche annonce complète de Rocky.
#################################################################################################

def _letter_editor_height(_text: str) -> int:
    """Conserve un éditeur de lettre compact, avec défilement si nécessaire."""
    return 460


def _reset_ats_editor(editor_key: str, cv_path: str) -> None:
    text, _ = load_ats_cv_text(cv_path)
    st.session_state[editor_key] = text


def _optional_date(value: Any) -> date | None:
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
    """ Fonction de paramétrage des badges de compétences dans les catégories de matching. """
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
            f'margin:0.15rem; border-radius:999px; background:{background}; '
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
    if normalized_skill in {
        normalize_text(candidate) for candidate in SOFT_SKILLS
    }:
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
    """ Fonction de modification des informations de l'annonce. ( !  Modifie la base de donnée) """
    edit_container = (
        st.expander(expander_label)
        if expander_label is not None
        else st.container()
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
            currency = salary[2].text_input(
                "Devise", offer.salary_currency or "EUR"
            )

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

            education = st.text_input(
                "Formation demandée", offer.required_education
            )
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
            application_url = st.text_input(
                "URL de candidature", offer.application_url
            )
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
            result = calculate_match(
                updated, profile, repository.fetch_skills(profile.id)
            )
            repository.save_match(job_id, profile.id, result)
        st.success("Annonce mise à jour et matching recalculé.")
        st.rerun()

#################################################################################################
# Bloc de recalcul du matching.
##################################################################################################

def _render_category(
    label: str, category: dict[str, Any], icon: str
) -> None:
    """ Fonction d'affichage des catégories de matching avec le score et les badges de compétences. """
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
    """ Orchestre le recalcul du matching (après modification) et affiche les résultats : catégories et détail auditable du score Rocky. """
    job_id = int(row["id"])
    st.subheader("Analyse du matching")
    if profile is None:
        st.warning("Active un profil pour calculer le matching.")
        return
    added_skill_key = f"v2_profile_skill_added_{job_id}"
    added_skill = st.session_state.pop(added_skill_key, None)
    if added_skill:
        st.success(
            f"« {added_skill} » a été ajoutée au profil et le matching "
            "a été recalculé."
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
            result = calculate_match(
                hydration.offer, profile, repository.fetch_skills(profile.id)
            )
            repository.update_job(job_id, hydration.offer)
            repository.save_match(job_id, profile.id, result)
        st.success(f"Score recalculé : {result.score:.1f} %.")
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
        _render_category(
            "Compétences transversales", summary["transversal"], "🤝"
        )

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
                result = calculate_match(
                    offer, profile, repository.fetch_skills(profile.id)
                )
                repository.save_match(job_id, profile.id, result)
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
            (
                item
                for item in result.breakdown.values()
                if isinstance(item, dict)
            ),
            key=lambda item: float(item.get("weight", 0)),
            reverse=True,
        )
        columns = st.columns(2)
        for index, item in enumerate(criteria):
            raw_score = float(item.get("raw_score", 0))
            weight = float(item.get("weight", 0))
            contribution = raw_score * weight / active_weight if active_weight else 0
            with columns[index % 2].container(border=True):
                st.markdown(
                    f"**{item.get('label', 'Critère')} — {raw_score:.1f} %**"
                )
                st.progress(min(1.0, max(0.0, raw_score / 100)))
                st.caption(
                    f"{item.get('detail', '')} · contribution : "
                    f"{contribution:.1f} point(s)"
                )

#################################################################################################
# Bloc d'affichage des rapports de compatibilité ATS.
#################################################################################################

def render_ats_report(report: AtsReport) -> None:
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


@st.fragment
def render_letter_workshop(
    job_id: int,
    offer: JobOffer,
    settings: Settings,
    repository: RockyRepository,
    profile: CandidateProfile | None,
) -> None:
    """Réutilise l’atelier V1.1 de lettre modifiable et de dossier final."""
    st.subheader("Lettre de motivation et candidature")
    if profile is None:
        st.warning("Active un profil avant de préparer une candidature.")
        return
    llm = RockyLLM(settings)
    if not profile.cv_path:
        st.warning("Ajoute un CV au profil avant de créer le dossier final.")

    paragraph_key = f"v2_company_paragraph_{job_id}"
    if paragraph_key not in st.session_state:
        st.session_state[paragraph_key] = (
            f"Je suis particulièrement intéressé par cette opportunité chez "
            f"{offer.company_name}, dont les missions correspondent à mon projet "
            "d’utiliser la data comme outil d’aide à la décision."
        )
    if st.button(
        "Proposer le paragraphe avec Rocky",
        key=f"v2_llm_paragraph_{job_id}",
        disabled=not llm.is_configured,
    ):
        try:
            st.session_state[paragraph_key] = llm.company_paragraph(offer)
        except RockyError as error:
            st.error(str(error))
    if not llm.is_configured:
        st.caption("Mistral non configuré : le brouillon reste modifiable manuellement.")

    recipient = st.text_input(
        "Destinataire",
        "À l’attention du Service des Ressources Humaines",
        key=f"v2_recipient_{job_id}",
    )
    address = st.text_input(
        "Adresse de l’entreprise (facultatif)",
        key=f"v2_address_{job_id}",
    )
    company_paragraph = st.text_area(
        "Paragraphe personnalisé",
        key=paragraph_key,
        height=110,
    )
    variables = LetterVariables(
        job_title=offer.job_title,
        company_name=offer.company_name,
        company_paragraph=company_paragraph,
        recipient=recipient,
        company_address=address,
    )
    letter_preview = ""
    try:
        generated = render_letter(settings, variables)
        editor_key = f"v2_letter_editor_{job_id}"
        base_key = f"v2_letter_base_{job_id}"
        previous_base = st.session_state.get(base_key)
        current_draft = st.session_state.get(editor_key)
        if current_draft is None or current_draft == previous_base:
            st.session_state[editor_key] = generated
        st.session_state[base_key] = generated

        st.markdown("#### Lettre modifiable")
        if st.button(
            "Recharger depuis le modèle", key=f"v2_reset_letter_{job_id}"
        ):
            st.session_state[editor_key] = generated
        editor_height = _letter_editor_height(
            str(st.session_state.get(editor_key) or generated)
        )
        letter_preview = st.text_area(
            "Contenu de la lettre",
            key=editor_key,
            height=editor_height,
            label_visibility="collapsed",
        )

        st.markdown("#### Aperçu mis en forme")
        st.caption("Aperçu complet dans une zone défilable.")
        with st.container(height=700, border=True):
            st.markdown(
                render_letter_preview_html(variables, letter_preview),
                unsafe_allow_html=True,
            )
    except RockyError as error:
        st.error(str(error))

    confirm = st.checkbox(
        "J’ai relu la lettre et je valide la génération",
        key=f"v2_confirm_letter_{job_id}",
    )
    if st.button(
        "Créer DOCX + PDF + copie du CV",
        key=f"v2_prepare_{job_id}",
        type="primary",
        disabled=not confirm or not letter_preview or not profile.cv_path,
        use_container_width=True,
    ):
        try:
            files = prepare_application(
                settings,
                profile,
                offer,
                variables,
                letter_text=letter_preview,
            )
            repository.create_application(
                job_id,
                profile.id,
                project_relative(files.cv_path, settings.project_dir),
                project_relative(files.docx_path, settings.project_dir),
                project_relative(files.pdf_path, settings.project_dir),
            )
            st.session_state[f"v2_files_{job_id}"] = files
            st.success(f"Dossier créé : {files.directory.name}")
        except (RockyError, OSError) as error:
            st.error(str(error))
    files = st.session_state.get(f"v2_files_{job_id}")
    if files:
        downloads = st.columns(3)
        for column, label, path in (
            (downloads[0], "CV", files.cv_path),
            (downloads[1], "DOCX", files.docx_path),
            (downloads[2], "PDF", files.pdf_path),
        ):
            column.download_button(
                f"Télécharger {label}",
                path.read_bytes(),
                file_name=path.name,
                key=f"v2_download_{job_id}_{label}",
                use_container_width=True,
            )
