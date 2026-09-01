"""Interface Streamlit d'authentification et de session Rocky.

Ce module traduit les opérations de ``AuthService`` en écrans de connexion,
création de compte et récupération. Il ne manipule jamais de secret durable :
seul le jeton de session opaque est conservé côté navigateur.
"""

from __future__ import annotations

import contextlib
from typing import NoReturn

import streamlit as st

from dashboard.dashboard_common import load_repository
from dashboard.rocky.auth import AuthService
from dashboard.rocky.config import Settings
from dashboard.rocky.errors import RockyError
from dashboard.rocky.models import AuthenticatedUser

COOKIE_NAME = "rocky_session"


def _cookie_controller():
    """Charge le composant de cookie tout en gardant les tests unitaires autonomes."""
    try:
        from streamlit_cookies_controller import CookieController
    except ImportError:
        return None
    return CookieController()


def _read_session(controller) -> str:
    """Lit le jeton opaque afin de restaurer un accès déjà vérifié."""
    raw = str(st.session_state.get(COOKIE_NAME) or "")
    if raw or controller is None:
        return raw
    try:
        return str(controller.get(COOKIE_NAME) or "")
    except Exception:
        return ""


def _store_session(controller, raw_session: str) -> None:
    """Conserve le jeton de session après authentification, sans exposer son contenu."""
    st.session_state[COOKIE_NAME] = raw_session
    if controller is None:
        return
    try:
        controller.set(COOKIE_NAME, raw_session, max_age=30 * 24 * 60 * 60)
    except TypeError:
        controller.set(COOKIE_NAME, raw_session)


def _clear_session(controller) -> None:
    """Supprime la session navigateur lors d'une déconnexion ou d'une invalidation."""
    st.session_state.pop(COOKIE_NAME, None)
    st.session_state.pop("rocky_authenticated_user_id", None)
    if controller is not None:
        with contextlib.suppress(Exception):
            controller.remove(COOKIE_NAME)


def _password_link(service: AuthService, token: str, purpose: str) -> None:
    """Rend le formulaire utilisé par les liens d'activation et de reset."""
    title = "Active ton espace Rocky" if purpose == "verify" else "Nouveau mot de passe"
    st.title(title)
    st.caption("Choisis une phrase de passe d'au moins 12 caractères.")
    with st.form(f"rocky_{purpose}_password"):
        password = st.text_input("Mot de passe", type="password")
        confirmation = st.text_input("Confirmation", type="password")
        submitted = st.form_submit_button("Enregistrer", type="primary")
    if submitted:
        if password != confirmation:
            st.error("Les deux mots de passe ne correspondent pas.")
            return
        try:
            if purpose == "verify":
                service.activate_account(token, password)
            else:
                service.reset_password(token, password)
        except RockyError as error:
            st.error(str(error))
            return
        st.query_params.clear()
        st.success("Mot de passe enregistré. Tu peux maintenant te connecter.")
        if st.button("Revenir à la connexion", type="primary"):
            st.rerun()
    st.stop()


def _access_screen(service: AuthService, controller) -> NoReturn:
    """Présente connexion, inscription et récupération sans révéler les comptes."""
    st.markdown(
        """
        <div class="rocky-hero">
          <span class="rocky-kicker">Espace personnel</span>
          <h1>Prépare tes candidatures avec Rocky</h1>
          <p>Connecte-toi pour retrouver tes profils, documents et candidatures.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    login_tab, register_tab, reset_tab = st.tabs(
        ["Connexion", "Créer un compte", "Mot de passe oublié"]
    )
    with login_tab:
        with st.form("rocky_login"):
            email = st.text_input("E-mail", key="login_email")
            password = st.text_input(
                "Mot de passe", type="password", key="login_password"
            )
            submitted = st.form_submit_button("Se connecter", type="primary")
        if submitted:
            try:
                user, raw_session = service.authenticate(email, password)
            except RockyError as error:
                st.error(str(error))
            else:
                _store_session(controller, raw_session)
                st.session_state["rocky_authenticated_user_id"] = user.id
                st.rerun()
    with register_tab:
        st.caption(
            "Un lien personnel te permettra de vérifier l'adresse et de choisir "
            "ton mot de passe."
        )
        with st.form("rocky_register"):
            email = st.text_input("E-mail", key="register_email")
            submitted = st.form_submit_button("Créer mon espace", type="primary")
        if submitted:
            try:
                service.register(email)
            except RockyError as error:
                st.error(str(error))
            else:
                st.success(
                    "Si cette adresse peut être utilisée, un lien d'activation vient d'être envoyé."
                )
    with reset_tab:
        with st.form("rocky_reset_request"):
            email = st.text_input("E-mail", key="reset_email")
            submitted = st.form_submit_button("Recevoir un lien", type="primary")
        if submitted:
            try:
                service.request_password_reset(email)
            except RockyError as error:
                st.error(str(error))
            else:
                st.success(
                    "Si un compte actif correspond, un lien de réinitialisation a été envoyé."
                )
    st.stop()


def require_authenticated_user() -> AuthenticatedUser:
    """Bloque le dashboard jusqu'à obtention d'une session vérifiée."""
    settings = Settings()
    service = AuthService(load_repository().engine, settings)
    verify_token = str(st.query_params.get("verify") or "")
    reset_token = str(st.query_params.get("reset") or "")
    if verify_token:
        _password_link(service, verify_token, "verify")
    if reset_token:
        _password_link(service, reset_token, "reset")

    controller = _cookie_controller()
    raw_session = _read_session(controller)
    user = service.user_from_session(raw_session)
    if user is None:
        _clear_session(controller)
        _access_screen(service, controller)
    st.session_state["rocky_authenticated_user_id"] = user.id
    st.session_state["rocky_authenticated_email"] = user.email
    return user


def render_account_sidebar(user: AuthenticatedUser) -> None:
    """Affiche l'identité courante et révoque proprement la session."""
    controller = _cookie_controller()
    with st.sidebar:
        st.caption(f"Connecté · {user.email}")
        if st.button("Se déconnecter", use_container_width=True):
            raw_session = _read_session(controller)
            AuthService(load_repository().engine, Settings()).revoke_session(
                raw_session
            )
            _clear_session(controller)
            st.rerun()
