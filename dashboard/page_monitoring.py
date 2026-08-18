"""Monitoring et diagnostic repris de Rocky V1.1."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_data, metric_counts


def _json_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _source_label(item: dict[str, object]) -> str:
    source = str(item.get("source") or "Source inconnue")
    collector = str(item.get("collector") or "")
    return f"{source} via {collector}" if collector else source


st.title("Monitoring")
st.caption("État de Rocky V2, services configurés et historique de veille.")

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
    columns = [
        "started_at",
        "finished_at",
        "status",
        "profile_name",
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
        started = pd.to_datetime(run.get("started_at"), errors="coerce")
        started_label = (
            started.strftime("%d/%m/%Y %H:%M")
            if not pd.isna(started)
            else "Date inconnue"
        )
        profile_label = str(run.get("profile_name") or "Profil supprimé")
        status_label = str(run.get("status") or "INCONNU")
        with st.expander(
            f"{started_label} · {profile_label} · {status_label}",
            expanded=False,
        ):
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
                        count = int(item.get("fetched_count") or 0)
                        inserted = int(item.get("inserted_count") or 0)
                        duplicates = int(item.get("duplicate_count") or 0)
                        st.success(
                            f"{source} · OK · {count} détectée(s) · "
                            f"{inserted} nouvelle(s) · {duplicates} doublon(s)"
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
