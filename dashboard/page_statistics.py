"""Tableau de bord analytique du parcours de recherche d'emploi.

La page agrège les annonces, scores, candidatures, réponses et veilles déjà
persistés pour permettre le pilotage. Elle produit des lectures statistiques et
ne déclenche aucune action sur une candidature ou Gmail.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_data
from dashboard.rocky.application_statuses import RESPONSE_STATUSES
from dashboard.rocky.gmail_service import GmailService
from dashboard.rocky.text_utils import ensure_list


def _role_family(title: object) -> str:
    """Regroupe les intitulés libres en familles lisibles, sans appel externe."""
    value = str(title or "").lower()
    for marker, label in (
        ("data scientist", "Data Scientist"),
        ("data analyst", "Data Analyst"),
        ("product", "Product / Data Product"),
        ("consult", "Conseil"),
        ("machine learning", "Machine Learning"),
        ("business intelligence", "BI / Analytics"),
    ):
        if marker in value:
            return label
    return "Autres métiers"


def _performance_table(frame: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Calcule des volumes et taux de réponse sans inventer de suivi historique."""
    if frame.empty:
        return pd.DataFrame()
    measured = frame.copy()
    measured["Réponse"] = measured["status"].isin(RESPONSE_STATUSES).astype(int)
    measured["Entretien"] = (
        measured["status"].isin(["ENTRETIEN", "TEST TECHNIQUE", "OFFRE"]).astype(int)
    )
    result = (
        measured.groupby(dimension, dropna=False)
        .agg(
            Dossiers=("id", "count"),
            Réponses=("Réponse", "sum"),
            Entretiens=("Entretien", "sum"),
        )
        .reset_index()
    )
    result["Taux de réponse"] = (100 * result["Réponses"] / result["Dossiers"]).round(
        0
    ).astype(int).astype(str) + " %"
    return result.sort_values(["Dossiers", "Réponses"], ascending=False)


st.markdown(
    '<div class="rocky-kicker">Mesure & progression</div>', unsafe_allow_html=True
)
st.title("Statistiques")
st.caption(
    "Un bilan visuel du flux d’offres jusqu’aux retours des recruteurs et aux "
    "accusés de réception."
)

try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

if profile is None:
    st.info("Active un profil pour calculer ses statistiques.")
    st.stop()

applications = repository.fetch_applications(profile.id)
sent_statuses = {
    "CANDIDATURE ENVOYÉE",
    "ACCUSÉ DE RÉCEPTION",
    "EN COURS",
    "ENTRETIEN",
    "TEST TECHNIQUE",
    "OFFRE",
    "REFUS",
}
sent = (
    applications[applications["status"].isin(sent_statuses)]
    if not applications.empty
    else applications
)
responses = (
    applications[applications["status"].isin(RESPONSE_STATUSES)]
    if not applications.empty
    else applications
)

response_delays = pd.Series(dtype="timedelta64[ns]")
if not applications.empty:
    applied_dates = pd.to_datetime(
        applications["applied_at"], errors="coerce", utc=True
    )
    response_dates = pd.to_datetime(
        applications["last_email_at"], errors="coerce", utc=True
    )
    response_delays = (response_dates - applied_dates).dropna()
    response_delays = response_delays[response_delays >= pd.Timedelta(0)]

top = st.columns(7)
top[0].metric("Offres suivies", len(jobs))
top[1].metric("Dossiers", len(applications))
top[2].metric("Envoyées", len(sent))
top[3].metric("Réponses", len(responses))
top[4].metric(
    "Entretiens",
    int(applications["status"].isin(["ENTRETIEN", "TEST TECHNIQUE"]).sum())
    if not applications.empty
    else 0,
)
top[5].metric(
    "Taux de réponse", f"{100 * len(responses) / len(sent):.0f} %" if len(sent) else "—"
)
top[6].metric(
    "Délai de réponse",
    f"{response_delays.dt.total_seconds().median() / 86400:.1f} j"
    if not response_delays.empty
    else "—",
)

