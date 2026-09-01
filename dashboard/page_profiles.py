"""Gestion document-first des profils et CV bilingues.

La page guide l'import, l'analyse consentie et la validation des informations
réellement présentes dans les documents. Ces données alimentent ensuite veille,
matching et génération sans traduire ni inventer les pièces sources.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import streamlit as st

from dashboard.dashboard_common import load_data
from dashboard.rocky.errors import RockyError
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.profile_documents import (
    analyze_profile,
    save_uploaded_profile_document,
)
from dashboard.rocky.profile_skills import (
    add_missing_inferred_skills,
    infer_profile_skills_from_cv,
)
from dashboard.rocky.projects import (
    ensure_projects_file,
    load_profile_projects,
    prefill_english_projects,
    save_profile_projects,
)
from dashboard.rocky.text_utils import ensure_list


SKILL_CATEGORIES = ["technical", "business", "soft"]
SKILL_LEVELS = ["", "débutant", "intermédiaire", "avancé", "expert"]
RECALCULATE_LABEL = "Recalculer tous les scores"


def _resolve(project_dir: Path, value: str) -> Path:
    """Résout un chemin privé stocké en relatif ou en absolu selon le volume."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_dir / path


def _journey(readiness: list[bool], locale: str) -> None:
    """Affiche les cinq jalons comme une histoire courte et vérifiable."""
    labels = (
        (
            ("01", "Upload your documents", "Your English CV and cover letter."),
            (
                "02",
                "Your English profile",
                "A pre-filled version of your French profile.",
            ),
            ("03", "Refine your target", "Roles, sectors and preferences."),
            ("04", "Validate your strengths", "Summary, skills and evidence."),
            ("05", "Your kit is ready", "Reviewed, downloadable English documents."),
        )
        if locale == "en"
        else (
            ("01", "Pose tes documents", "CV et lettre français d'abord."),
            ("02", "Rocky fait l'inventaire", "Analyse et préremplissage prudent."),
            ("03", "Affine ta cible", "Postes, domaines et préférences."),
            ("04", "Valide tes forces", "Résumé, compétences et preuves."),
            (
                "05",
                "Ton kit est prêt",
                "CV et lettre EN importés, relus et téléchargeables.",
            ),
        )
    )
    columns = st.columns(5)
    for column, (number, title, detail), ready in zip(
        columns, labels, readiness, strict=True
    ):
        with column, st.container(border=True):
            state = "✓ ready" if ready else "to prepare"
            if locale == "fr":
                state = "✓ prêt" if ready else "à préparer"
            st.caption(f"{number} · {state}")
            st.markdown(f"**{title}**")
            st.caption(detail)
    st.progress(
        sum(readiness) / len(readiness), text=f"{sum(readiness)}/5 jalons validés"
    )


def _document_map(repository, profile_id: int, locale: str):
    """Indexe les documents courants d'une langue par usage métier."""
    return {
        document.kind: document
        for document in repository.fetch_profile_documents(profile_id, locale)
    }


def _ensure_english_localization(settings, repository, profile_id: int) -> bool:
    """Crée une copie anglaise préremplie lors de la première ouverture EN.

    Les documents restent strictement importés par l'utilisateur. Seuls les
    champs courts du profil français déjà validés sont traduits pour éviter une
    seconde saisie à blanc ; ils demeurent éditables dans l'espace anglais.
    """
    existing_english = repository.fetch_localization(profile_id, "en")
    if existing_english is not None:
        _ensure_english_skill_labels(settings, repository, profile_id)
        prefill_english_projects(profile_id, settings, repository, RockyLLM(settings))
        return True
    french = repository.fetch_localization(profile_id, "fr")
    if french is None:
        return False
    if not (
        french.summary.strip() or french.target_job_titles or french.target_domains
    ):
        # Un nouveau brouillon n'a rien à traduire : créer la version EN vide
        # évite un appel inutile et laisse immédiatement la page anglaise
        # accueillir sa saisie initiale.
        repository.save_localization(replace(french, locale="en"))
        _ensure_english_skill_labels(settings, repository, profile_id)
        return True
    llm = RockyLLM(settings)
    if not llm.is_configured:
        return False
    translated = llm.translate_profile_localization(french)
    repository.save_localization(translated)
    _ensure_english_skill_labels(settings, repository, profile_id, llm)
    prefill_english_projects(profile_id, settings, repository, llm)
    return True


