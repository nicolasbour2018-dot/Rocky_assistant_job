# 0006 – Web : FastAPI, Jinja2, htmx, Pico CSS

Date : 2026-09-01. Statut : acceptée.

## Contexte

L'interface Streamlit fait 8423 lignes. L'audit montre que le coût n'est pas
le HTML dans les chaînes Python (133 lignes de CSS, 21 sites) mais le
couplage : 65 `st.rerun()`, 171 accès à `st.session_state`, 32 sélecteurs sur
le DOM interne de Streamlit, version épinglée `>=1.51,<1.52`. L'auth passe
par un composant cookie tiers. Le multi-compte est un bricolage dans un outil
conçu pour des data apps mono-utilisateur.

Alternatives pesées : Django + htmx (batteries incluses, mais remplace
`auth.py` et SQLAlchemy, et s'accorde mal avec une architecture hexagonale) ;
Litestar (plus structuré, mais corpus plus petit pour les agents) ; Streamlit
corrigé sur place (garde le couplage).

## Décision

FastAPI + Jinja2 + htmx. Pico CSS vendoré, plus une feuille projet pour les
jetons Rocky (couleurs, mascotte). Zéro Node, zéro étape de build.

`auth.py` est conservé et exposé comme dépendance FastAPI : le cookie
`rocky_session` donne l'utilisateur courant.

Transition page par page : FastAPI et Streamlit tournent côte à côte sur deux
ports de `localhost`, même base, même table `user_sessions` ; un cookie
ignore le port, la session est donc partagée. Chaque page Streamlit est
supprimée dans le lot qui la remplace.

## Conséquences

- Les 65 `st.rerun()` deviennent des fragments htmx ; le chat de la mascotte
  garde son streaming via un flux SSE.
- Les 86 ternaires FR/EN de `page_profiles.py` deviennent des variables de
  template. L'interface reste en français ; FR/EN reste un attribut du
  contenu des profils, pas une traduction de l'UI.
- Tests web avec le `TestClient` httpx de FastAPI.
- `streamlit` et `streamlit-cookies-controller` quittent les dépendances à la
  fin de la transition.