left, right = st.columns(2)
with left:
    st.subheader("Entonnoir")
    funnel = pd.DataFrame(
        {
            "Étape": ["Préparées", "Envoyées", "Réponses", "Entretiens", "Offres"],
            "Volume": [
                len(applications),
                len(sent),
                len(responses),
                int(applications["status"].isin(["ENTRETIEN", "TEST TECHNIQUE"]).sum())
                if not applications.empty
                else 0,
                int((applications["status"] == "OFFRE").sum())
                if not applications.empty
                else 0,
            ],
        }
    )
    st.altair_chart(
        alt.Chart(funnel)
        .mark_bar(cornerRadiusEnd=8)
        .encode(
            x=alt.X("Volume:Q", title=None),
            y=alt.Y("Étape:N", sort=None, title=None),
            color=alt.Color(
                "Étape:N", legend=None, scale=alt.Scale(scheme="tealblues")
            ),
            tooltip=["Étape", "Volume"],
        ),
        width="stretch",
    )
with right:
    st.subheader("Statuts actuels")
    if applications.empty:
        st.info("Aucune candidature.")
    else:
        status_counts = applications.groupby("status").size().reset_index(name="Volume")
        st.altair_chart(
            alt.Chart(status_counts)
            .mark_arc(innerRadius=45)
            .encode(
                theta="Volume:Q",
                color=alt.Color(
                    "status:N", title="Statut", scale=alt.Scale(scheme="tealblues")
                ),
                tooltip=["status", "Volume"],
            ),
            width="stretch",
        )

charts = st.columns(2)
with charts[0]:
    st.subheader("Sources d’offres")
    source_counts = (
        jobs.groupby("source_name", dropna=False).size().reset_index(name="Offres")
    )
    source_counts["source_name"] = source_counts["source_name"].fillna("Inconnue")
    st.altair_chart(
        alt.Chart(source_counts.sort_values("Offres", ascending=False).head(12))
        .mark_bar(cornerRadiusEnd=6)
        .encode(
            x=alt.X("Offres:Q", title=None),
            y=alt.Y("source_name:N", sort="-x", title=None),
            color=alt.value("#08B5D1"),
            tooltip=["source_name", "Offres"],
        ),
        width="stretch",
    )
with charts[1]:
    st.subheader("Distribution du matching")
    scores = (
        pd.to_numeric(jobs["match_score"], errors="coerce").dropna()
        if "match_score" in jobs
        else pd.Series(dtype="float64")
    )
    if scores.empty:
        st.info("Aucun score disponible.")
    else:
        st.altair_chart(
            alt.Chart(pd.DataFrame({"Score": scores}))
            .mark_bar(color="#18212B")
            .encode(
                x=alt.X("Score:Q", bin=alt.Bin(maxbins=10), title="Score Rocky"),
                y=alt.Y("count():Q", title="Offres"),
                tooltip=["count():Q"],
            ),
            width="stretch",
        )

st.subheader("Évolution temporelle")
timeline_period = st.selectbox(
    "Fenêtre affichée",
    ("1 semaine", "1 mois", "3 mois", "6 mois"),
    index=1,
    help="La fenêtre courte évite de mélanger le suivi actuel avec les archives anciennes.",
)
period_days = {"1 semaine": 7, "1 mois": 31, "3 mois": 92, "6 mois": 183}[
    timeline_period
]
timeline_boundary = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timedelta(
    period_days, unit="D"
)
# La fenêtre d'une semaine conserve un point par jour. Pour un mois, les
# périodes hebdomadaires se terminent le dimanche afin que leur début
# corresponde au lundi affiché dans le graphique ; les archives restent
# regroupées par mois.
if timeline_period == "1 semaine":
    period_frequency, period_label = "D", "Jour"
elif timeline_period == "1 mois":
    period_frequency, period_label = "W-SUN", "Semaine"
else:
    period_frequency, period_label = "M", "Mois"
job_dates = pd.to_datetime(
    jobs["publication_date"].fillna(jobs["created_at"]), errors="coerce", utc=True
).dt.tz_localize(None)
job_dates = job_dates[job_dates >= timeline_boundary]
timeline_parts = []
if job_dates.notna().any():
    period_jobs = (
        pd.DataFrame(
            {period_label: job_dates.dt.to_period(period_frequency).dt.start_time}
        )
        .dropna()
        .groupby(period_label)
        .size()
        .reset_index(name="Volume")
    )
    period_jobs["Série"] = "Offres"
    timeline_parts.append(period_jobs)