def _ensure_english_skill_labels(
    settings, repository, profile_id: int, llm=None
) -> None:
    """Préremplit les libellés anglais des compétences canoniques restantes."""
    missing_skills = [
        skill
        for skill in repository.fetch_skills(profile_id)
        if not str(skill.get("skill_name_en") or "").strip()
    ]
    if not missing_skills:
        return
    llm = llm or RockyLLM(settings)
    if not llm.is_configured:
        return
    translated_labels = llm.translate_blocks(
        [str(skill["skill_name"]) for skill in missing_skills]
    )
    for skill, label in zip(missing_skills, translated_labels, strict=True):
        repository.set_skill_translation(int(skill["id"]), label)


def _upload_card(
    settings, repository, user_id: int, profile_id: int, locale: str
) -> None:
    """Rend les deux imports d'une langue et publie seulement un fichier validé."""
    language = "française" if locale == "fr" else "English"
    st.markdown(f"**Version {language}**")
    if locale == "en":
        st.caption(
            "Upload your own English files. Rocky does not translate or generate "
            "them; they will be used for English job postings."
        )
    cv = st.file_uploader(
        f"CV PDF · {locale.upper()}",
        type=["pdf"],
        key=f"profile_cv_{profile_id}_{locale}",
    )
    letter = st.file_uploader(
        ("Lettre DOCX" if locale == "fr" else "Cover letter DOCX")
        + f" · {locale.upper()}",
        key=f"profile_letter_{profile_id}_{locale}",
        help=(
            "Le document doit contenir exactement [paragraphe Rocky]."
            if locale == "fr"
            else "The document must contain exactly one [paragraphe Rocky] marker."
        ),
    )
    actions = st.columns(2)
    if actions[0].button(
        "Enregistrer le CV" if locale == "fr" else "Save CV",
        key=f"save_cv_{profile_id}_{locale}",
        disabled=cv is None,
        use_container_width=True,
    ):
        try:
            save_uploaded_profile_document(
                settings, repository, user_id, profile_id, locale, "cv", cv.getvalue()
            )
        except (RockyError, OSError) as error:
            st.error(str(error))
        else:
            st.success("CV validé et enregistré." if locale == "fr" else "CV saved.")
            st.rerun()
    if actions[1].button(
        "Enregistrer la lettre" if locale == "fr" else "Save cover letter",
        key=f"save_letter_{profile_id}_{locale}",
        disabled=letter is None,
        use_container_width=True,
    ):
        try:
            save_uploaded_profile_document(
                settings,
                repository,
                user_id,
                profile_id,
                locale,
                "letter",
                letter.getvalue(),
            )
        except (RockyError, OSError) as error:
            st.error(str(error))
        else:
            st.success(
                "Lettre et aperçu PDF validés."
                if locale == "fr"
                else "Cover letter and PDF preview saved."
            )
            st.rerun()


