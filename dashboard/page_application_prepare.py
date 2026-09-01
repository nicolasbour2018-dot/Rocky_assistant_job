"""Parcours dédié de préparation d'une candidature.

Cette page est la destination du bouton « Préparer la candidature » : elle
évite de dépendre d'un onglet conservé entre deux reruns et présente les deux
PDF, puis le préremplissage supervisé, dans un chemin linéaire.
"""

from __future__ import annotations

from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import streamlit as st

from dashboard.dashboard_common import display_date, display_score, load_data
from dashboard.job_detail_components import render_letter_workshop
from dashboard.rocky.browser_apply import (
    application_target_url,
    start_prefill,
)
from dashboard.rocky.errors import RockyError
from dashboard.rocky.models import ApplicationPackage


def _preparation_style() -> None:
    """Pose une identité visuelle dédiée, sans toucher au thème global Rocky."""
    st.markdown(
        """
        <style>
        .application-hero {
            position:relative; overflow:hidden; margin:.45rem 0 1rem; padding:1.55rem;
            border:1px solid rgba(8,181,209,.28); border-radius:26px;
            background:linear-gradient(124deg,#e1f8fb 0%,#fdfcf7 48%,#fff0e9 100%);
            box-shadow:0 14px 30px rgba(18,66,76,.08);
        }
        .application-hero:after { content:'✦'; position:absolute; right:1.6rem; top:-1.35rem;
            font-size:7rem; color:rgba(255,127,102,.24); transform:rotate(13deg); }
        .application-eyebrow { margin:0 0 .4rem; color:#087f96; font-size:.72rem;
            font-weight:850; letter-spacing:.13em; text-transform:uppercase; }
        .application-title { position:relative; z-index:1; margin:0; max-width:78%;
            color:#18212b; font-size:clamp(1.65rem,3.1vw,2.55rem); line-height:1.04; letter-spacing:-.045em; }
        .application-company { position:relative; z-index:1; margin:.45rem 0 0; color:#40505b; font-size:1rem; }
        .application-tags { position:relative; z-index:1; display:flex; flex-wrap:wrap; gap:.42rem; margin-top:1rem; }
        .application-tag { display:inline-block; padding:.34rem .64rem; border-radius:999px;
            background:rgba(255,255,255,.8); border:1px solid rgba(24,33,43,.1); color:#35505a;
            font-size:.78rem; font-weight:700; }
        .application-score { position:absolute; z-index:2; right:1.5rem; bottom:1.25rem; display:flex;
            min-width:94px; min-height:94px; align-items:center; justify-content:center; flex-direction:column;
            border:4px solid #fff; border-radius:50%; background:linear-gradient(145deg,#08b5d1,#178db2);
            color:#fff; box-shadow:0 8px 18px rgba(8,181,209,.28); }
        .application-score strong { font-size:1.35rem; line-height:1; } .application-score span { font-size:.62rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
        .preparation-journey { display:grid; grid-template-columns:repeat(3,1fr); gap:.75rem; margin:.5rem 0 1.25rem; }
        .preparation-card { position:relative; min-height:112px; padding:1rem 1rem 1rem 3.8rem;
            border:1px solid #d8e7e9; border-radius:17px; background:rgba(255,255,255,.78); box-shadow:0 5px 16px rgba(18,66,76,.035); }
        .preparation-card__number { position:absolute; top:1rem; left:1rem; width:2rem; height:2rem; display:flex; align-items:center; justify-content:center;
            border-radius:10px; background:#e4f7fa; color:#087f96; font-size:.75rem; font-weight:900; }
        .preparation-card--done .preparation-card__number { background:#dff3bd; color:#476d11; }
        .preparation-card--active { border-color:rgba(8,181,209,.55); background:linear-gradient(135deg,#fff,#ecfbfc); }
        .preparation-card strong { display:block; color:#18212b; font-size:.93rem; } .preparation-card p { margin:.26rem 0 0; color:#68747d; font-size:.78rem; line-height:1.4; }
        .preparation-section { display:flex; gap:.75rem; align-items:center; margin:1.6rem 0 .55rem; }
        .preparation-section__badge { display:flex; align-items:center; justify-content:center; width:2.05rem; height:2.05rem; flex:0 0 auto;
            border-radius:9px; background:linear-gradient(135deg,#08b5d1,#1595bc); color:#fff; font-size:.78rem; font-weight:900; }
        .preparation-section h3 { margin:0 !important; font-size:1.18rem; } .preparation-section p { margin:.1rem 0 0; color:#697782; font-size:.82rem; }
        .preparation-ready { margin:1.4rem 0 .5rem; padding:1.1rem 1.2rem; border-radius:19px; border:1px solid rgba(185,231,105,.75); background:linear-gradient(110deg,#f4ffe6,#fffdf7); }
        .preparation-ready h3 { margin:0 !important; } .preparation-ready p { margin:.28rem 0 0; color:#536238; }
        @media (max-width: 760px) { .application-hero { padding:1.2rem; } .application-title { max-width:100%; font-size:1.8rem; padding-right:.4rem; } .application-score { position:relative; right:auto; bottom:auto; margin-top:1rem; min-height:70px; min-width:70px; width:70px; } .preparation-journey { grid-template-columns:1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _journey_selector(
    job_id: int, cv_ready: bool, letter_ready: bool, files_ready: bool
) -> str:
    """Rend les cartes de progression comme des raccourcis d'atelier.

    Une carte est ici un vrai bouton Streamlit, donc utilisable au clavier et
    sur mobile. Le choix est local à l'annonce et ne modifie ni le statut de
    l'offre, ni celui de la candidature.
    """
    section_key = f"v2_prepare_active_section_{job_id}"
    active = str(st.session_state.get(section_key, "cv"))
    # Compatibilité avec les sessions ouvertes avant le renommage de la carte.
    if active == "final":
        active = "postulate"
        st.session_state[section_key] = active
    cards = (
        (
            "cv",
            "01",
            "Cibler ton CV",
            "Compétences, projets et aperçu du PDF.",
            cv_ready,
        ),
        (
            "letter",
            "02",
            "Écrire tes messages",
            "Message court et lettre de motivation.",
            letter_ready,
        ),
        (
            "postulate",
            "03",
            "Postuler",
            "Génération des PDF et préremplissage contrôlé.",
            files_ready,
        ),
    )
    columns = st.columns(3, gap="large")
    for column, (section, number, title, detail, done) in zip(
        columns, cards, strict=True
    ):
        with column, st.container(border=True):
            state = (
                "✓ PDF prêts"
                if done and section == "postulate"
                else "✓ enregistré"
                if done
                else "à préparer"
            )
            st.caption(f"{number} · {state}")
            st.markdown(f"**{title}**")
            st.caption(detail)
            if st.button(
                "Étape ouverte" if active == section else "Ouvrir cette étape",
                key=f"v2_prepare_section_{section}_{job_id}",
                type="primary" if active == section else "secondary",
                use_container_width=True,
            ):
                st.session_state[section_key] = section
                st.rerun()
    return active


def _section_heading(number: str, title: str, detail: str) -> None:
    """Affiche un jalon cohérent dans l'atelier partagé CV/lettre."""
    st.markdown(
        f'<div class="preparation-section"><span class="preparation-section__badge">{escape(number)}</span>'
        f"<div><h3>{escape(title)}</h3><p>{escape(detail)}</p></div></div>",
        unsafe_allow_html=True,
    )


def _preparation_progress(
    cv_ready: bool,
    letter_ready: bool,
    files_ready: bool,
    sent_ready: bool,
) -> None:
    """Affiche les quatre jalons sans modifier le suivi métier.

    Les trois premières validations correspondent aux cartes de préparation.
    Le quatrième jalon ne devient vert qu'après confirmation humaine de l'envoi
    sur le portail : ouvrir ou préremplir un formulaire ne suffit jamais.
    """
    completed = sum((cv_ready, letter_ready, files_ready, sent_ready))
    labels = ("CV", "lettre", "PDF", "envoi confirmé")
    next_label = labels[min(completed, len(labels) - 1)]
    with st.container(border=True):
        st.markdown("**Avancement de la préparation**")
        st.progress(
            completed / 4,
            text=f"{completed}/4 jalons validés · prochaine étape : {next_label}",
        )
        st.caption(
            "Le dernier jalon est volontairement manuel : Rocky ne déclare jamais "
            "une candidature envoyée à la place de l’utilisateur."
        )


def _package_from_saved_application(
    application: dict[str, Any] | None, project_dir: Path
) -> ApplicationPackage | None:
    """Rouvre un dossier PDF versionné après un redémarrage Streamlit."""
    if not application:
        return None
    cv_value = str(application.get("cv_path") or "").strip()
    letter_value = str(application.get("letter_pdf_path") or "").strip()
    if not cv_value or not letter_value:
        return None
    cv_path = Path(cv_value)
    letter_path = Path(letter_value)
    if not cv_path.is_absolute():
        cv_path = project_dir / cv_path
    if not letter_path.is_absolute():
        letter_path = project_dir / letter_path
    return ApplicationPackage(
        directory=str(cv_path.parent),
        cv_pdf_path=str(cv_path),
        letter_pdf_path=str(letter_path),
        application_id=int(application["id"]),
    )


_preparation_style()

job_id = st.session_state.get("selected_job_id")
if not job_id:
    st.info("Ouvre d'abord une annonce depuis le cockpit.")
    if st.button("Retour au cockpit", type="primary"):
        st.switch_page("dashboard_b.py")
    st.stop()

try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

offer = repository.fetch_job_offer(int(job_id))
if offer is None:
    st.error("Cette annonce n'existe plus dans Rocky.")
    st.stop()

language_options = ["auto", "fr", "en"]
current_language = offer.language_override or "auto"
detected_label = (offer.detected_language or "fr").upper()
selected_language = st.selectbox(
    "Langue du dossier",
    language_options,
    index=language_options.index(
        current_language if current_language in language_options else "auto"
    ),
    format_func=lambda value: {
        "auto": f"Automatique · {detected_label}",
        "fr": "Français",
        "en": "English",
    }[value],
    key=f"application_language_{job_id}",
)
if selected_language != current_language:
    repository.set_job_language(
        int(job_id), None if selected_language == "auto" else selected_language
    )
    if profile:
        repository.recalculate_job_match(int(job_id), profile.id)
    st.rerun()
if profile:
    profile = repository.profile_for_offer(profile.id, offer) or profile
    localized_documents = {
        document.kind: document
        for document in repository.fetch_profile_documents(profile.id, profile.locale)
    }
    cv_document = localized_documents.get("cv")
    if cv_document:
        profile = replace(profile, cv_path=cv_document.source_path)
    if profile.locale == "en" and (
        {"cv", "letter"} - set(localized_documents)
        or any(document.status != "ready" for document in localized_documents.values())
    ):
        st.warning(
            "Le matching anglais reste visible, mais actualise les deux documents "
            "anglais dans Profil & CV avant la génération finale."
        )

# Les widgets de l'atelier peuvent avoir été renseignés lors d'un rerun : le
# bandeau restitue alors immédiatement l'avancement sans créer de nouvel état.
selected = jobs[jobs.get("id") == int(job_id)] if not jobs.empty else jobs
match_score = selected.iloc[0].get("match_score") if not selected.empty else None
cv_ready = bool(st.session_state.get(f"v2_prepare_cv_saved_{int(job_id)}"))
letter_ready = bool(st.session_state.get(f"v2_prepare_letter_saved_{int(job_id)}"))
latest_application = (
    repository.fetch_latest_application_for_job(int(job_id), profile.id)
    if profile
    else None
)
package_key = f"v2_files_{int(job_id)}"
known_package = st.session_state.get(package_key) or _package_from_saved_application(
    latest_application, settings.project_dir
)
files_ready = known_package is not None
application_status = str((latest_application or {}).get("status") or "")
sent_ready = application_status not in {"", "DOSSIER PRÉPARÉ", "PRÊTE À ENVOYER"}
score_label = display_score(match_score)
metadata = [
    offer.source_name or "Source Rocky",
    offer.city or "Localisation à préciser",
    offer.contract_type or "Contrat à préciser",
]
st.markdown(
    '<section class="application-hero">'
    '<p class="application-eyebrow">Dossier de candidature · prêt à composer</p>'
    f'<h1 class="application-title">{escape(offer.job_title or "Poste sans titre")}</h1>'
    f'<p class="application-company">{escape(offer.company_name or "Entreprise inconnue")} · publiée {escape(display_date(offer.publication_date))}</p>'
    '<div class="application-tags">'
    + "".join(
        f'<span class="application-tag">{escape(str(value))}</span>'
        for value in metadata
    )
    + "</div>"
    f'<div class="application-score"><strong>{escape(score_label)}</strong><span>score Rocky</span></div>'
    "</section>",
    unsafe_allow_html=True,
)

back, destination, profile_card = st.columns([1, 1.35, 1])
if back.button("← Retour à l'annonce", use_container_width=True):
    st.switch_page("page_job_detail.py")
application_url = offer.application_url or offer.source_url
if application_url:
    destination.link_button(
        "Voir le site de candidature",
        application_url,
        use_container_width=True,
    )
profile_card.caption(
    f"Profil utilisé : **{profile.profile_name if profile else 'à sélectionner'}**"
)

_preparation_progress(cv_ready, letter_ready, files_ready, sent_ready)

active_section = _journey_selector(int(job_id), cv_ready, letter_ready, files_ready)

section_details = {
    "cv": (
        "01",
        "Ton CV ciblé",
        "Ajuste les compétences et projets autorisés, puis valide l’aperçu.",
    ),
    "letter": (
        "02",
        "Tes messages",
        "Prépare le message d’accompagnement et la lettre de motivation.",
    ),
    "postulate": (
        "03",
        "Postuler",
        "Génère les PDF à partir des étapes enregistrées, puis ouvre le formulaire sans soumettre.",
    ),
}
_section_heading(*section_details[active_section])

render_letter_workshop(
    int(job_id), offer, settings, repository, profile, active_section=active_section
)

# Le générateur conserve le package dans la session : proposer immédiatement
# le dossier dans la page Candidatures évite de faire chercher son identifiant.
package = st.session_state.get(package_key) or known_package
if package and active_section == "postulate":
    st.divider()
    st.markdown(
        '<div class="preparation-ready"><h3>✨ Les deux PDF sont prêts</h3>'
        "<p>Dernière étape : préremplir le formulaire, le relire puis envoyer toi-même la candidature.</p></div>",
        unsafe_allow_html=True,
    )
    try:
        target_url = application_target_url(int(package.application_id), repository)
    except RockyError as error:
        target_url = ""
        st.error(str(error))
    target_domain = urlsplit(target_url).netloc or "site destinataire inconnu"
    st.markdown(f"### 🚀 Postuler chez {offer.company_name or 'l’entreprise'}")
    st.caption(
        f"Destination : **{target_domain}**. Playwright ouvre Chromium sur ce "
        "Mac, préremplit les champs reconnus et te laisse la main avant tout envoi."
    )
    consent = st.checkbox(
        "Je confirme les données et les deux PDF transmis au formulaire.",
        key=f"prepare_prefill_consent_{int(package.application_id)}",
    )
    postulate, details = st.columns([2, 1])
    with postulate:
        if st.button(
            "🚀 Préremplir avec Playwright",
            type="primary",
            use_container_width=True,
            disabled=not consent or not target_url,
            key=f"prepare_start_prefill_{int(package.application_id)}",
        ):
            try:
                start_prefill(
                    int(package.application_id),
                    settings,
                    repository,
                    confirmed=True,
                )
            except (RockyError, PermissionError) as error:
                st.error(str(error))
            else:
                st.success(
                    "Chromium démarre avec le dossier prérempli. Relis tout avant d’envoyer."
                )
    with details:
        if st.button(
            "Voir le dossier",
            use_container_width=True,
            key=f"prepare_view_application_{int(package.application_id)}",
        ):
            st.session_state["focus_application_id"] = int(package.application_id)
            st.switch_page("page_applications.py")

    current_application = repository.fetch_application(int(package.application_id))
    current_status = str((current_application or {}).get("status") or "")
    already_sent = current_status not in {
        "",
        "DOSSIER PRÉPARÉ",
        "PRÊTE À ENVOYER",
    }
    st.divider()
    if already_sent:
        st.success(
            "Préparation clôturée : cette candidature est déjà suivie comme envoyée."
        )
    else:
        st.markdown("#### ✅ Confirmer l’envoi réel")
        st.caption(
            "À utiliser seulement après avoir toi-même cliqué sur « Envoyer » sur le site. "
            "Rocky passera alors la candidature et l’annonce à « CANDIDATURE ENVOYÉE »."
        )
        sent_confirm = st.checkbox(
            "Je confirme que la candidature a été effectivement envoyée.",
            key=f"prepare_sent_confirm_{int(package.application_id)}",
        )
        if st.button(
            "✅ C’est envoyé · clôturer la préparation",
            type="primary",
            use_container_width=True,
            disabled=not sent_confirm,
            key=f"prepare_mark_sent_{int(package.application_id)}",
        ):
            try:
                repository.update_application_status(
                    int(package.application_id),
                    "CANDIDATURE ENVOYÉE",
                    source="USER_CONFIRMATION",
                    details={"confirmed_from": "application_preparation"},
                )
                st.success(
                    "Candidature enregistrée comme envoyée ; le statut de l’annonce est synchronisé."
                )
                st.rerun()
            except (ValueError, KeyError) as error:
                st.error(f"Impossible de clôturer la préparation : {error}")