if not applications.empty:
    application_dates = pd.to_datetime(
        applications["prepared_at"], errors="coerce", utc=True
    ).dt.tz_localize(None)
    application_dates = application_dates[application_dates >= timeline_boundary]
    period_applications = (
        pd.DataFrame(
            {
                period_label: application_dates.dt.to_period(
                    period_frequency
                ).dt.start_time
            }
        )
        .dropna()
        .groupby(period_label)
        .size()
        .reset_index(name="Volume")
    )
    period_applications["Série"] = "Dossiers"
    timeline_parts.append(period_applications)
if timeline_parts:
    timeline = pd.concat(timeline_parts, ignore_index=True)
    st.altair_chart(
        alt.Chart(timeline)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X(f"{period_label}:T", title=None),
            y=alt.Y("Volume:Q", title=f"Volume par {period_label.lower()}"),
            color=alt.Color("Série:N", scale=alt.Scale(range=["#08B5D1", "#18212B"])),
            tooltip=[
                alt.Tooltip(f"{period_label}:T", format="%d/%m/%Y"),
                "Série",
                "Volume",
            ],
        ),
        width="stretch",
    )
else:
    st.info("Pas encore assez de dates pour afficher l’évolution.")

st.subheader("Performance des candidatures")
performance_columns = st.columns(3)
if applications.empty:
    st.info("Prépare un premier dossier pour comparer les performances.")
else:
    measured = applications.copy()
    measured["source_name"] = measured["source_name"].fillna("Inconnue")
    measured["Famille de poste"] = measured["job_title"].map(_role_family)
    measured["Tranche de matching"] = (
        pd.cut(
            pd.to_numeric(measured["match_score"], errors="coerce"),
            bins=[-0.01, 59.99, 69.99, 79.99, 89.99, 100],
            labels=["< 60 %", "60–69 %", "70–79 %", "80–89 %", "90–100 %"],
        )
        .astype(object)
        .fillna("Sans score")
    )
    for column, dimension, title in zip(
        performance_columns,
        ("source_name", "Famille de poste", "Tranche de matching"),
        ("Par source", "Par poste", "Par matching"),
        strict=True,
    ):
        with column:
            st.caption(title)
            st.dataframe(
                _performance_table(measured, dimension),
                hide_index=True,
                width="stretch",
            )

st.subheader("Compétences les plus demandées")
skill_counts: dict[str, int] = {}
gap_counts: dict[str, int] = {}
for value in jobs.get("required_skills", pd.Series(dtype=object)):
    for skill in ensure_list(value):
        skill_counts[skill] = skill_counts.get(skill, 0) + 1
for value in jobs.get("match_gaps", pd.Series(dtype=object)):
    for skill in ensure_list(value):
        gap_counts[skill] = gap_counts.get(skill, 0) + 1
skills_columns = st.columns(2)
with skills_columns[0]:
    st.caption("Demandées")
    if skill_counts:
        demanded = pd.DataFrame(
            sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
            columns=["Compétence", "Offres"],
        )
        st.dataframe(demanded, hide_index=True, width="stretch")
    else:
        st.info("Aucune compétence structurée disponible.")
with skills_columns[1]:
    st.caption("Manquantes dans le matching")
    if gap_counts:
        missing = pd.DataFrame(
            sorted(gap_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
            columns=["Compétence", "Occurrences"],
        )
        st.dataframe(missing, hide_index=True, width="stretch")
    else:
        st.info("Aucun manque structuré disponible.")

runs = repository.fetch_watch_runs(10)
health = st.columns(3)
health[0].metric(
    "Dernière veille", str(runs.iloc[0]["status"]) if not runs.empty else "Jamais"
)
authorized_gmail_accounts = sum(
    GmailService(settings, repository, profile, account).is_authorized
    for account in settings.gmail_accounts
)
health[1].metric(
    "Gmail OAuth",
    f"{authorized_gmail_accounts}/{len(settings.gmail_accounts)} autorisée(s)",
)
health[2].metric("Profil", profile.profile_name)