def _render_analysis_feedback(result) -> None:
    """Transforme l'inventaire brut en restitution rassurante et actionnable.

    Les suggestions s'appuient uniquement sur les champs vides, les faits
    extraits et les ambiguïtés signalées par l'analyse. Elles guident la
    relecture sans attribuer au candidat une expérience absente du CV.
    """
    name = result.full_name.split(maxsplit=1)[0] if result.full_name else ""
    greeting = f" {name}" if name else ""
    st.success(
        f"Belle base{greeting} : Rocky a relevé les éléments explicites de tes "
        "documents. Tu gardes la main sur chaque information avant validation."
    )

    st.markdown("#### Ce que Rocky a compris")
    overview = st.columns(4)
    overview[0].metric("Compétences relevées", len(result.skills))
    overview[1].metric("Étapes de parcours", len(result.career_items))
    overview[2].metric("Projets / preuves", len(result.project_evidence))
    overview[3].metric("Cibles identifiées", len(result.target_job_titles))

    strengths: list[str] = []
    if result.summary:
        strengths.append(f"**Fil conducteur professionnel** — {result.summary}")
    if result.skills:
        strengths.append("**Compétences nommées** — " + ", ".join(result.skills[:8]))
    if result.career_items:
        strengths.append(
            "**Parcours tangible** — " + " · ".join(result.career_items[:3])
        )
    if result.project_evidence:
        strengths.append(
            "**Preuves concrètes** — " + " · ".join(result.project_evidence[:3])
        )
    if strengths:
        st.markdown("**Tes points d'appui**")
        for strength in strengths:
            st.markdown(f"- {strength}")
    else:
        st.info(
            "Les documents ne donnent pas encore assez de faits structurés. "
            "Ce n'est pas bloquant : complète simplement les cartes ci-dessous."
        )

    improvements: list[str] = []
    if not result.summary:
        improvements.append(
            "Ajoute un résumé de deux ou trois phrases : rôle, expertise et type "
            "de contribution recherché."
        )
    if not result.target_job_titles:
        improvements.append(
            "Nomme un à trois postes ciblés afin que Rocky puisse mieux prioriser "
            "les annonces."
        )
    if not result.target_domains:
        improvements.append(
            "Précise les domaines qui t'attirent pour rendre le matching plus "
            "pertinent."
        )
    if not result.skills:
        improvements.append(
            "Liste les outils, méthodes et savoir-faire que tu souhaites mettre "
            "en avant."
        )
    elif not result.skill_levels:
        improvements.append(
            "Indique ton niveau sur les compétences clés : cela rendra le profil "
            "plus lisible pour chaque candidature."
        )
    if not result.project_evidence:
        improvements.append(
            "Ajoute un ou deux projets, résultats ou réalisations vérifiables pour "
            "ancrer ton profil dans du concret."
        )
    if result.warnings:
        improvements.extend(
            f"À vérifier ensemble : {warning}" for warning in result.warnings
        )

    st.markdown("**Pour le rendre encore plus convaincant**")
    if improvements:
        for improvement in improvements:
            st.markdown(f"- {improvement}")
    else:
        st.caption(
            "Les éléments essentiels sont déjà présents. Une relecture des cibles "
            "et des niveaux de compétence suffit avant de passer au kit bilingue."
        )
    st.caption(
        "Étape suivante : ajuste les champs proposés, puis valide-les. Rocky "
        "n'enregistrera que les informations que tu confirmes."
    )


