                    ##############################################################################################################
                        # Module d'affichage et d'orchestration du banc de test ATS V3.
                        # Test ATS V3 : robustesse multi-parseurs, couverture lexicale et sémantique.
                        # Test effectué à partir du dictionnaire de compétences déterministe, sans texte corrigé ni LLM.
                    #############################################################################################################

"""Banc de test ATS V3 sur le CV réellement transmis.

La page compare plusieurs parseurs, mesure la couverture des compétences et
présente des simulations explicables. Elle sert à relire la robustesse d'un
dossier ; elle ne prédit pas une décision d'employeur et ne modifie aucun CV.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_data, plain_description
from dashboard.job_detail_components import render_ats_report, render_ats_v2_report
from dashboard.rocky.ats import (
    analyze_application_ats,
    analyze_application_ats_v2,
)
from dashboard.rocky.ats_v3 import (
    AtsV3Report,
    analyze_ats_v3,
    poppler_diagnostic,
    render_pdf_first_page,
)
from dashboard.rocky.errors import DocumentError, RockyError


REPORT_KEY = "ats_v3_report"
CV_BYTES_KEY = "ats_v3_cv_bytes"
CV_NAME_KEY = "ats_v3_cv_name"
JOB_ID_KEY = "ats_v3_report_job_id"
INPUT_FINGERPRINT_KEY = "ats_v3_input_fingerprint"
MY_JOB_STATUSES = {
    "À ÉTUDIER",
    "RETENUE",
    "CANDIDATURE ENVOYÉE",
    "ENTRETIEN",
    "REFUS",
}


def _percent(value: int | None) -> str:
    """Formate une mesure ATS optionnelle sans masquer une donnée indisponible."""
    return "—" if value is None else f"{value} %"


def _fingerprint(
    cv_data: bytes | None, file_name: str, description: str, job_title: str
) -> str:
    """Identifie les entrées ATS pour éviter de recalculer un diagnostic identique."""
    digest = hashlib.sha256()
    digest.update(cv_data or b"")
    digest.update(file_name.encode("utf-8"))
    digest.update(description.encode("utf-8"))
    digest.update(job_title.encode("utf-8"))
    return digest.hexdigest()


def _cv_path(settings: Any, profile: Any) -> Path | None:
    """Résout le CV actif du profil lorsque aucun fichier de test n'est téléversé."""
    if profile is None or not profile.cv_path:
        return None
    path = Path(profile.cv_path).expanduser()
    return path if path.is_absolute() else settings.project_dir / path


def _job_label(row: pd.Series) -> str:
    """Construit le libellé de sélection d'une annonce dans le contexte ATS."""
    title = str(row.get("job_title") or "Sans titre")
    company = str(row.get("company_name") or "Entreprise inconnue")
    source = str(row.get("source_name") or "Source inconnue")
    marker = "complète" if bool(row.get("description_is_full")) else "incomplète"
    return f"#{int(row['id'])} · {title} — {company} · {source} · {marker}"


def _selected_job(jobs: pd.DataFrame) -> tuple[int | None, pd.Series | None]:
    """Laisse choisir l'annonce qui fournit le texte de comparaison ATS."""
    if jobs.empty:
        st.info("Aucune annonce de « Mes annonces » n’est disponible. Utilise le texte manuel.")
        return None, None
    rows = [row for _, row in jobs.iterrows()]
    requested = st.session_state.get("ats_v3_job_id") or st.session_state.get(
        "selected_job_id"
    )
    ids = [int(row["id"]) for row in rows]
    index = ids.index(int(requested)) if requested and int(requested) in ids else 0
    selected_id = st.selectbox(
        "Annonce Rocky",
        ids,
        index=index,
        format_func=lambda job_id: _job_label(rows[ids.index(job_id)]),
        key="ats_v3_selected_job",
    )
    return int(selected_id), rows[ids.index(selected_id)]


def _my_jobs(frame: pd.DataFrame) -> pd.DataFrame:
    """Retient les mêmes annonces que la vue « Mes annonces » du cockpit."""
    if frame.empty:
        return frame.copy()
    statuses = frame["status"].fillna("").astype(str).str.strip().str.upper()
    full = frame["description_is_full"].fillna(False).astype(bool)
    scores = pd.to_numeric(frame["match_score"], errors="coerce")
    return frame[full & scores.notna() & statuses.isin(MY_JOB_STATUSES)].copy()


