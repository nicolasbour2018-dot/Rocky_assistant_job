"""Espace de suivi des candidatures Rocky.

La page permet de piloter les dossiers, documents et réponses Gmail associés à
un profil. Elle expose les décisions à valider et leur audit, sans jamais
envoyer de candidature ni modifier la boîte Gmail distante.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_data
from dashboard.rocky.application_filters import PIPELINE_SEGMENTS, filter_applications
from dashboard.rocky.application_statuses import APPLICATION_STATUS_OPTIONS
from dashboard.rocky.browser_apply import (
    application_target_url,
    start_prefill,
)
from dashboard.rocky.errors import RockyError
from dashboard.rocky.gmail_service import GmailService

EMAIL_STATUS = {
    "REFUSAL": "REFUS",
    "INTERVIEW": "ENTRETIEN",
    "TECHNICAL_TEST": "TEST TECHNIQUE",
    "OFFER": "OFFRE",
    "ACKNOWLEDGEMENT": "ACCUSÉ DE RÉCEPTION",
    "IN_PROGRESS": "EN COURS",
}

EMAIL_LABELS = {
    **EMAIL_STATUS,
    "APPLICATION_UPDATE": "Mise à jour de candidature",
    "JOB_ALERT": "Alerte emploi",
    "NOISE": "Notification classée automatiquement",
}

EMAIL_TABLE_LABELS = {
    **EMAIL_LABELS,
    "APPLICATION_UPDATE": "Mise à jour",
    "NOISE": "Notification",
}

# Les états sont conservés tels quels en base pour l'audit, mais l'historique
# doit expliciter qu'un e-mail classé comme alerte n'attend plus une action.
EMAIL_PROCESSING_LABELS = {
    "CLASSIFIED": "Alerte emploi classée",
}

CAROUSEL_CARDS_PER_VIEW = 3


def _display_date(value: Any) -> str:
    """Affiche une date courte et stable, sans erreur sur les valeurs vides."""
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%d/%m/%Y") if pd.notna(parsed) else "—"


def _mailbox_label(value: object) -> str:
    """Raccourcit l'adresse dans les tableaux tout en gardant le détail complet."""
    address = str(value or "historique")
    return address.split("@", 1)[0]


def _short_label(value: object, limit: int) -> str:
    """Tronque les libellés des cartes sans couper un mot en plein milieu."""
    label = " ".join(str(value or "").split()) or "—"
    if len(label) <= limit:
        return label
    return label[: limit - 1].rsplit(" ", 1)[0].rstrip(" —-") + "…"


def _carousel_page(items: pd.DataFrame, *, state_key: str, label: str) -> pd.DataFrame:
    """Rend les flèches d'un carrousel et retourne ses cartes visibles.

    Trois cartes sont visibles à la fois afin que l'interface garde une vraie
    navigation latérale, y compris dans Streamlit 1.51 où un conteneur
    horizontal peut se comporter comme une simple rangée.
    """
    total = len(items)
    maximum_start = max(0, total - CAROUSEL_CARDS_PER_VIEW)
    current_start = min(max(0, int(st.session_state.get(state_key, 0))), maximum_start)
    controls = st.columns([1, 4, 1])
    if controls[0].button(
        "←", key=f"{state_key}_previous", disabled=current_start == 0
    ):
        st.session_state[state_key] = max(0, current_start - 1)
        st.rerun()
    end = min(total, current_start + CAROUSEL_CARDS_PER_VIEW)
    controls[1].caption(
        f"{label} {current_start + 1}–{end} sur {total} · utilise les flèches pour défiler"
    )
    if controls[2].button(
        "→", key=f"{state_key}_next", disabled=current_start >= maximum_start
    ):
        st.session_state[state_key] = min(maximum_start, current_start + 1)
        st.rerun()
    return items.iloc[current_start:end]


