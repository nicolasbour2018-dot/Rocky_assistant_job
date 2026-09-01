##############################################################################################################
# Page d'import manuel d'une URL.
# Orchestration de la lecture de la page, de l'extraction des informations et de l'enregistrement dans la base.
#############################################################################################################

"""Import manuel et contrôlé d'une annonce depuis son URL.

La page télécharge, extrait et présente un aperçu avant insertion dans Rocky.
Elle permet de compléter une veille sans contourner la déduplication, le
matching ni la validation humaine de l'offre.
"""

# Importations standard
from __future__ import annotations

import streamlit as st

# Importations des modules internes
from dashboard.dashboard_common import load_data
from dashboard.rocky.errors import RockyError
from dashboard.rocky.job_importer import (
    ImportPreview,
    description_is_probably_truncated,
    import_job_url,
)
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.matching import calculate_match
from dashboard.rocky.models import JobOffer
from dashboard.rocky.statuses import JOB_STATUS_OPTIONS

st.title("Ajouter une URL")
st.caption(
    "Import V1.1 conservé : Rocky lit la page puis permet de vérifier les "
    "informations avant enregistrement."
)

try:
    settings, repository, profile, _ = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

# Sans profil actif, l'annonce serait insérée sans ligne dans `profile_jobs`.
# Elle reste visible tant que le compte n'a aucun profil, puis disparaît de
# toutes les vues dès la création du premier, sans moyen de la rattacher :
# les INSERT de reprise ont été retirés des schémas.
# TODO: rendre `profile_id` obligatoire dans `insert_job` et supprimer la
# branche `None` de sa signature. Cela demande de migrer les appels de tests,
# et rendrait cet état inexprimable au lieu de le garder sous condition.
if profile is None:
    st.info(
        "Crée d'abord un profil dans « Profil & CV ». Une annonce importée "
        "doit être rattachée à un profil pour rester visible."
    )
    st.stop()

llm = RockyLLM(settings)

url = st.text_input(
    "URL de l’annonce",
    placeholder="https://www.linkedin.com/jobs/view/...",
)
if st.button("Analyser l’URL", type="primary", disabled=not url.strip()):
    try:
        with st.spinner("Lecture de l’annonce…"):
            st.session_state.v2_import_preview = import_job_url(url, llm)
    except RockyError as error:
        st.error(str(error))
        st.session_state.v2_import_preview = ImportPreview(
            offer=JobOffer(
                job_title="",
                company_name="",
                responsibilities="",
                source_url=url,
                application_url=url,
            ),
            extraction_method="Saisie manuelle",
            warnings=["La page n’a pas pu être lue. Complète les champs manuellement."],
            raw_text="",
        )

preview = st.session_state.get("v2_import_preview")
if preview:
    for warning in preview.warnings:
        st.warning(warning)
    st.caption(f"Méthode : {preview.extraction_method}")
    imported = preview.offer
    with st.form("v2_import_job_form"):
        columns = st.columns(2)
        with columns[0]:
            title = st.text_input("Poste *", imported.job_title)
            company = st.text_input("Entreprise *", imported.company_name)
            city = st.text_input("Ville", imported.city)
            country = st.text_input("Pays", imported.country)
            contract = st.text_input("Contrat", imported.contract_type)
            schedule = st.text_input("Temps de travail", imported.work_schedule)
            remote = st.text_input("Télétravail", imported.remote_policy)
        with columns[1]:
            source = st.text_input("Source", imported.source_name)
            external_id = st.text_input("Identifiant externe", imported.external_id)
            application_url = st.text_input(
                "URL de candidature", imported.application_url
            )
            salary_min = st.number_input(
                "Salaire minimum",
                min_value=0.0,
                value=float(imported.salary_min or 0),
                step=1000.0,
            )
            salary_max = st.number_input(
                "Salaire maximum",
                min_value=0.0,
                value=float(imported.salary_max or 0),
                step=1000.0,
            )
            status = st.selectbox("Statut", JOB_STATUS_OPTIONS)
        short_description = st.text_area(
            "Résumé", imported.short_description, height=100
        )
        description = st.text_area(
            "Description complète *", imported.responsibilities, height=320
        )
        save = st.form_submit_button("Enregistrer l’annonce", type="primary")

    if save:
        if not title.strip() or not company.strip():
            st.error("Le poste et l’entreprise sont obligatoires.")
        elif not description.strip():
            st.error("La description est obligatoire.")
        elif description_is_probably_truncated(description):
            st.error("La description se termine par … et semble encore tronquée.")
        else:
            offer = JobOffer(
                job_title=title.strip(),
                company_name=company.strip(),
                responsibilities=description.strip(),
                short_description=short_description.strip(),
                source_name=source.strip() or "URL",
                source_url=imported.source_url,
                application_url=application_url.strip(),
                external_id=external_id.strip(),
                city=city.strip(),
                country=country.strip(),
                contract_type=contract.strip(),
                work_schedule=schedule.strip(),
                remote_policy=remote.strip(),
                salary_min=salary_min or None,
                salary_max=salary_max or None,
                salary_currency=imported.salary_currency,
                publication_date=imported.publication_date,
                application_deadline=imported.application_deadline,
                status=status,
                description_is_full=True,
                description_enrichment_source="Import URL",
            )
            job_id, inserted = repository.insert_job(offer, profile.id)
            localized = repository.profile_for_offer(profile.id, offer) or profile
            result = calculate_match(
                offer, localized, repository.fetch_skills(profile.id)
            )
            repository.save_match(job_id, profile.id, result)
            if inserted:
                st.success("Annonce enregistrée.")
                del st.session_state.v2_import_preview
                st.rerun()
            else:
                st.info("Cette annonce était déjà présente.")