def _existing_letter_text(
    settings: Any, repository: Any, profile_id: int, job_id: int
) -> tuple[str, str]:
    """Retrouve le brouillon courant ou la dernière lettre DOCX enregistrée."""
    draft = str(st.session_state.get(f"v2_letter_editor_{job_id}") or "").strip()
    if draft:
        return draft, "brouillon de lettre en cours"
    applications = repository.fetch_applications()
    if applications.empty:
        return "", ""
    matching = applications[
        (applications["job_id"] == job_id)
        & (applications["profile_id"] == profile_id)
    ]
    for _, application in matching.iterrows():
        stored_path = application.get("letter_docx_path")
        if not stored_path or pd.isna(stored_path):
            continue
        docx_path = Path(str(stored_path))
        if not docx_path.is_absolute():
            docx_path = settings.project_dir / docx_path
        if not docx_path.is_file():
            continue
        try:
            from docx import Document

            text = "\n".join(
                paragraph.text.strip()
                for paragraph in Document(docx_path).paragraphs
                if paragraph.text.strip()
            )
        except (ImportError, OSError, ValueError):
            continue
        if text:
            return text, "dernière lettre DOCX enregistrée"
    return "", ""


def _job_text(row: pd.Series | None) -> tuple[str, str]:
    """Extrait la description et l'intitulé réellement fournis au banc ATS."""
    if row is None:
        return "", ""
    full = plain_description(row.get("responsibilities"))
    short = plain_description(row.get("short_description"))
    description = full or short
    return description, str(row.get("job_title") or "")


def _source_controls(
    settings: Any, profile: Any, jobs: pd.DataFrame
) -> tuple[bytes | None, str, str, str, int | None]:
    """Collecte les entrées explicites du test : CV, annonce et éventuel texte manuel."""
    st.subheader("Documents testés")
    left, right = st.columns(2)
    with left:
        st.markdown("##### CV réel")
        default_path = _cv_path(settings, profile)
        uploaded = st.file_uploader(
            "PDF ou DOCX",
            type=("pdf", "docx"),
            help=(
                "Sans fichier importé, Rocky utilise le CV du profil actif. "
                "Le PDF est analysé directement, sans texte corrigé par V2."
            ),
        )
        if uploaded is not None:
            cv_data = uploaded.getvalue()
            file_name = uploaded.name
            st.success(f"Fichier importé : {file_name}")
        elif default_path and default_path.is_file():
            cv_data = default_path.read_bytes()
            file_name = default_path.name
            st.caption(f"CV du profil actif : {default_path.name}")
        else:
            cv_data = None
            file_name = ""
            st.warning("Aucun CV PDF ou DOCX n’est disponible.")

    with right:
        st.markdown("##### Annonce")
        mode = st.radio(
            "Source de la description",
            ("Annonce Rocky", "Texte manuel"),
            horizontal=True,
        )
        selected_id: int | None = None
        if mode == "Annonce Rocky":
            selected_id, selected_row = _selected_job(jobs)
            description, job_title = _job_text(selected_row)
            if selected_row is not None and not bool(
                selected_row.get("description_is_full")
            ):
                st.warning(
                    "Cette annonce est marquée incomplète. Le test utilise seulement "
                    "le texte réellement disponible et peut donc sous-estimer le matching."
                )
            st.text_area(
                "Description utilisée",
                description,
                height=180,
                disabled=True,
                key=f"ats_v3_rocky_description_{selected_id}",
            )
        else:
            job_title = st.text_input("Intitulé du poste", key="ats_v3_manual_title")
            description = st.text_area(
                "Description complète de l’annonce",
                height=245,
                key="ats_v3_manual_description",
                placeholder="Colle ici les missions, exigences et compétences attendues.",
            )
    return cv_data, file_name, description, job_title, selected_id