def _analysis_editor(settings, repository, profile, french_documents) -> None:
    """Analyse les sources puis laisse l'utilisateur valider chaque fait extrait."""
    st.caption(
        "Rocky n'invente rien. Avec ton accord, le texte extrait est envoyé au "
        "service Mistral configuré ; les documents eux-mêmes ne sont pas journalisés."
    )
    consent = st.checkbox(
        "J'autorise l'analyse Mistral pour préremplir ce profil.",
        key=f"analysis_consent_{profile.id}",
    )
    if st.button(
        "Analyser mes deux documents",
        type="primary",
        disabled=not {"cv", "letter"} <= set(french_documents),
        key=f"analyze_profile_{profile.id}",
    ):
        try:
            with st.spinner("Rocky inventorie les faits présents dans tes documents…"):
                result = analyze_profile(
                    settings,
                    _resolve(settings.project_dir, french_documents["cv"].source_path),
                    _resolve(
                        settings.project_dir, french_documents["letter"].source_path
                    ),
                    consent,
                )
                repository.save_profile_analysis(profile.id, result)
        except (RockyError, OSError) as error:
            st.error(str(error))
        else:
            st.session_state[f"profile_analysis_{profile.id}"] = result
            st.rerun()

    result = st.session_state.get(
        f"profile_analysis_{profile.id}"
    ) or repository.fetch_profile_analysis(profile.id)
    if result is None:
        st.info("Lance l'analyse ou complète directement les cartes suivantes.")
        return
    _render_analysis_feedback(result)
    with st.form(f"apply_profile_analysis_{profile.id}"):
        st.markdown("**Vérifie le préremplissage avant de l'enregistrer**")
        full_name = st.text_input(
            "Nom complet", value=result.full_name or profile.full_name
        )
        email = st.text_input(
            "E-mail de candidature", value=result.email or profile.email
        )
        phone = st.text_input("Téléphone", value=result.phone or profile.phone)
        summary = st.text_area("Résumé", value=result.summary or profile.summary)
        targets = st.text_input(
            "Postes ciblés",
            value=", ".join(result.target_job_titles or profile.target_job_titles),
        )
        domains = st.text_input(
            "Domaines", value=", ".join(result.target_domains or profile.target_domains)
        )
        career_text = st.text_area(
            "Parcours détecté · un élément par ligne",
            value="\n".join(result.career_items),
        )
        evidence_text = st.text_area(
            "Projets et preuves détectés · un élément par ligne",
            value="\n".join(result.project_evidence),
        )
        submitted = st.form_submit_button("Valider ces informations", type="primary")
    if submitted:
        repository.update_profile(
            replace(
                profile,
                full_name=full_name,
                email=email,
                phone=phone,
                summary=summary,
                target_job_titles=ensure_list(targets),
                target_domains=ensure_list(domains),
                locale="fr",
            )
        )
        inferred = infer_profile_skills_from_cv(
            _resolve(settings.project_dir, french_documents["cv"].source_path)
        )
        add_missing_inferred_skills(repository, profile.id, inferred)
        existing = {
            str(skill["skill_name"]).casefold()
            for skill in repository.fetch_skills(profile.id)
        }
        levels = {name.casefold(): level for name, level in result.skill_levels}
        for name in result.skills:
            if name.casefold() not in existing:
                repository.add_skill(
                    profile.id, name, "business", levels.get(name.casefold(), "")
                )
        validated_analysis = replace(
            result,
            career_items=tuple(
                line.strip() for line in career_text.splitlines() if line.strip()
            ),
            project_evidence=tuple(
                line.strip() for line in evidence_text.splitlines() if line.strip()
            ),
        )
        repository.save_profile_analysis(
            profile.id, validated_analysis, status="accepted"
        )
        st.session_state[f"profile_analysis_{profile.id}"] = validated_analysis
        st.rerun()


def _target_editor(repository, profile, locale: str = "fr") -> None:
    """Modifie préférences partagées et champs localisés dans une carte courte."""
    english = locale == "en"
    with st.form(f"v2_edit_profile_{locale}"):
        name = st.text_input(
            "Profile name" if english else "Nom du profil", value=profile.profile_name
        )
        summary = st.text_area(
            "Professional summary" if english else "Résumé professionnel",
            value=profile.summary,
        )
        targets = st.text_input(
            "Target roles" if english else "Postes ciblés",
            value=", ".join(profile.target_job_titles),
        )
        domains = st.text_input(
            "Target sectors" if english else "Domaines ciblés",
            value=", ".join(profile.target_domains),
        )
        shared = st.columns(2)
        salary = shared[0].number_input(
            "Minimum annual gross salary · EUR"
            if english
            else "Salaire minimum annuel brut · EUR",
            min_value=0,
            value=int(profile.minimum_salary or 0),
            step=1000,
        )
        contracts = shared[1].text_input(
            "Preferred contract types" if english else "Contrats recherchés",
            value=", ".join(profile.preferred_contracts),
        )
        locations = st.text_input(
            "Preferred locations" if english else "Localisations",
            value=", ".join(profile.preferred_locations),
        )
        remote = st.text_input(
            "Remote-work preferences" if english else "Télétravail",
            value=", ".join(profile.remote_preferences),
        )
        submitted = st.form_submit_button(
            "Save this card" if english else "Enregistrer cette carte", type="primary"
        )
    if submitted:
        repository.update_profile(
            replace(
                profile,
                profile_name=name.strip() or profile.profile_name,
                summary=summary,
                target_job_titles=ensure_list(targets),
                target_domains=ensure_list(domains),
                minimum_salary=salary or None,
                preferred_contracts=ensure_list(contracts),
                preferred_locations=ensure_list(locations),
                remote_preferences=ensure_list(remote),
            )
        )
        st.rerun()


