"""Interface conversationnelle de l'assistant Rocky.

Elle fournit au modèle un contexte borné sur les annonces et candidatures puis
présente toute écriture sous forme de proposition confirmable. Le chat n'accède
ni à du SQL libre ni à des actions externes arbitraires.
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from dashboard.dashboard_common import load_data
from dashboard.rocky.assistant_agent import plan_rocky_action
from dashboard.rocky.llm import RockyLLM
from dashboard.rocky.mascot import mascot_data_uri

st.markdown(
    '<div class="rocky-kicker">Copilote personnel</div>', unsafe_allow_html=True
)
st.title("Assistant Rocky")
st.caption("Rocky lit tes données; toute modification reste visible et confirmable.")
st.markdown(
    '<div class="rocky-hero"><strong>On regarde les vraies annonces, ensemble.</strong><br>'
    "Demande un comparatif, une piste de candidature ou un point rapide sur ton suivi.</div>",
    unsafe_allow_html=True,
)
assistant_expression = st.session_state.get("rocky_expression", "smiling")
st.markdown(
    f'''<div class="rocky-assistant-mascot" title="Rocky — {assistant_expression}">
      <img src="{mascot_data_uri(assistant_expression)}" alt="Rocky, {assistant_expression}">
    </div>''',
    unsafe_allow_html=True,
)
st.markdown(
    """<style>
    .rocky-assistant-mascot { display:flex; justify-content:center; align-items:center;
      min-height:270px; margin:.5rem auto 1rem; }
    .rocky-assistant-mascot img { width:220px; height:270px; object-fit:contain;
      filter: drop-shadow(0 14px 18px rgba(24,33,43,.18)); transition:transform .2s ease; }
    .rocky-assistant-mascot img:hover { transform:translateY(-4px) rotate(-1deg); }
    </style>""",
    unsafe_allow_html=True,
)

try:
    settings, repository, profile, jobs = load_data()
except Exception as error:
    st.error("Connexion à la base Rocky impossible.")
    st.code(type(error).__name__)
    st.stop()

if profile is None:
    st.info("Active un profil pour discuter avec Rocky.")
    st.stop()

examples = st.columns(3)
examples[0].caption("« Fais-moi un bilan »")
examples[1].caption("« Candidature #12 en entretien »")
examples[2].caption("« Annonce #42 ville = Paris »")

messages = st.session_state.setdefault("rocky_agent_messages", [])
for message in messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

prompt = st.chat_input("Demande un bilan ou prépare une action…")
if prompt:
    st.session_state["rocky_expression"] = "curious"
    messages.append({"role": "user", "content": prompt})
    action = plan_rocky_action(prompt)
    st.session_state.rocky_pending_action = asdict(action)
    if action.action == "READ_SUMMARY":
        applications = repository.fetch_applications(profile.id)
        scored = jobs.copy()
        if not scored.empty:
            scored["_score"] = pd.to_numeric(scored["match_score"], errors="coerce")
            scored = scored.dropna(subset=["_score"]).sort_values(
                "_score", ascending=False
            )
        answer = (
            f"Tu suis {len(jobs)} offres et {len(applications)} candidatures. "
            f"{int((applications['status'] == 'ENTRETIEN').sum()) if not applications.empty else 0} "
            "sont actuellement en entretien et "
            f"{int((applications['status'] == 'REFUS').sum()) if not applications.empty else 0} en refus."
        )
        if not scored.empty:
            answer += "\n\nMeilleures correspondances actuelles :\n- " + "\n- ".join(
                f"#{int(row['id'])} {row['company_name']} — {row['job_title']} ({row['_score']:.0f} %)"
                for _, row in scored.head(3).iterrows()
            )
        messages.append({"role": "assistant", "content": answer})
        st.session_state.pop("rocky_pending_action", None)
    elif action.requires_confirmation:
        messages.append({"role": "assistant", "content": action.summary})
    else:
        llm = RockyLLM(settings)
        if llm.is_configured:
            try:
                with st.chat_message("assistant"):
                    st.session_state["rocky_expression"] = "thinking"
                    answer = st.write_stream(
                        llm.stream_chat(
                            prompt,
                            profile,
                            jobs=jobs.to_dict("records"),
                            applications=repository.fetch_applications(
                                profile.id
                            ).to_dict("records"),
                            skills=repository.fetch_skills(profile.id),
                            history=messages[:-1],
                        )
                    )
            except Exception as error:
                st.session_state["rocky_expression"] = "compassionate"
                answer = str(error)
            else:
                st.session_state["rocky_expression"] = "good-job-check"
        else:
            answer = "Mistral n'est pas configuré, mais les commandes de statut restent disponibles."
        messages.append({"role": "assistant", "content": answer})
        st.session_state.pop("rocky_pending_action", None)
    st.rerun()

pending = st.session_state.get("rocky_pending_action")
if pending and pending.get("requires_confirmation"):
    with st.container(border=True):
        st.warning(pending["summary"])
        confirm, cancel = st.columns(2)
        if confirm.button(
            "Confirmer cette action", type="primary", use_container_width=True
        ):
            action = pending["action"]
            entity_id = int(pending["entity_id"])
            if action == "UPDATE_APPLICATION_STATUS":
                repository.update_application_status(
                    entity_id, pending["value"], source="ROCKY"
                )
            elif action == "ADD_APPLICATION_NOTE":
                repository.add_application_note(entity_id, pending["value"])
            elif action == "UPDATE_JOB_STATUS":
                repository.update_job_status(entity_id, pending["value"])
            elif action == "UPDATE_JOB_FIELD":
                repository.update_job_field(
                    entity_id, pending["field"], pending["value"]
                )
            messages.append(
                {"role": "assistant", "content": "Action appliquée et historisée."}
            )
            st.session_state.pop("rocky_pending_action", None)
            st.rerun()
        if cancel.button("Annuler", use_container_width=True):
            st.session_state.pop("rocky_pending_action", None)
            st.rerun()