def _summary(report: AtsV3Report, job_id: int | None) -> None:
    """Affiche la synthèse multi-indicateurs sans confondre V1, V2 et V3."""
    st.subheader("Résumé multi-indicateurs")
    st.caption(
        "Aucun profil Rocky, texte ATS corrigé ou LLM n’a complété le contenu du CV. "
        "Les résultats proviennent uniquement du fichier transmis aux parseurs."
    )
    metrics = st.columns(5)
    metrics[0].metric("Robustesse parsing", _percent(report.parsing_robustness))
    metrics[1].metric("Cohérence parseurs", _percent(report.parser_consistency))
    metrics[2].metric("Termes exacts", _percent(report.exact_coverage))
    metrics[3].metric("Couverture lexicale", _percent(report.lexical_coverage))
    metrics[4].metric("Mots-clés", _percent(report.keyword_coverage))

    secondary = st.columns(4)
    secondary[0].metric("Exigences obligatoires", _percent(report.mandatory_coverage))
    secondary[1].metric(
        "Équivalences sémantiques",
        _percent(report.semantic_coverage),
        help="Mesurée seulement parmi les compétences absentes lexicalement.",
    )
    secondary[2].metric("Compétences demandées", len(report.requirements))
    secondary[3].metric("Risques / actions", len(report.recommendations))

    with st.expander("Note synthétique secondaire et formule"):
        st.metric("Résumé secondaire", _percent(report.secondary_summary))
        st.code(
            "45 % robustesse parsing + 40 % couverture lexicale "
            "+ 15 % couverture des mots-clés"
        )
        st.caption(
            "Cette note n’est pas une probabilité de franchir un ATS et ne remplace "
            "pas les indicateurs détaillés."
        )

    st.markdown("##### Comparaison de philosophie V1 / V2 / V3")
    v1 = st.session_state.get(f"v2_ats_report_{job_id}") if job_id else None
    v2 = st.session_state.get(f"v2_ats_v2_report_{job_id}") if job_id else None
    comparison = pd.DataFrame(
        [
            {
                "Version": "V1",
                "Résultat courant": f"{v1.score} / 100" if v1 else "Non lancé",
                "Objet mesuré": "Lecture PDF brute + CV/lettre/annonce",
            },
            {
                "Version": "V2",
                "Résultat courant": f"{v2.score} / 100" if v2 else "Non lancé",
                "Objet mesuré": "Texte corrigible + proximité lexicale + lettre",
            },
            {
                "Version": "V3",
                "Résultat courant": (
                    f"Parsing {report.parsing_robustness} % · "
                    f"Lexical {_percent(report.lexical_coverage)}"
                ),
                "Objet mesuré": "Robustesse multi-parseurs du fichier réel",
            },
        ]
    )
    st.dataframe(comparison, hide_index=True, width="stretch")
    st.caption(
        "Les notes ne sont pas directement équivalentes : le contraste entre les "
        "trois philosophies est précisément l’objet de cette comparaison."
    )