def _identity_editor(repository, profile, locale: str = "fr") -> None:
    """Conserve les coordonnées communes aux versions FR et EN."""
    english = locale == "en"
    with st.form(f"profile_identity_{profile.id}_{locale}"):
        first = st.columns(3)
        full_name = first[0].text_input(
            "Full name" if english else "Nom complet", profile.full_name
        )
        email = first[1].text_input("Email" if english else "E-mail", profile.email)
        phone = first[2].text_input("Phone" if english else "Téléphone", profile.phone)
        second = st.columns(3)
        address = second[0].text_input(
            "Address" if english else "Adresse", profile.address
        )
        postal = second[1].text_input(
            "Postcode" if english else "Code postal", profile.postal_code
        )
        city = second[2].text_input("City" if english else "Ville", profile.home_city)
        third = st.columns(3)
        linkedin = third[0].text_input("LinkedIn", profile.linkedin_url)
        github = third[1].text_input("GitHub", profile.github_url)
        portfolio = third[2].text_input("Portfolio", profile.portfolio_url)
        submitted = st.form_submit_button(
            "Save contact details" if english else "Enregistrer mes coordonnées"
        )
    if submitted:
        repository.update_profile(
            replace(
                profile,
                full_name=full_name,
                email=email,
                phone=phone,
                address=address,
                postal_code=postal,
                home_city=city,
                linkedin_url=linkedin,
                github_url=github,
                portfolio_url=portfolio,
            )
        )
        st.rerun()


def _skills_editor(repository, profile_id: int, locale: str = "fr") -> None:
    """Présente les forces compactement tout en gardant la saisie manuelle."""
    skills = repository.fetch_skills(profile_id)
    if skills:
        st.write(
            " · ".join(
                f"**{skill.get('skill_name_en') or skill['skill_name']}**"
                if locale == "en"
                else f"**{skill['skill_name']}**"
                for skill in skills
            )
        )
    with st.form(f"add_skill_{profile_id}"):
        columns = st.columns(4)
        name = columns[0].text_input(
            "New skill" if locale == "en" else "Nouvelle compétence"
        )
        category = columns[1].selectbox(
            "Category" if locale == "en" else "Catégorie", SKILL_CATEGORIES
        )
        level = columns[2].selectbox(
            "Level" if locale == "en" else "Niveau",
            ["", "beginner", "intermediate", "advanced", "expert"]
            if locale == "en"
            else SKILL_LEVELS,
        )
        core = columns[3].checkbox("Core skill" if locale == "en" else "Principale")
        submitted = st.form_submit_button("Add" if locale == "en" else "Ajouter")
    if submitted and name.strip():
        repository.add_skill(profile_id, name, category, level, is_core=core)
        st.rerun()
    if skills:
        selected = st.selectbox(
            "Remove a skill" if locale == "en" else "Retirer une compétence",
            [None, *[int(skill["id"]) for skill in skills]],
            format_func=lambda value: (
                ("Choose…" if locale == "en" else "Choisir…")
                if value is None
                else next(
                    str(skill["skill_name"])
                    for skill in skills
                    if int(skill["id"]) == value
                )
            ),
            key=f"delete_skill_select_{profile_id}",
        )
        if st.button(
            "Remove" if locale == "en" else "Retirer",
            disabled=selected is None,
            key=f"delete_skill_{profile_id}",
        ):
            repository.delete_skill(int(selected))
            st.rerun()


