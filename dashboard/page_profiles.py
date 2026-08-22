"""Gestion des profils reprise de Rocky V1.1."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.dashboard_common import load_data
from dashboard.rocky.errors import RockyError
from dashboard.rocky.letters import save_profile_cv
from dashboard.rocky.models import CandidateProfile
from dashboard.rocky.profile_skills import (
    add_missing_inferred_skills,
    infer_profile_skills_from_cv,
)
from dashboard.rocky.text_utils import ensure_list, project_relative


SKILL_CATEGORIES = ["technical", "business", "soft"]
SKILL_LEVELS = ["", "débutant", "intermédiaire", "avancé", "expert"]


def _experience_label(value: object) -> str:
    if value is None:
        return "expérience non précisée"
    try:
        years = float(value)
    except (TypeError, ValueError):
        return "expérience non précisée"
    amount = f"{years:g}".replace(".", ",")
    unit = "an" if years <= 1 else "ans"
    return f"{amount} {unit} d’expérience"


st.title("Mes profils")
st.caption("Profils, CV et compétences utilisés par la veille et le matching.")

try:
    settings, repository, active_profile, _ = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

profiles = repository.fetch_profiles()
with st.expander("Créer un nouveau profil"):
    with st.form("v2_create_profile"):
        new_name = st.text_input("Nom du profil")
        new_summary = st.text_area("Résumé")
        create = st.form_submit_button("Créer", type="primary")
    if create:
        if not new_name.strip():
            st.error("Le nom est obligatoire.")
        else:
            new_id = repository.create_profile(new_name, new_summary)
            if profiles.empty:
                repository.set_active_profile(new_id)
            st.rerun()

if profiles.empty:
    st.info("Crée ton premier profil pour démarrer.")
    st.stop()

profile_options = {
    int(row["id"]): str(row["profile_name"])
    for _, row in profiles.iterrows()
}
default_id = (
    active_profile.id if active_profile else next(iter(profile_options))
)
selected_id = st.selectbox(
    "Profil à modifier",
    list(profile_options),
    index=list(profile_options).index(default_id),
    format_func=lambda value: profile_options[value],
)
profile = repository.fetch_profile(int(selected_id))
if profile is None:
    st.error("Profil introuvable.")
    st.stop()

activation = st.columns([1, 3])
if activation[0].button(
    "Activer ce profil",
    disabled=profile.is_active,
    type="primary",
    use_container_width=True,
):
    repository.set_active_profile(profile.id)
    st.rerun()
activation[1].write(
    "✅ Profil actif pour la veille"
    if profile.is_active
    else "Ce profil n’est pas utilisé par la veille."
)

with st.form("v2_edit_profile"):
    profile_name = st.text_input("Nom", profile.profile_name)
    summary = st.text_area("Résumé professionnel", profile.summary)
    targets = st.text_input(
        "Postes ciblés", ", ".join(profile.target_job_titles)
    )
    contracts = st.text_input(
        "Contrats recherchés", ", ".join(profile.preferred_contracts)
    )
    locations = st.text_input(
        "Localisations", ", ".join(profile.preferred_locations)
    )
    remote = st.text_input(
        "Télétravail", ", ".join(profile.remote_preferences)
    )
    salary = st.number_input(
        "Salaire minimum",
        min_value=0,
        value=int(profile.minimum_salary or 0),
        step=1000,
    )
    save_profile = st.form_submit_button(
        "Enregistrer le profil", type="primary"
    )
if save_profile:
    repository.update_profile(
        CandidateProfile(
            id=profile.id,
            profile_name=profile_name,
            summary=summary,
            target_job_titles=ensure_list(targets),
            preferred_contracts=ensure_list(contracts),
            preferred_locations=ensure_list(locations),
            remote_preferences=ensure_list(remote),
            minimum_salary=salary or None,
            cv_path=profile.cv_path,
            is_active=profile.is_active,
        )
    )
    st.rerun()

st.subheader("CV associé")
cv_result_key = f"v2_cv_save_result_{profile.id}"
cv_result = st.session_state.pop(cv_result_key, None)
if cv_result:
    st.success(cv_result)
if profile.cv_path:
    st.success(f"CV disponible : {Path(profile.cv_path).name}")
uploaded_cv = st.file_uploader(
    "Ajouter ou remplacer le CV PDF",
    type=["pdf"],
    key=f"v2_cv_{profile.id}",
)
if uploaded_cv and st.button("Enregistrer ce CV"):
    try:
        cv_path = save_profile_cv(
            settings, profile.id, uploaded_cv.getvalue()
        )
        repository.save_cv_path(
            profile.id,
            project_relative(cv_path, settings.project_dir),
        )
        st.session_state[cv_result_key] = (
            f"CV « {uploaded_cv.name} » enregistré pour ce profil."
        )
        st.rerun()
    except (RockyError, OSError) as error:
        st.error(str(error))

st.markdown("#### Détection depuis le CV")
st.caption(
    "Rocky lit le PDF avec son extracteur existant, reconnaît les compétences de "
    "sa taxonomie et estime un niveau indicatif selon leur contexte et leur fréquence. "
    "Les compétences déjà présentes ne sont jamais modifiées."
)
if st.button(
    "Lire le CV et ajouter les compétences",
    key=f"v2_detect_cv_skills_{profile.id}",
    disabled=not profile.cv_path,
    type="primary",
):
    try:
        stored_cv_path = Path(profile.cv_path).expanduser()
        cv_path = (
            stored_cv_path
            if stored_cv_path.is_absolute()
            else settings.project_dir / stored_cv_path
        )
        inferred = infer_profile_skills_from_cv(cv_path)
        added, skipped = add_missing_inferred_skills(
            repository, profile.id, inferred
        )
        if not inferred:
            st.warning("Aucune compétence de la taxonomie Rocky n’a été détectée.")
        elif added:
            st.success(
                f"{added} compétence(s) ajoutée(s). "
                f"{skipped} compétence(s) existante(s) conservée(s)."
            )
        else:
            st.info(
                "Toutes les compétences détectées sont déjà présentes ; leurs "
                "niveaux manuels ont été conservés."
            )
    except (RockyError, OSError) as error:
        st.error(str(error))

st.subheader("Compétences")
with st.form("v2_add_skill"):
    skill_columns = st.columns(3)
    skill_name = skill_columns[0].text_input("Compétence")
    skill_category = skill_columns[1].selectbox(
        "Catégorie", SKILL_CATEGORIES
    )
    skill_level = skill_columns[2].selectbox(
        "Niveau", SKILL_LEVELS
    )
    years = st.number_input("Années d’expérience", min_value=0.0, step=0.5)
    core = st.checkbox("Compétence principale")
    add_skill = st.form_submit_button("Ajouter")
if add_skill:
    if not skill_name.strip():
        st.error("Le nom de la compétence est obligatoire.")
    else:
        repository.add_skill(
            profile.id,
            skill_name,
            skill_category,
            skill_level,
            years or None,
            core,
        )
        st.rerun()

for skill in repository.fetch_skills(profile.id):
    skill_id = int(skill["id"])
    columns = st.columns([5, 1, 1])
    level = str(skill.get("skill_level") or "niveau non précisé")
    columns[0].write(
        f"**{skill['skill_name']}** — {skill['skill_category']} · {level} · "
        f"{_experience_label(skill.get('years_experience'))}"
        + (" · principale" if skill["is_core_skill"] else "")
    )
    with columns[1].popover("Modifier", key=f"v2_edit_skill_{skill_id}"):
        st.caption(f"Modifier « {skill['skill_name']} »")
        with st.form(f"v2_edit_skill_form_{skill_id}"):
            edited_name = st.text_input(
                "Compétence",
                value=str(skill["skill_name"]),
                key=f"v2_edit_skill_name_{skill_id}",
            )
            current_category = str(skill.get("skill_category") or "technical")
            edited_category = st.selectbox(
                "Catégorie",
                SKILL_CATEGORIES,
                index=(
                    SKILL_CATEGORIES.index(current_category)
                    if current_category in SKILL_CATEGORIES
                    else 0
                ),
                key=f"v2_edit_skill_category_{skill_id}",
            )
            current_level = str(skill.get("skill_level") or "")
            edited_level = st.selectbox(
                "Niveau",
                SKILL_LEVELS,
                index=(
                    SKILL_LEVELS.index(current_level)
                    if current_level in SKILL_LEVELS
                    else 0
                ),
                key=f"v2_edit_skill_level_{skill_id}",
            )
            edited_years = st.number_input(
                "Années d’expérience",
                min_value=0.0,
                value=float(skill.get("years_experience") or 0),
                step=0.5,
                key=f"v2_edit_skill_years_{skill_id}",
            )
            edited_core = st.checkbox(
                "Compétence principale",
                value=bool(skill.get("is_core_skill")),
                key=f"v2_edit_skill_core_{skill_id}",
            )
            save_skill = st.form_submit_button(
                "Enregistrer", type="primary", use_container_width=True
            )
        if save_skill:
            if not edited_name.strip():
                st.error("Le nom de la compétence est obligatoire.")
            else:
                repository.update_skill(
                    skill_id,
                    profile.id,
                    edited_name,
                    edited_category,
                    edited_level,
                    edited_years or None,
                    edited_core,
                )
                st.rerun()
    if columns[2].button("Supprimer", key=f"v2_delete_skill_{skill_id}"):
        repository.delete_skill(skill_id)
        st.rerun()
