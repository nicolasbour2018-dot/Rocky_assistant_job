"""Monitoring de la veille, de Gmail et des connecteurs Rocky.

Cette page est le journal opérationnel : elle restitue les résultats de veille,
les requêtes utilisées, les sources et l'état Gmail. Elle sert à diagnostiquer
le fonctionnement sans lancer d'action métier implicite.
"""

from __future__ import annotations

import inspect
import json
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_data, metric_counts
from dashboard.rocky.gmail_service import GmailService


def _json_list(value: object) -> list[dict[str, object]]:
    """Décode les listes JSON de diagnostics en ignorant les formats historiques invalides."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _searched_titles_label(value: object) -> str:
    """Présente l'instantané JSON des intitulés sans dépendre du profil actuel."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        return "—"
    titles = [str(title).strip() for title in value if str(title).strip()]
    return " · ".join(titles) if titles else "—"


def _source_label(item: dict[str, object]) -> str:
    """Compose le libellé lisible d'un connecteur et de son collecteur éventuel."""
    source = str(item.get("source") or "Source inconnue")
    collector = str(item.get("collector") or "")
    return f"{source} via {collector}" if collector else source


def _count(item: dict[str, object], key: str) -> int:
    """Relit un compteur du bilan JSON de veille, écrit par la veille elle-même."""
    value = item.get(key)
    return int(value) if isinstance(value, int | float) else 0


def _horizontal_carousel_container():
    """Construit un rail horizontal compatible avec Streamlit 1.51+ ."""
    # Les paramètres sont assemblés d'après la signature réellement présente :
    # leur type ne peut pas être connu avant l'appel à `inspect`.
    options: dict[str, Any] = {"horizontal": True, "gap": "small"}
    if "wrap" in inspect.signature(st.container).parameters:
        options["wrap"] = False
    return st.container(**options)


def _note_preview(value: object, limit: int = 220) -> str:
    """Limite le texte d'un post-it tout en conservant ses retours à la ligne."""
    content = str(value or "").strip()
    if len(content) <= limit:
        return content
    return content[: limit - 1].rstrip() + "…"