def _projects_editor(settings, repository, profile_id: int, locale: str = "fr") -> None:
    """Garde les preuves factuelles existantes dans un atelier secondaire."""
    path = ensure_projects_file(settings, profile_id, repository.user_id, locale)
    try:
        projects = load_profile_projects(profile_id, settings, repository, locale)
    except RockyError as error:
        projects = repository.fetch_profile_projects(profile_id, locale=locale)
        st.warning(str(error))
    content = st.text_area(
        "Projects and evidence · Markdown"
        if locale == "en"
        else "Projets et preuves · Markdown",
        path.read_text(encoding="utf-8"),
        height=260,
        key=f"projects_{profile_id}_{locale}",
    )
    if st.button(
        "Save projects" if locale == "en" else "Valider mes projets",
        key=f"save_projects_{profile_id}_{locale}",
    ):
        try:
            saved = save_profile_projects(
                profile_id, content, settings, repository, locale
            )
        except (RockyError, OSError) as error:
            st.error(str(error))
        else:
            st.success(
                f"{len(saved or projects)} project(s) available."
                if locale == "en"
                else f"{len(saved or projects)} projet(s) disponible(s)."
            )


def _pdf_preview(settings, document, label: str, locale: str = "fr") -> None:
    """Affiche un PDF privé sans exposer son chemin comme URL publique."""
    value = document.preview_pdf_path or document.source_path
    path = _resolve(settings.project_dir, value)
    if not path.is_file():
        st.warning(
            f"{label} is missing from private storage."
            if locale == "en"
            else f"{label} introuvable sur le stockage."
        )
        return
    st.markdown(f"**{label}** · {document.status}")
    # ``st.pdf`` délègue à un composant bidirectionnel : sans clé, un CV et une
    # lettre rendus dans le même parcours reçoivent le même identifiant interne.
    # L'identifiant de version du document reste unique, même après un import.
    st.pdf(str(path), height=580, key=f"profile_pdf_preview_{document.id}")
    st.download_button(
        f"Download {label}" if locale == "en" else f"Télécharger {label}",
        path.read_bytes(),
        file_name=path.name,
        key=f"download_{document.id}_{label}",
        use_container_width=True,
    )


def _document_preview_control(settings, document, label: str, locale: str) -> None:
    """Confirme le document sélectionné puis ouvre son aperçu à la demande."""
    value = document.preview_pdf_path or document.source_path
    path = _resolve(settings.project_dir, value)
    loaded = path.is_file()
    state = "Loaded" if locale == "en" else "Chargé"
    missing = "Missing" if locale == "en" else "Manquant"
    st.markdown(f"**{label}** · {state if loaded else missing} · {document.status}")
    if not loaded:
        st.warning(
            "The selected file is no longer available in private storage."
            if locale == "en"
            else "Le fichier sélectionné n'est plus disponible dans le stockage privé."
        )
        return
    toggle_key = f"profile_document_preview_{document.id}"
    opened = bool(st.session_state.get(toggle_key, False))
    if st.button(
        ("Hide preview" if opened else "Preview document")
        if locale == "en"
        else ("Masquer l'aperçu" if opened else "Aperçu du document"),
        key=f"toggle_{toggle_key}",
        use_container_width=True,
    ):
        st.session_state[toggle_key] = not opened
        st.rerun()
    if opened:
        _pdf_preview(settings, document, label, locale)


try:
    settings, repository, active_profile, _ = load_data()