def _render_application_carousel(applications: pd.DataFrame) -> None:
    """Rend le carrousel visible des candidatures, avec le détail dessous."""
    selected_application_id = st.session_state.get("selected_application_id")
    page = _carousel_page(
        applications,
        state_key="applications_carousel_start",
        label="Candidatures",
    )
    columns = st.columns(CAROUSEL_CARDS_PER_VIEW, gap="small")
    for column, (_, application) in zip(columns, page.iterrows(), strict=False):
        application_id = int(application["id"])
        is_selected = application_id == int(selected_application_id or -1)
        with column.container(border=True, height=240):
            st.caption(
                f"#{application_id} · {_display_date(application.get('prepared_at'))}"
            )
            st.markdown(f"**{_short_label(application.get('company_name'), 34)}**")
            st.write(_short_label(application.get("job_title"), 58))
            score = application.get("match_score")
            score_label = f"{float(score):.0f} %" if pd.notna(score) else "—"
            st.caption(f"{application.get('status') or '—'} · score {score_label}")
            if st.button(
                "Dossier ouvert" if is_selected else "Voir le dossier",
                key=f"select_application_{application_id}",
                type="primary" if is_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state["selected_application_id"] = application_id
                st.rerun()


def _render_pending_email_carousel(emails: pd.DataFrame) -> None:
    """Rend le carrousel visible de la file Gmail, avec le détail dessous."""
    selected_email_id = st.session_state.get("selected_email_id")
    page = _carousel_page(
        emails,
        state_key="pending_email_carousel_start",
        label="E-mails",
    )
    columns = st.columns(CAROUSEL_CARDS_PER_VIEW, gap="small")
    for column, (_, email) in zip(columns, page.iterrows(), strict=False):
        email_id = int(email["id"])
        is_selected = email_id == int(selected_email_id or -1)
        with column.container(border=True, height=240):
            st.caption(
                f"{_display_date(email.get('received_at'))} · "
                f"boîte {_mailbox_label(email.get('gmail_account'))}"
            )
            st.markdown(f"**{_short_label(email.get('sender'), 38)}**")
            st.write(_short_label(email.get("subject"), 62))
            classification = EMAIL_TABLE_LABELS.get(
                str(email.get("classification")), email.get("classification")
            )
            confidence = float(email.get("confidence") or 0)
            st.caption(f"{classification} · confiance {confidence:.0%}")
            if st.button(
                "E-mail ouvert" if is_selected else "Voir l'e-mail",
                key=f"select_pending_email_{email_id}",
                type="primary" if is_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state["selected_email_id"] = email_id
                st.rerun()


def _keep_pending_email_queue_open() -> None:
    """Prépare le rerun d'une décision sans quitter la file Gmail.

    Les callbacks Streamlit s'exécutent avant le rendu des widgets. C'est le
    moment sûr pour remettre à jour la section pilotée par
    ``applications_active_section`` ; le faire après son affichage provoquerait
    une erreur de mutation de widget ou un retour au tableau des candidatures.
    L'e-mail sélectionné ne doit surtout pas être effacé ici : les callbacks
    s'exécutent avant le corps du script, donc l'action de classement ou de
    validation ne serait jamais atteinte. Les actions terminales le ferment
    seulement après leur écriture en base.
    """
    st.session_state["applications_active_section"] = "emails"


def _save_application_status_from_widget(repository, application_id: int) -> None:
    """Persiste le statut dès son choix dans le sélecteur du dossier.

    Le callback Streamlit s'exécute avant le chargement de la liste des
    candidatures : la carte et le détail sont donc relus avec le nouveau statut
    pendant le même rerun, sans demander un second clic à l'utilisateur.
    """
    state_key = f"application_status_{application_id}"
    selected_status = st.session_state.get(state_key)
    if selected_status not in APPLICATION_STATUS_OPTIONS:
        return
    repository.update_application_status(application_id, str(selected_status))
    st.session_state["application_status_saved_id"] = application_id


def _path(value: object, project_dir: Path) -> Path:
    """Résout un chemin de document stocké, absolu ou relatif au projet Rocky."""
    path = Path(str(value or "")).expanduser()
    return path if path.is_absolute() else project_dir / path


def _render_application_detail(application, settings, repository) -> None:
    """Rend un seul dossier actif dans trois sous-vues courtes."""
    application_id = int(application["id"])
    heading, close_column = st.columns([6, 1])
    heading.markdown(f"### {application['company_name']} — {application['job_title']}")
    if close_column.button(
        "Fermer", key=f"close_application_{application_id}", use_container_width=True
    ):
        st.session_state.pop("selected_application_id", None)
        st.rerun()
    heading.caption(
        f"Dossier #{application_id} · préparé le "
        f"{_display_date(application.get('prepared_at'))}"
    )

    follow_up_tab, documents_tab, timeline_tab = st.tabs(
        ["Suivi", "Documents & ouverture", "Chronologie"]
    )
    with follow_up_tab:
        top = st.columns([2, 1, 1])
        top[0].selectbox(
            "Statut",
            APPLICATION_STATUS_OPTIONS,
            index=(
                APPLICATION_STATUS_OPTIONS.index(str(application["status"]))
                if str(application["status"]) in APPLICATION_STATUS_OPTIONS
                else 0
            ),
            key=f"application_status_{application_id}",
            on_change=_save_application_status_from_widget,
            args=(repository, application_id),
        )
        top[1].metric(
            "Score",
            f"{float(application['match_score']):.0f} %"
            if pd.notna(application.get("match_score"))
            else "—",
        )
        if st.session_state.pop("application_status_saved_id", None) == application_id:
            top[2].success("Statut enregistré")
        else:
            top[2].caption("Enregistrement automatique")

        with st.form(f"application_note_form_{application_id}"):
            note = st.text_area(
                "Ajouter une note",
                height=80,
                placeholder="Relance, interlocuteur, prochaine action…",
            )
            save_note = st.form_submit_button("Ajouter à l’historique")
        if save_note and note.strip():
            repository.add_application_note(application_id, note)
            st.rerun()
        if str(application.get("notes") or "").strip():
            st.info(str(application["notes"]))

    with documents_tab:
        documents = repository.fetch_application_documents(application_id)
        if documents.empty:
            st.caption(
                "Dossier historique : les chemins existants restent disponibles."
            )
            current_documents = [
                ("CV", application.get("cv_path")),
                ("Lettre", application.get("letter_pdf_path")),
            ]
        else:
            current_documents = [
                (str(row["kind"]), row["path"])
                for _, row in documents[documents["is_current"].astype(bool)].iterrows()
            ]
        download_columns = st.columns(max(1, len(current_documents)))
        for column, (kind, value) in zip(
            download_columns, current_documents, strict=False
        ):
            path = _path(value, settings.project_dir)
            if path.is_file():
                column.download_button(
                    f"Télécharger {kind}",
                    path.read_bytes(),
                    file_name=path.name,
                    key=f"download_application_{application_id}_{kind}_{path.name}",
                    use_container_width=True,
                )

        try:
            target_url = application_target_url(application_id, repository)
        except RockyError as error:
            target_url = ""
            st.error(str(error))
        domain = urlsplit(target_url).netloc or "site inconnu"
        st.caption(
            f"Destination : {domain}. Playwright ouvre Chromium et préremplit "
            "les champs reconnus ; Rocky ne soumet jamais le formulaire."
        )
        consent = st.checkbox(
            "Je confirme les données et les deux PDF transmis au formulaire.",
            key=f"prefill_consent_{application_id}",
        )
        if st.button(
            "Préremplir avec Playwright",
            disabled=not consent or not target_url,
            type="primary",
            use_container_width=True,
            key=f"start_prefill_{application_id}",
        ):
            try:
                start_prefill(
                    application_id,
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
        sessions = repository.fetch_browser_sessions(application_id)
        if not sessions.empty:
            latest = sessions.iloc[0]
            st.caption(
                f"Dernière ouverture : {latest['status']} · {latest['updated_at']}"
            )

    with timeline_tab:
        events = repository.fetch_application_events(application_id)
        if events.empty:
            st.caption("Aucun événement historisé.")
        else:
            for index, event in events.head(10).iterrows():
                reverted = " · annulé" if pd.notna(event.get("reverted_at")) else ""
                st.caption(
                    f"{event['created_at']} · {event['source']} · "
                    f"{event.get('old_status') or '—'} → "
                    f"{event.get('new_status') or event['event_type']}{reverted}"
                )
                # Le garde et le clic sont deux decisions distinctes : fusionner
                # mettrait un appel de rendu Streamlit dans une chaine booleenne.
                if (  # noqa: SIM102
                    index == events.index[0]
                    and event["event_type"] == "STATUS_CHANGED"
                    and pd.isna(event.get("reverted_at"))
                    and event["source"] != "UNDO"
                ):
                    if st.button(
                        "Annuler ce changement",
                        key=f"undo_application_event_{int(event['id'])}",
                    ) and repository.revert_application_event(int(event["id"])):
                        st.rerun()


def _render_email_detail(email, applications, repository) -> None:
    """Affiche uniquement l'e-mail sélectionné et ses décisions possibles."""
    email_id = int(email["id"])
    heading, close_column = st.columns([6, 1])
    heading.markdown(f"### {email.get('subject') or '(sans objet)'}")
    if close_column.button(
        "Fermer",
        key=f"close_email_{email_id}",
        on_click=_keep_pending_email_queue_open,
        use_container_width=True,
    ):
        st.session_state.pop("selected_email_id", None)
        st.rerun()
    heading.caption(
        f"{email.get('sender') or 'Expéditeur inconnu'} · boîte "
        f"{email.get('gmail_account') or 'historique'} · "
        f"{EMAIL_LABELS.get(str(email.get('classification')), email.get('classification'))} "
        f"· confiance {float(email.get('confidence') or 0):.0%}"
    )
    if pd.notna(email.get("matched_application_id")):
        st.caption(
            f"Candidature rapprochée : {email.get('company_name')} — "
            f"{email.get('job_title')}"
        )
    st.write(email.get("snippet") or "Aucun aperçu.")
    st.caption(f"Pourquoi : {email.get('reason') or 'Aucune précision'}")
    gmail_url = _gmail_message_url(email)
    if gmail_url:
        st.link_button("Ouvrir dans Gmail", gmail_url)

    st.caption("Corriger le classement si nécessaire")
    classification_actions = st.columns(3)
    if classification_actions[0].button(
        "Ignorer",
        key=f"classify_noise_{email_id}",
        on_click=_keep_pending_email_queue_open,
        help="Classe ce message comme sans lien avec une candidature ou une offre.",
        use_container_width=True,
    ):
        repository.manually_classify_email(
            email_id,
            classification="NOISE",
            confidence=0.99,
            processing_state="IGNORED",
            reason="Classement manuel : message sans lien emploi",
            clear_application=True,
        )
        st.session_state.pop("selected_email_id", None)
        st.rerun()
    if classification_actions[1].button(
        "Retour candidature",
        key=f"classify_application_update_{email_id}",
        on_click=_keep_pending_email_queue_open,
        help=(
            "Le conserve dans la file pour l'associer à un dossier et "
            "valider un statut."
        ),
        use_container_width=True,
    ):
        repository.manually_classify_email(
            email_id,
            classification="APPLICATION_UPDATE",
            confidence=0.78,
            processing_state="REVIEW",
            reason="Classement manuel : retour de candidature à interpréter",
            clear_application=False,
        )
        st.rerun()
    if classification_actions[2].button(
        "Alerte d'offres",
        key=f"reclassify_job_alert_{email_id}",
        on_click=_keep_pending_email_queue_open,
        help="Classe l'e-mail comme alerte d'offres et termine sa vérification.",
        use_container_width=True,
    ):
        repository.reclassify_email_as_job_alert(
            email_id, "Classement manuel : alerte d'offres"
        )
        st.session_state.pop("selected_email_id", None)
        st.rerun()

    application_options = {
        f"#{int(row['id'])} · {row['company_name']} — {row['job_title']}": int(
            row["id"]
        )
        for _, row in applications.iterrows()
    }
    proposed = EMAIL_STATUS.get(str(email.get("classification")))
    selected_application = (
        int(email["matched_application_id"])
        if pd.notna(email.get("matched_application_id"))
        else None
    )
    if (
        (proposed or str(email.get("classification")) == "APPLICATION_UPDATE")
        and selected_application is None
        and application_options
    ):
        application_query = (
            st.text_input(
                "Rechercher une candidature",
                placeholder="Entreprise, poste ou #dossier",
                key=f"email_application_query_{email_id}",
            )
            .strip()
            .lower()
        )
        filtered_application_options = {
            label: application_id
            for label, application_id in application_options.items()
            if not application_query or application_query in label.lower()
        }
        if not filtered_application_options:
            st.warning("Aucune candidature ne correspond à cette recherche.")
        selected_label = st.selectbox(
            "Associer à une candidature avant validation",
            ["— Choisir une candidature —", *filtered_application_options],
            key=f"email_application_{email_id}",
        )
        selected_application = filtered_application_options.get(selected_label)
    manual_status = None
    if proposed is None and str(email.get("classification")) == "APPLICATION_UPDATE":
        manual_status = st.selectbox(
            "Décision à enregistrer (optionnel)",
            ["— Ne pas changer le statut —", *APPLICATION_STATUS_OPTIONS[2:]],
            key=f"email_status_{email_id}",
        )
        manual_status = None if manual_status.startswith("—") else manual_status
    effective_status = proposed or manual_status
    # Le garde et le clic sont deux decisions distinctes : fusionner
    # mettrait un appel de rendu Streamlit dans une chaine booleenne.
    if effective_status and selected_application is not None:  # noqa: SIM102
        if st.button(
            f"Valider → {effective_status}",
            key=f"approve_email_{email_id}",
            on_click=_keep_pending_email_queue_open,
            type="primary",
            use_container_width=True,
        ):
            repository.update_application_status(
                selected_application,
                effective_status,
                source="GMAIL_CONFIRMED",
                confidence=float(email.get("confidence") or 0),
                details={
                    "email_message_id": email_id,
                    "gmail_account": email.get("gmail_account"),
                },
            )
            repository.resolve_email_message(
                email_id, "APPROVED", application_id=selected_application
            )
            st.session_state.pop("selected_email_id", None)
            st.rerun()


def _render_history_email_detail(email, repository) -> None:
    """Affiche le détail d'audit et permet de rouvrir un rejet automatique."""
    email_id = int(email["id"])
    st.markdown(f"#### {email.get('subject') or '(sans objet)'}")
    st.caption(
        f"{email.get('sender') or 'Expéditeur inconnu'} · "
        f"boîte {email.get('gmail_account') or 'historique'} · "
        f"{EMAIL_LABELS.get(str(email.get('classification')), email.get('classification'))} · "
        f"{email.get('processing_state') or 'état inconnu'}"
    )
    st.write(email.get("snippet") or "Aucun aperçu conservé pour ce message.")
    st.caption(f"Pourquoi : {email.get('reason') or 'Aucune précision'}")
    if pd.notna(email.get("matched_application_id")):
        st.caption(
            f"Candidature rapprochée : {email.get('company_name')} — "
            f"{email.get('job_title')}"
        )
    gmail_url = _gmail_message_url(email)
    if gmail_url:
        st.link_button("Ouvrir dans Gmail", gmail_url)
    # Le garde et le clic sont deux decisions distinctes : fusionner
    # mettrait un appel de rendu Streamlit dans une chaine booleenne.
    if str(email.get("processing_state")) == "AUTO_IGNORED":  # noqa: SIM102
        if st.button(
            "Requalifier ce mail",
            key=f"reopen_auto_ignored_email_{email_id}",
            on_click=_keep_pending_email_queue_open,
            help=(
                "Remet ce message dans la file des e-mails à vérifier "
                "sans modifier Gmail."
            ),
            type="primary",
        ):
            repository.reopen_auto_ignored_email(
                email_id,
                "Réouverture manuelle : message à requalifier",
            )
            st.session_state["selected_email_id"] = email_id
            st.session_state.pop("selected_history_email_id", None)
            st.rerun()


def _gmail_message_url(email) -> str:
    """Construit un lien Gmail sans exposer de données si l'identifiant manque."""
    thread_id = str(email.get("gmail_thread_id") or email.get("gmail_message_id") or "")
    account = str(email.get("gmail_account") or "")
    if not thread_id or not account:
        return ""
    return (
        "https://mail.google.com/mail/u/?authuser="
        f"{quote(account, safe='')}#all/{quote(thread_id, safe='')}"
    )


def _render_gmail_sync_action(settings, repository, profile) -> None:
    """Rend la synchronisation multi-boîtes au plus près de la file à traiter.

    Le bouton lit uniquement les boîtes déjà autorisées. Chaque résultat est
    conservé une seule exécution dans ``session_state`` afin de recharger la
    table avec les nouveaux messages sans perdre le compte rendu utilisateur.
    """
    services = [
        GmailService(settings, repository, profile, account_email)
        for account_email in settings.gmail_accounts
    ]
    authorized_services = [service for service in services if service.is_authorized]
    unauthorized_accounts = [
        service.account_email for service in services if not service.is_authorized
    ]

    sync_results = st.session_state.pop("applications_gmail_sync_results", None)
    if isinstance(sync_results, list):
        st.success("Synchronisation Gmail terminée.")
        for result in sync_results:
            if not isinstance(result, dict):
                continue
            account = str(result.get("account") or "Boîte Gmail")
            error = result.get("error")
            if error:
                st.warning(f"{account} : {error}")
                continue
            # ``summary.review`` est le nombre de messages rencontrés pendant
            # ce scan. Il ne décrit pas forcément la file après les règles de
            # classement ; on relit donc l'état persistant affiché à l'écran.
            pending_now = len(repository.fetch_pending_email_messages(account))
            st.caption(
                f"{account} · {result.get('inserted', 0)} ajouté(s) · "
                f"{result.get('auto_applied', 0)} statut(s) mis à jour · "
                f"{pending_now} actuellement à vérifier"
            )
            error_count = int(result.get("error_count", 0) or 0)
            if error_count:
                st.warning(
                    f"{account} : synchronisation partielle, {error_count} "
                    "message(s) n'ont pas été enregistrés. Réessaie après "
                    "avoir vérifié le diagnostic technique."
                )

    actions, state = st.columns([1.4, 2.6])
    if actions.button(
        "Synchroniser les boîtes Gmail",
        key="applications_sync_gmail",
        type="primary",
        disabled=not authorized_services,
        use_container_width=True,
    ):
        results: list[dict[str, object]] = []
        with st.spinner("Lecture et classement des e-mails Gmail…"):
            for service in authorized_services:
                try:
                    summary = service.sync_gmail()
                    results.append(
                        {
                            "account": service.account_email,
                            "inserted": summary.inserted,
                            "auto_applied": summary.auto_applied,
                            "error_count": len(summary.errors),
                        }
                    )
                except Exception as error:
                    # Une boîte en erreur ne doit pas empêcher la lecture des
                    # autres comptes configurés sur le même cockpit.
                    results.append(
                        {
                            "account": service.account_email,
                            "error": type(error).__name__,
                        }
                    )
        st.session_state["applications_gmail_sync_results"] = results
        st.rerun()

    if authorized_services:
        state.caption(
            f"{len(authorized_services)} boîte(s) autorisée(s) seront lues en "
            "lecture seule."
        )
    else:
        state.caption("Autorise au moins une boîte Gmail depuis Monitoring.")
    if unauthorized_accounts:
        state.caption(
            "Non autorisée(s) et ignorée(s) : " + ", ".join(unauthorized_accounts)
        )


st.markdown('<div class="rocky-kicker">Pilotage</div>', unsafe_allow_html=True)
st.title("Candidatures")
st.caption("Documents, étapes, réponses Gmail et préremplissage Playwright supervisé.")

try:
    settings, repository, profile, _ = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

if profile is None:
    st.info("Active un profil pour afficher ses candidatures.")
    st.stop()

applications = repository.fetch_applications(profile.id)
pending = repository.fetch_pending_email_messages()
history = repository.fetch_email_messages(limit=100)

metrics = st.columns(6)
metrics[0].metric("Dossiers", len(applications))
metrics[1].metric(
    "Envoyées",
    int(applications["status"].isin(APPLICATION_STATUS_OPTIONS[2:]).sum())
    if not applications.empty
    else 0,
)
metrics[2].metric(
    "Entretiens",
    int(applications["status"].isin(["ENTRETIEN", "TEST TECHNIQUE"]).sum())
    if not applications.empty
    else 0,
)
metrics[3].metric(
    "Offres",
    int((applications["status"] == "OFFRE").sum()) if not applications.empty else 0,
)
metrics[4].metric(
    "Refus",
    int((applications["status"] == "REFUS").sum()) if not applications.empty else 0,
)
metrics[5].metric("E-mails", len(pending), help="Messages à vérifier")

section_options = ["applications", "emails"]
section_labels = {
    "applications": f"Candidatures · {len(applications)}",
    "emails": f"E-mails à vérifier · {len(pending)}",
}
# Les anciennes versions stockaient le compteur dans la valeur du widget. On
# le normalise une fois pour éviter de perdre la section active au prochain
# rerun lorsque le nombre de messages change.
previous_section = st.session_state.get("applications_active_section")
if isinstance(previous_section, str):
    if previous_section.startswith("E-mails à vérifier"):
        st.session_state["applications_active_section"] = "emails"
    elif previous_section.startswith("Candidatures"):
        st.session_state["applications_active_section"] = "applications"
active_section = st.segmented_control(
    "Section",
    section_options,
    format_func=lambda value: section_labels.get(value, value),
    default=section_options[0],
    key="applications_active_section",
    label_visibility="collapsed",
    # La largeur de contenu conserve l'aspect léger d'onglets au lieu de
    # transformer les deux sections en grands panneaux verticaux.
    width="content",
)

if active_section == "applications":
    filters = st.columns([1.1, 1.55, 2.0, 1.15, 1.25])
    segment = filters[0].selectbox(
        "Vue",
        list(PIPELINE_SEGMENTS),
        key="applications_segment_filter",
    )
    selected_statuses = filters[1].multiselect(
        "Statuts",
        APPLICATION_STATUS_OPTIONS,
        placeholder="Tous",
        key="applications_status_filter",
    )
    query = filters[2].text_input(
        "Rechercher",
        placeholder="Entreprise ou poste",
        key="applications_query_filter",
    )
    minimum_score = filters[3].slider(
        "Seuil de score",
        min_value=0,
        max_value=100,
        value=0,
        step=5,
        key="applications_score_filter",
        help="À 0 %, tous les dossiers restent visibles, y compris sans score.",
    )
    sort_order = filters[4].selectbox(
        "Trier",
        ["Plus récentes", "Étape du parcours", "Meilleur score", "Entreprise"],
        key="applications_sort_filter",
    )
    visible = filter_applications(
        applications,
        segment=segment,
        statuses=list(selected_statuses),
        query=query,
        minimum_score=int(minimum_score),
        sort_order=sort_order,
    )
    st.caption(
        f"{len(visible)} dossier(s) · fais défiler les cartes latéralement puis "
        "ouvre le dossier qui t'intéresse."
    )
    if visible.empty:
        st.info("Aucune candidature ne correspond à ces filtres.")
    else:
        focus_application_id = st.session_state.pop("focus_application_id", None)
        if focus_application_id is not None:
            st.session_state["selected_application_id"] = int(focus_application_id)
        _render_application_carousel(visible)
        selected_application_id = st.session_state.get("selected_application_id")
        selected_application = visible[
            visible["id"].astype(int) == int(selected_application_id or -1)
        ]
        if not selected_application.empty:
            with st.container(border=True):
                _render_application_detail(
                    selected_application.iloc[0], settings, repository
                )
        else:
            st.info("Sélectionne une carte pour ouvrir son détail.")

elif active_section == "emails":
    _render_gmail_sync_action(settings, repository, profile)
    if pending.empty:
        st.success("Aucun message ambigu en attente.")
    else:
        st.caption(
            "Cette file contient les messages emploi à interpréter ou à "
            "rattacher. Rocky ne modifie automatiquement une candidature "
            "qu'au-delà de 95 % de confiance."
        )
        email_filters = st.columns([1.3, 1.4, 2.3])
        pending_classes = sorted(
            str(value) for value in pending["classification"].dropna().unique()
        )
        selected_class = email_filters[0].selectbox(
            "Type",
            ["Tous", *pending_classes],
            format_func=lambda value: (
                "Tous les types" if value == "Tous" else EMAIL_LABELS.get(value, value)
            ),
            key="pending_email_class_filter",
        )
        pending_accounts = sorted(
            str(value) for value in pending["gmail_account"].dropna().unique()
        )
        selected_account = email_filters[1].selectbox(
            "Boîte",
            ["Toutes", *pending_accounts],
            key="pending_email_account_filter",
        )
        email_query = email_filters[2].text_input(
            "Rechercher dans les e-mails",
            placeholder="Objet, expéditeur ou entreprise",
            key="pending_email_query_filter",
        )
        visible_pending = pending.copy()
        if selected_class != "Tous":
            visible_pending = visible_pending[
                visible_pending["classification"] == selected_class
            ]
        if selected_account != "Toutes":
            visible_pending = visible_pending[
                visible_pending["gmail_account"] == selected_account
            ]
        if email_query.strip() and not visible_pending.empty:
            searchable = (
                visible_pending["subject"].fillna("")
                + " "
                + visible_pending["sender"].fillna("")
                + " "
                + visible_pending["company_name"].fillna("")
            )
            visible_pending = visible_pending[
                searchable.str.contains(email_query.strip(), case=False, regex=False)
            ]
        visible_pending = visible_pending.reset_index(drop=True)
        st.caption(
            f"{len(visible_pending)} message(s) · fais défiler les cartes "
            "latéralement puis ouvre celui que tu veux vérifier."
        )
        _render_pending_email_carousel(visible_pending)
        selected_email_id = st.session_state.get("selected_email_id")
        selected_email = visible_pending[
            visible_pending["id"].astype(int) == int(selected_email_id or -1)
        ]
        if not selected_email.empty:
            with st.container(border=True):
                _render_email_detail(selected_email.iloc[0], applications, repository)
        else:
            st.info("Sélectionne une carte pour ouvrir l'e-mail à vérifier.")

    with st.expander("Historique Gmail (diagnostic)", expanded=False):
        # L'historique reste disponible pour contrôler un classement, sans
        # concurrencer la file de décisions dans l'espace principal.
        if history.empty:
            st.caption("Aucun message Gmail enregistré.")
        else:
            history_filters = st.columns([1.3, 1.3, 1.5, 2.2])
            history_classes = sorted(
                str(value) for value in history["classification"].dropna().unique()
            )
            history_class = history_filters[0].selectbox(
                "Type",
                ["Tous", *history_classes],
                format_func=lambda value: (
                    "Tous les types"
                    if value == "Tous"
                    else EMAIL_LABELS.get(value, value)
                ),
                key="gmail_history_class_filter",
            )
            history_accounts = sorted(
                str(value) for value in history["gmail_account"].dropna().unique()
            )
            history_account = history_filters[1].selectbox(
                "Boîte",
                ["Toutes", *history_accounts],
                key="gmail_history_account_filter",
            )
            history_states = sorted(
                str(value) for value in history["processing_state"].dropna().unique()
            )
            history_state = history_filters[2].selectbox(
                "Traitement",
                ["Tous", *history_states],
                format_func=lambda value: (
                    "Tous les traitements"
                    if value == "Tous"
                    else EMAIL_PROCESSING_LABELS.get(value, value)
                ),
                key="gmail_history_state_filter",
            )
            history_query = history_filters[3].text_input(
                "Rechercher",
                placeholder="Objet, expéditeur ou entreprise",
                key="gmail_history_query_filter",
            )
            filtered_history = history.copy()
            if history_class != "Tous":
                filtered_history = filtered_history[
                    filtered_history["classification"] == history_class
                ]
            if history_account != "Toutes":
                filtered_history = filtered_history[
                    filtered_history["gmail_account"] == history_account
                ]
            if history_state != "Tous":
                filtered_history = filtered_history[
                    filtered_history["processing_state"] == history_state
                ]
            if history_query.strip() and not filtered_history.empty:
                searchable = (
                    filtered_history["sender"].fillna("")
                    + " "
                    + filtered_history["subject"].fillna("")
                    + " "
                    + filtered_history["company_name"].fillna("")
                    + " "
                    + filtered_history["job_title"].fillna("")
                )
                filtered_history = filtered_history[
                    searchable.str.contains(
                        history_query.strip(), case=False, regex=False
                    )
                ]
            history_view = filtered_history[
                [
                    "received_at",
                    "gmail_account",
                    "sender",
                    "subject",
                    "classification",
                    "classification_manual",
                    "processing_state",
                    "company_name",
                    "job_title",
                ]
            ].copy()
            history_view["received_at"] = history_view["received_at"].map(_display_date)
            history_view["classification"] = history_view["classification"].map(
                lambda value: EMAIL_LABELS.get(str(value), value)
            )
            history_view["classification_manual"] = history_view[
                "classification_manual"
            ].map(lambda value: "Manuelle" if bool(value) else "Automatique")
            history_view["processing_state"] = history_view["processing_state"].map(
                lambda value: EMAIL_PROCESSING_LABELS.get(str(value), value)
            )
            history_view = history_view.rename(
                columns={
                    "received_at": "Reçu",
                    "gmail_account": "Boîte",
                    "sender": "Expéditeur",
                    "subject": "Objet",
                    "classification": "Type",
                    "classification_manual": "Décision",
                    "processing_state": "Traitement",
                    "company_name": "Entreprise rapprochée",
                    "job_title": "Poste rapproché",
                }
            )
            st.caption(
                f"{len(history_view)} message(s) correspondant aux filtres "
                "· 100 derniers e-mails chargés."
            )
            history_selection = st.dataframe(
                history_view,
                hide_index=True,
                width="stretch",
                height=440,
                row_height=34,
                key="gmail_history_table",
                on_select="rerun",
                selection_mode="single-row",
            )
            selected_history_rows = list(history_selection["selection"]["rows"])
            if selected_history_rows:
                st.session_state["selected_history_email_id"] = int(
                    filtered_history.iloc[selected_history_rows[0]]["id"]
                )
            selected_history_id = st.session_state.get("selected_history_email_id")
            selected_history = filtered_history[
                filtered_history["id"].astype(int) == int(selected_history_id or -1)
            ]
            if not selected_history.empty:
                with st.container(border=True):
                    _render_history_email_detail(selected_history.iloc[0], repository)