def _render_note_carousel(notes: pd.DataFrame, repository) -> None:
    """Affiche les pense-bêtes récents comme des cartes jaunes défilables."""
    st.markdown(
        """
        <style>
        .rocky-postit {
            background: #fff7c2;
            border: 1px solid #eadf9a;
            border-radius: 14px;
            box-shadow: 0 5px 14px rgba(93, 77, 24, .10);
            min-height: 122px;
            padding: 14px 16px;
        }
        .rocky-postit small { color: #756b35; }
        .rocky-postit p {
            color: #3d391d;
            margin: 10px 0 0;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    carousel = _horizontal_carousel_container()
    for _, note in notes.iterrows():
        with carousel.container(width=280, height=220):
            updated_at = note.get("updated_at")
            date_label = (
                pd.NaT
                if updated_at is None
                else pd.to_datetime(updated_at, errors="coerce")
            )
            date_text = (
                date_label.strftime("%d/%m/%Y %H:%M")
                if pd.notna(date_label)
                else "Date inconnue"
            )
            st.markdown(
                f'<div class="rocky-postit"><small>📝 {escape(date_text)}</small>'
                f"<p>{escape(_note_preview(note.get('content')))}</p></div>",
                unsafe_allow_html=True,
            )
            if st.button(
                "Supprimer",
                key=f"delete_monitoring_note_{int(note['id'])}",
                type="tertiary",
                use_container_width=True,
            ):
                repository.delete_monitoring_note(int(note["id"]))
                st.rerun()


st.title("Monitoring")
st.caption("État de Rocky V2, services configurés et historique de veille.")
oauth_notice = st.session_state.pop("gmail_oauth_notice", None)
if isinstance(oauth_notice, dict):
    level = str(oauth_notice.get("level") or "info")
    message = str(oauth_notice.get("message") or "")
    renderer = getattr(st, level, st.info)
    renderer(message)

try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

counts = metric_counts(jobs)
metrics = st.columns(4)
metrics[0].metric("Annonces connues", counts["total"])
metrics[1].metric("Exploitables", counts["complete"])
metrics[2].metric("À enrichir", counts["incomplete"])
metrics[3].metric("Profil actif", profile.profile_name if profile else "Aucun")

st.subheader("Notes de projet")
st.caption(
    "Un espace rapide pour garder les prochaines actions, idées et rappels de Rocky."
)
with st.form("monitoring_note_form", clear_on_submit=True):
    note_content = st.text_area(
        "Nouvelle note",
        height=82,
        placeholder="Ex. Relancer l'entreprise X vendredi, vérifier le score de l'annonce Y…",
        label_visibility="collapsed",
    )
    save_note = st.form_submit_button("Ajouter la note", type="primary")
if save_note and note_content.strip():
    repository.create_monitoring_note(profile.id if profile else None, note_content)
    st.rerun()

monitoring_notes = repository.fetch_monitoring_notes(profile.id if profile else None)
if monitoring_notes.empty:
    st.info("Aucune note pour le moment. Ajoute ton premier pense-bête ci-dessus.")
else:
    st.caption(
        f"{len(monitoring_notes)} note(s) · fais défiler les post-it latéralement."
    )
    _render_note_carousel(monitoring_notes, repository)

st.subheader("Services")
st.dataframe(
    pd.DataFrame(
        [
            {
                "Service": label,
                "État": "Configuré" if configured else "À renseigner",
            }
            for label, configured in settings.diagnostic().items()
        ]
    ),
    hide_index=True,
    width="stretch",
)
st.caption(
    f"Modèle Mistral : {settings.mistral_model} · "
    f"Seuil par défaut : {settings.match_threshold} %"
)

st.subheader("Gmail lecture seule")
if profile:
    # Le dossier est créé dès l'ouverture de la page afin que l'installation
    # OAuth soit concrète, même avant la première autorisation Google.
    gmail_folder = settings.gmail_credentials_path.parent
    gmail_folder.mkdir(parents=True, exist_ok=True)
    st.caption(
        "Dossier OAuth local prêt. Dans le Finder, utilise ⌘⇧G puis colle ce "
        "chemin si les dossiers commençant par un point sont masqués."
    )
    st.code(str(gmail_folder), language=None)
    gmail_services = [
        GmailService(settings, repository, profile, account_email)
        for account_email in settings.gmail_accounts
    ]
    oauth_client_type = gmail_services[0].oauth_client_type if gmail_services else None
    if oauth_client_type == "web":
        st.warning(
            "Le JSON présent est un client OAuth Web. Télécharge un client "
            "« Application de bureau » dans Google Cloud, puis remplace "
            "credentials.json."
        )
    elif oauth_client_type == "invalid":
        st.warning("credentials.json n'est pas un client OAuth Google valide.")
    uploaded_credentials = st.file_uploader(
        "Ajouter le fichier OAuth Desktop app (credentials.json)",
        type=["json"],
        help="Le fichier reste uniquement dans ce dossier local ignoré par Git.",
    )
    if (
        st.button(
            "Installer les identifiants Gmail",
            disabled=uploaded_credentials is None,
        )
        and uploaded_credentials is not None
    ):
        try:
            content = uploaded_credentials.getvalue()
            payload = json.loads(content.decode("utf-8"))
            if not isinstance(payload, dict) or "installed" not in payload:
                raise ValueError(
                    "Choisis le JSON d'un client OAuth de type Desktop app."
                )
            settings.gmail_credentials_path.write_bytes(content)
            st.success("Identifiants Gmail enregistrés localement.")
            st.rerun()
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            st.error(str(error))
    if not gmail_services:
        st.warning("Ajoute au moins une adresse dans GMAIL_ACCOUNTS.")
    for gmail in gmail_services:
        st.markdown(f"**{gmail.account_email}**")
        st.caption(
            "Autorisé en lecture seule."
            if gmail.is_authorized
            else "Autorisation Google requise."
        )
        account_actions = st.columns(2)
        authorization_url_key = f"gmail_oauth_url_{gmail.account_email}"
        if account_actions[0].button(
            "Réautoriser" if gmail.is_authorized else "Autoriser",
            key=f"gmail_authorize_{gmail.account_email}",
            disabled=not gmail.is_configured,
            help=(
                "Place d'abord credentials.json dans .secrets/gmail/."
                if not gmail.is_configured
                else None
            ),
            use_container_width=True,
        ):
            try:
                st.session_state[authorization_url_key] = (
                    gmail.begin_browser_authorization(settings.gmail_oauth_redirect_uri)
                )
                st.rerun()
            except Exception as error:
                st.error(str(error))
        if account_actions[1].button(
            "Synchroniser",
            key=f"gmail_sync_{gmail.account_email}",
            disabled=not gmail.is_authorized,
            type="primary",
            use_container_width=True,
        ):
            try:
                with st.spinner(f"Lecture et classement de {gmail.account_email}…"):
                    summary = gmail.sync_gmail()
                # Le total du scan peut inclure des messages que les règles
                # viennent de classer. La file PENDING/REVIEW est la seule
                # source fiable pour indiquer l'action restante à l'utilisateur.
                pending_now = len(
                    repository.fetch_pending_email_messages(gmail.account_email)
                )
                st.success(
                    f"{summary.inserted} message(s) ajouté(s), "
                    f"{summary.auto_applied} statut(s) mis à jour automatiquement, "
                    f"{summary.auto_ignored} notification(s) classée(s) sans action, "
                    f"{pending_now} message(s) actuellement à vérifier."
                )
                if summary.errors:
                    st.warning(
                        f"Synchronisation partielle : {len(summary.errors)} "
                        "message(s) n'ont pas pu être enregistrés."
                    )
            except Exception as error:
                st.error(str(error))
        authorization_url = st.session_state.get(authorization_url_key)
        if authorization_url:
            st.link_button(
                f"Continuer avec Google pour {gmail.account_email}",
                str(authorization_url),
                type="primary",
                use_container_width=True,
            )
            st.caption(
                "Le lien s'ouvre dans ton navigateur. Après ton accord, Google te "
                "ramènera automatiquement dans Rocky."
            )
    pending_count = len(repository.fetch_pending_email_messages())
    if pending_count:
        st.info(
            f"File de validation : {pending_count} message(s) emploi à interpréter. "
            "Rocky écarte automatiquement les messages non liés à l'emploi "
            "au-delà de 90 % de confiance et réserve les cas ambigus à cette file.",
            icon="📬",
        )
        st.link_button(
            "📨 Ouvrir la file de validation",
            "/page_applications",
            use_container_width=True,
        )
else:
    st.info("Active un profil avant de connecter Gmail.")

st.subheader("Historique des veilles")
runs = repository.fetch_watch_runs(30)
if runs.empty:
    st.info("Aucune veille enregistrée.")
else:
    display = runs.copy()
    if "errors" in display:
        display["errors"] = display["errors"].map(
            lambda value: len(
                json.loads(value) if isinstance(value, str) else value or []
            )
        )
    if "searched_job_titles" in display:
        display["searched_job_titles"] = display["searched_job_titles"].map(
            _searched_titles_label
        )
    columns = [
        "started_at",
        "finished_at",
        "status",
        "profile_name",
        "searched_job_titles",
        "fetched_count",
        "inserted_count",
        "duplicate_count",
        "rejected_count",
        "errors",
    ]
    st.dataframe(
        display[[column for column in columns if column in display]],
        hide_index=True,
        width="stretch",
        column_config={
            "started_at": "Début",
            "finished_at": "Fin",
            "status": "État",
            "profile_name": "Profil",
            "searched_job_titles": "Postes recherchés",
            "fetched_count": "Détectées",
            "inserted_count": "Ajoutées",
            "duplicate_count": "Déjà connues",
            "rejected_count": "Écartées",
            "errors": "Erreurs",
        },
    )

    st.subheader("Résultat des connecteurs")
    st.caption(
        "Détail des sources interrogées pour chaque veille récente. Les messages "
        "techniques sensibles ne sont jamais affichés."
    )
    for _, run in runs.head(10).iterrows():
        source_results = _json_list(run.get("source_results"))
        errors = _json_list(run.get("errors"))
        error_by_source = {
            str(error.get("source") or "Source inconnue"): str(
                error.get("message") or "Erreur sans détail."
            )
            for error in errors
        }
        started_at = run.get("started_at")
        started = (
            pd.NaT
            if started_at is None
            else pd.to_datetime(started_at, errors="coerce")
        )
        started_label = (
            started.strftime("%d/%m/%Y %H:%M")
            if not pd.isna(started)
            else "Date inconnue"
        )
        profile_label = str(run.get("profile_name") or "Profil supprimé")
        status_label = str(run.get("status") or "INCONNU")
        searched_titles = _searched_titles_label(run.get("searched_job_titles"))
        with st.expander(
            f"{started_label} · {profile_label} · {searched_titles} · {status_label}",
            expanded=False,
        ):
            st.caption(f"Postes recherchés : {searched_titles}")
            if source_results:
                successful = [
                    item
                    for item in source_results
                    if str(item.get("status") or "").upper() == "OK"
                ]
                failed = [
                    item
                    for item in source_results
                    if str(item.get("status") or "").upper() != "OK"
                ]
                result_columns = st.columns(2)
                with result_columns[0]:
                    st.markdown(f"**Sources réussies · {len(successful)}**")
                    if not successful:
                        st.info("Aucune source n’a terminé avec succès.")
                    for item in successful:
                        source = _source_label(item)
                        count = _count(item, "fetched_count")
                        inserted = _count(item, "inserted_count")
                        duplicates = _count(item, "duplicate_count")
                        rejected = _count(item, "rejected_count")
                        incomplete = _count(item, "incomplete_count")
                        st.success(
                            f"{source} · OK · {count} détectée(s) · "
                            f"{inserted} nouvelle(s) · {duplicates} doublon(s) · "
                            f"{rejected} sous le seuil · {incomplete} à enrichir"
                        )
                with result_columns[1]:
                    st.markdown(f"**Sources en erreur · {len(failed)}**")
                    if not failed:
                        st.success("Aucune source en erreur.")
                    for item in failed:
                        source = str(item.get("source") or "Source inconnue")
                        label = _source_label(item)
                        message = error_by_source.get(
                            source, "La source n’a pas répondu correctement."
                        )
                        st.warning(f"{label} · {message}")
            elif errors:
                st.warning(
                    "Cette veille est antérieure au suivi des sources réussies. "
                    "Seules les erreurs enregistrées sont disponibles."
                )
                for source, message in error_by_source.items():
                    st.warning(f"{source} · {message}")
            else:
                st.info(
                    "Le détail par source n’était pas encore enregistré pour cette veille."
                )

st.subheader("Répartition par source")
if jobs.empty:
    st.info("Aucune donnée source disponible.")
else:
    source_counts = (
        jobs.groupby("source_name", dropna=False)
        .agg(
            annonces=("id", "count"),
            descriptions_completes=("description_is_full", "sum"),
        )
        .reset_index()
        .sort_values("annonces", ascending=False)
    )
    st.dataframe(source_counts, hide_index=True, width="stretch")

st.info(
    "Les secrets ne sont jamais affichés. Après modification de .env, "
    "redémarre Rocky pour recharger la configuration."
)