except Exception as error:
    st.error("Connexion à l'espace Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

user_id = st.session_state.get("rocky_authenticated_user_id")
if user_id is None:
    st.error("La session du compte est introuvable.")
    st.stop()

profiles = repository.fetch_profiles()
if profiles.empty:
    repository.create_profile("Mon premier profil", onboarding_status="DRAFT")
    st.rerun()

profile_options = {
    int(row["id"]): str(row["profile_name"]) for _, row in profiles.iterrows()
}
default_id = int(
    st.session_state.get("selected_profile_id")
    or (active_profile.id if active_profile else next(iter(profile_options)))
)
if default_id not in profile_options:
    default_id = next(iter(profile_options))
page_locale = str(st.session_state.get(f"profile_locale_{default_id}", "fr"))
english_page = page_locale == "en"
header = st.columns([3, 1])
with header[1]:
    if st.button(
        "＋ New profile" if english_page else "＋ Nouveau profil",
        use_container_width=True,
    ):
        new_id = repository.create_profile(
            "New profile" if english_page else "Nouveau profil",
            onboarding_status="DRAFT",
        )
        st.session_state["selected_profile_id"] = new_id
        st.rerun()
selected_id = header[0].selectbox(
    "Profile" if english_page else "Profil",
    list(profile_options),
    index=list(profile_options).index(default_id),
    format_func=lambda value: profile_options[value],
)
st.session_state["selected_profile_id"] = selected_id

locale = st.radio(
    "Displayed version" if english_page else "Version affichée",
    ["fr", "en"],
    horizontal=True,
    format_func=lambda value: "🇫🇷 Français" if value == "fr" else "🇬🇧 English",
    key=f"profile_locale_{selected_id}",
)
if locale == "en":
    try:
        with st.spinner("Creating or refreshing your pre-filled English profile…"):
            _ensure_english_localization(settings, repository, selected_id)
    except RockyError as error:
        st.warning(
            "Rocky could not create the English pre-fill yet. You can retry after "
            f"checking Mistral: {error}"
        )
profile = repository.fetch_profile(selected_id, locale)
if profile is None:
    st.error("Profil introuvable ou non autorisé.")
    st.stop()

french_documents = _document_map(repository, profile.id, "fr")
english_documents = _document_map(repository, profile.id, "en")
skills = repository.fetch_skills(profile.id)
english_localization = repository.fetch_localization(profile.id, "en")
readiness = [
    {"cv", "letter"} <= set(french_documents),
    bool(profile.full_name or profile.summary or skills),
    bool(profile.target_job_titles),
    bool(profile.summary and skills),
    {"cv", "letter"} <= set(english_documents)
    and english_localization is not None
    and all(document.status == "ready" for document in english_documents.values()),
]
st.title("Profile & CV" if locale == "en" else "Profil & CV")
st.caption(
    "A complete English version of your profile and application kit."
    if locale == "en"
    else "Prépare un kit ciblé, vérifiable et disponible en français comme en anglais."
)
_journey(readiness, locale)

status_columns = st.columns([1, 1, 2])
status_columns[0].metric(
    "Status" if locale == "en" else "État",
    ("Ready" if profile.onboarding_status == "COMPLETE" else "Draft")
    if locale == "en"
    else ("Prêt" if profile.onboarding_status == "COMPLETE" else "Brouillon"),
)
status_columns[1].metric(
    "Active profile" if locale == "en" else "Profil actif",
    ("Yes" if profile.is_active else "No")
    if locale == "en"
    else ("Oui" if profile.is_active else "Non"),
)
if not profile.is_active and status_columns[2].button(
    "Activate this profile" if locale == "en" else "Activer ce profil",
    use_container_width=True,
):
    repository.set_active_profile(profile.id)
    st.rerun()
if st.button(
    "Recalculate all match scores" if locale == "en" else RECALCULATE_LABEL,
    key=f"recalculate_profile_{profile.id}",
):
    with st.spinner(
        "Recalculating complete job postings in the right language…"
        if locale == "en"
        else "Recalcul des annonces complètes dans la bonne langue…"
    ):
        result = repository.recalculate_profile_matches(profile.id)
    st.success(
        f"{result['recalculated']} score(s) updated."
        if locale == "en"
        else f"{result['recalculated']} score(s) mis à jour."
    )

if locale == "fr":
    st.subheader("1 · Pose tes documents")
    with st.container(border=True):
        _upload_card(settings, repository, int(user_id), profile.id, "fr")

    st.subheader("2 · Rocky fait l'inventaire")
    with st.container(border=True):
        _analysis_editor(settings, repository, profile, french_documents)

    st.subheader("3 · Affine ta cible")
    with st.container(border=True):
        _target_editor(repository, profile, locale)
    with st.expander("Coordonnées de candidature"):
        _identity_editor(repository, profile, locale)

    st.subheader("4 · Valide tes forces")
    with st.container(border=True):
        _skills_editor(repository, profile.id, locale)
    with st.expander("Projets et preuves"):
        _projects_editor(settings, repository, profile.id, locale)
else:
    st.subheader("1 · Upload your English documents")
    with st.container(border=True):
        _upload_card(settings, repository, int(user_id), profile.id, "en")

    st.subheader("2 · Your English profile")
    st.caption(
        "This editable version was pre-filled from your French profile. It is the "
        "version Rocky will use for English job postings."
    )
    with st.container(border=True):
        _target_editor(repository, profile, locale)

    st.subheader("3 · Contact details")
    with st.container(border=True):
        _identity_editor(repository, profile, locale)

    st.subheader("4 · Your strengths")
    with st.container(border=True):
        _skills_editor(repository, profile.id, locale)
    with st.expander("Projects and evidence"):
        _projects_editor(settings, repository, profile.id, locale)

st.subheader(
    "5 · Your English application kit" if locale == "en" else "5 · Ton kit bilingue"
)
english_document_ready = {"cv", "letter"} <= set(english_documents) and all(
    document.status == "ready" for document in english_documents.values()
)
if locale == "en" and not english_document_ready:
    st.info(
        "Upload an English CV PDF and cover-letter DOCX in step 1. No automatic "
        "translation or document generation is performed."
    )
elif locale == "en":
    st.success(
        "Your English kit is ready. Rocky automatically selects it for an English "
        "job posting; you can still correct the detected job language."
    )
elif not english_document_ready:
    st.info(
        "Pour activer le kit anglais, importe un CV PDF et une lettre DOCX anglais "
        "dans l'étape 1. Aucune traduction ou génération automatique n'est lancée."
    )
elif english_localization is None:
    st.info(
        "Tes documents anglais sont prêts. Bascule sur 🇬🇧 English puis complète "
        "le résumé, les postes et les domaines dans l'étape 3."
    )
else:
    st.success(
        "Ton kit anglais est prêt. Rocky le sélectionne automatiquement pour une "
        "annonce en anglais ; le sélecteur de langue de l'annonce permet de corriger "
        "la détection si besoin."
    )

current_documents = french_documents if locale == "fr" else english_documents
summary_columns = st.columns(4)
summary_columns[0].metric(
    "Target roles" if locale == "en" else "Postes ciblés",
    len(profile.target_job_titles),
)
summary_columns[1].metric(
    "Sectors" if locale == "en" else "Domaines", len(profile.target_domains)
)
summary_columns[2].metric(
    "Minimum salary" if locale == "en" else "Salaire minimum",
    f"{profile.minimum_salary:,.0f} €".replace(",", " ")
    if profile.minimum_salary
    else "—",
)
summary_columns[3].metric("Skills" if locale == "en" else "Compétences", len(skills))
if profile.summary:
    st.info(profile.summary)

if {"cv", "letter"} <= set(current_documents):
    previews = st.columns(2)
    with previews[0]:
        _document_preview_control(
            settings, current_documents["cv"], f"CV {locale.upper()}", locale
        )
    with previews[1]:
        _document_preview_control(
            settings,
            current_documents["letter"],
            f"Cover letter {locale.upper()}"
            if locale == "en"
            else f"Lettre {locale.upper()}",
            locale,
        )
else:
    st.warning(
        "This version does not have both ready PDF documents yet."
        if locale == "en"
        else "Cette version n'a pas encore ses deux documents PDF prêts."
    )

# Le garde et le clic sont deux decisions distinctes : fusionner
# mettrait un appel de rendu Streamlit dans une chaine booleenne.
if profile.onboarding_status != "COMPLETE":  # noqa: SIM102
    if st.button(
        "Validate and activate this profile"
        if locale == "en"
        else "Valider et activer ce profil",
        type="primary",
        disabled=not all(readiness),
        use_container_width=True,
    ):
        repository.complete_profile(profile.id, activate=True)
        st.balloons()
        st.rerun()