def _parser_comparison(report: AtsV3Report) -> None:
    """Compare les extractions structurées afin de révéler les fragilités de parsing."""
    st.markdown("##### Champs structurés par moteur")
    rows = []
    for extraction in report.parser_extractions:
        structured = extraction.structured
        rows.append(
            {
                "Parseur": extraction.label,
                "Qualité": f"{extraction.quality_score} %",
                "Nom": structured.name or "—",
                "Coordonnées": (
                    f"{len(structured.emails)} e-mail · {len(structured.phones)} tél."
                ),
                "Titre": structured.professional_title or "—",
                "Expériences": len(structured.experiences),
                "Entreprises": len(structured.companies),
                "Dates": len(structured.dates),
                "Diplômes/lignes": len(structured.education),
                "Établissements": len(structured.institutions),
                "Compétences": len(structured.skills),
                "Langues": len(structured.languages),
                "Certifications": len(structured.certifications),
                "Projets": len(structured.projects),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    columns = st.columns(len(report.parser_extractions))
    for column, extraction in zip(columns, report.parser_extractions):
        with column:
            st.markdown(f"**{extraction.label}**")
            st.caption(f"{extraction.engine} · {extraction.license}")
            st.metric("Qualité d’extraction", f"{extraction.quality_score} %")
            st.write(
                f"{extraction.word_count} mots · "
                f"{extraction.character_count} caractères"
            )
            if extraction.warnings:
                for warning in extraction.warnings:
                    st.warning(warning)
            else:
                st.success("Aucun signal de parsing majeur.")


def _matching(report: AtsV3Report) -> None:
    """Restitue la couverture des compétences annonce/CV pour chaque parseur."""
    parser_labels = {
        extraction.parser_id: extraction.label
        for extraction in report.parser_extractions
    }
    if not report.skill_comparisons:
        st.info(
            "Aucune compétence de la taxonomie déterministe n’a été identifiée "
            "dans l’annonce. Consulte la couverture des mots-clés et les vues brutes."
        )
        return
    rows: list[dict[str, Any]] = []
    for item in report.skill_comparisons:
        exact = set(item.exact_parsers)
        variants = set(item.variant_parsers)
        semantic = {evidence.parser_id: evidence.evidence for evidence in item.semantic_evidence}
        row: dict[str, Any] = {
            "Compétence": item.skill,
            "Importance": item.importance,
            "Terme annonce": item.job_evidence,
        }
        for parser_id, label in parser_labels.items():
            if parser_id in exact:
                value = "Exact"
            elif parser_id in variants:
                value = "Variante lexicale"
            elif parser_id in semantic:
                value = f"Sémantique seulement : {semantic[parser_id]}"
            else:
                value = "Absente"
            row[label] = value
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Une équivalence sémantique reste explicitement séparée et ne transforme "
        "jamais une absence lexicale en présence."
    )

    missing = [
        item.skill
        for item in report.skill_comparisons
        if not item.exact_parsers and not item.variant_parsers
    ]
    partial = [
        item.skill
        for item in report.skill_comparisons
        if 0
        < len(item.exact_parsers) + len(item.variant_parsers)
        < len(report.parser_extractions)
    ]
    summary = st.columns(2)
    summary[0].write("**Absentes lexicalement**")
    summary[0].write(", ".join(missing) if missing else "Aucune")
    summary[1].write("**Instables selon le parseur**")
    summary[1].write(", ".join(partial) if partial else "Aucune")


def _benchmarks(report: AtsV3Report) -> None:
    """Affiche des benchmarks pédagogiques, explicitement distincts d'ATS propriétaires."""
    st.warning(
        "Ces résultats sont des simulations de comportement inspirées de familles "
        "d’ATS. Ils ne reproduisent pas les algorithmes propriétaires ni les réglages "
        "d’une entreprise donnée."
    )
    rows = [
        {
            "Benchmark": item.name,
            "Indicateur": f"{item.score} / 100",
            "Lecture": item.interpretation,
            "Parsing": f"{item.parsing_component} %",
            "Lexical": f"{item.lexical_component} %",
            "Structure": f"{item.structure_component} %",
            "Hypothèses": " · ".join(item.notes),
        }
        for item in report.benchmark_results
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Méthode réimplémentée dans Rocky d’après les idées publiques d’ATS Screener ; "
        "aucun moteur, poids ou code propriétaire d’un éditeur ATS n’est utilisé."
    )


def _diagnostic(report: AtsV3Report) -> None:
    """Présente les recommandations et limites mesurables du rapport ATS V3."""
    st.markdown("##### Observations mesurables")
    for recommendation in report.recommendations:
        st.write(f"- {recommendation}")
    st.markdown("##### Limites connues")
    for limit in report.limits:
        st.caption(f"• {limit}")


def _raw_view(report: AtsV3Report, cv_data: bytes, file_name: str) -> None:
    """Expose le document source et ses extractions sans les modifier."""
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        visual, parsed = st.columns([1, 1])
        with visual:
            st.markdown("##### CV visuel réel — première page")
            try:
                st.image(
                    render_pdf_first_page(cv_data),
                    caption="Rendu direct du PDF transmis",
                    width="stretch",
                )
            except (DocumentError, OSError, ValueError) as error:
                st.error(f"Aperçu impossible : {error}")
        with parsed:
            st.markdown("##### Ce que voient les parseurs")
            _raw_parser_tabs(report)
    else:
        st.info(
            "Streamlit ne rend pas le DOCX fidèlement dans cette page. Télécharge le "
            "fichier pour le comparer visuellement aux extractions."
        )
        st.download_button("Télécharger le DOCX testé", cv_data, file_name=file_name)
        _raw_parser_tabs(report)

    if suffix == ".pdf":
        with st.expander("Diagnostic externe optionnel : Poppler pdftotext -layout"):
            st.caption(
                "Cette extraction n’entre dans aucun score. Elle sert uniquement de "
                "quatrième point de comparaison lorsqu’un binaire Poppler est installé."
            )
            poppler_text = poppler_diagnostic(cv_data)
            if poppler_text is None:
                st.info("Poppler n’est pas disponible dans cet environnement.")
            else:
                st.text_area(
                    "Texte Poppler",
                    poppler_text,
                    height=500,
                    disabled=True,
                )


def _raw_parser_tabs(report: AtsV3Report) -> None:
    """Organise les textes bruts et structures produits par chaque parseur."""
    tabs = st.tabs([item.label for item in report.parser_extractions])
    for tab, extraction in zip(tabs, report.parser_extractions):
        with tab:
            mode = st.radio(
                "Vue",
                ("Texte brut", "Extraction structurée"),
                horizontal=True,
                key=f"ats_v3_raw_mode_{extraction.parser_id}",
            )
            if mode == "Texte brut":
                st.text_area(
                    f"Texte extrait par {extraction.label}",
                    extraction.raw_text,
                    height=600,
                    disabled=True,
                    key=f"ats_v3_raw_{extraction.parser_id}",
                )
            else:
                st.json(asdict(extraction.structured), expanded=True)


st.title("ATS")
st.write(
    "Centralise les contrôles ATS V1, V2 et V3 pour comparer le CV, la lettre "
    "et l’annonce dans un seul espace."
)

try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

my_jobs = _my_jobs(jobs)
cv_data, file_name, description, job_title, selected_job_id = _source_controls(
    settings, profile, my_jobs
)

actions = st.columns([2, 1])
if actions[0].button(
    "Lancer le banc de test V3",
    type="primary",
    width="stretch",
    disabled=not cv_data or len(description.strip()) < 80,
):
    try:
        with st.spinner("Exécution indépendante de chaque parseur…"):
            report = analyze_ats_v3(
                cv_data,
                file_name,
                description,
                job_title=job_title,
            )
        st.session_state[REPORT_KEY] = report
        st.session_state[CV_BYTES_KEY] = cv_data
        st.session_state[CV_NAME_KEY] = file_name
        st.session_state[JOB_ID_KEY] = selected_job_id
        st.session_state[INPUT_FINGERPRINT_KEY] = _fingerprint(
            cv_data, file_name, description, job_title
        )
    except (DocumentError, RockyError, OSError) as error:
        st.error(str(error))

if len(description.strip()) < 80:
    actions[1].caption("Description trop courte : 80 caractères minimum.")

report = st.session_state.get(REPORT_KEY)
if report:
    if st.session_state.get(INPUT_FINGERPRINT_KEY) != _fingerprint(
        cv_data, file_name, description, job_title
    ):
        st.warning(
            "Les documents sélectionnés ont changé depuis ce rapport. Relance V3 "
            "pour actualiser les résultats."
        )
    with st.expander("Rapport ATS V3", expanded=False):
        summary_tab, parsing_tab, matching_tab, benchmark_tab, diagnostic_tab, raw_tab = st.tabs(
            ("Résumé", "Parsing", "Matching annonce", "Benchmarks ATS", "Diagnostic", "Vue brute")
        )
        with summary_tab:
            _summary(report, st.session_state.get(JOB_ID_KEY))
        with parsing_tab:
            _parser_comparison(report)
        with matching_tab:
            _matching(report)
        with benchmark_tab:
            _benchmarks(report)
        with diagnostic_tab:
            _diagnostic(report)
        with raw_tab:
            _raw_view(
                report,
                st.session_state.get(CV_BYTES_KEY, b""),
                st.session_state.get(CV_NAME_KEY, report.file_name),
            )
