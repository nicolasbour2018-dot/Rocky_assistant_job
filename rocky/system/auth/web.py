"""Authentication pages, session middleware and the ``require_account`` dependency.

Each request that writes runs one use case in one transaction; e-mails leave after the commit.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from rocky.system.auth.mail import MailDeliveryError, Mailer, MailNotConfiguredError
from rocky.system.auth.model import Account
from rocky.system.auth.rules import (
    SESSION_IDLE_LIFETIME,
    InvalidPasswordError,
    safe_next_path,
)
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.auth.usecases import (
    Auth,
    Clock,
    InvalidLink,
    PasswordHasher,
    ResolvedSession,
    SessionOpened,
)

logger = logging.getLogger(__name__)

SESSION_COOKIE = "rocky_session"
LOGIN_PATH = "/connexion"

MESSAGES = {
    "refused": "Adresse ou mot de passe incorrect.",
    "mismatch": "Les deux mots de passe ne sont pas identiques.",
    "invalid_link": "Ce lien est invalide, a déjà servi ou a expiré.",
    "reset_sent": (
        "Si un compte actif correspond à cette adresse, un e-mail vient de partir. "
        "Le lien reste valable 1 heure."
    ),
    "mail_failed": "L'e-mail n'a pas pu être envoyé. Réessaie plus tard.",
    "password_changed": "Mot de passe modifié : connecte-toi avec le nouveau.",
}


@dataclass(frozen=True)
class AuthServices:
    engine: Engine
    hasher: PasswordHasher
    clock: Clock
    mailer: Mailer
    public_url: str
    secure_cookies: bool


class LoginRequiredError(Exception):
    """A protected page was requested without a valid session."""

    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path


router = APIRouter()


def services(request: Request) -> AuthServices:
    return request.app.state.auth  # type: ignore[no-any-return]


def templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


@contextmanager
def auth_transaction(auth_services: AuthServices) -> Iterator[Auth]:
    """One use case, one transaction: committed on exit, rolled back on error."""
    with auth_services.engine.begin() as connection:
        yield Auth(
            SqlAuthStore(connection),
            hasher=auth_services.hasher,
            clock=auth_services.clock,
            public_url=auth_services.public_url,
        )


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Persistent cookie (Max-Age): it survives a browser restart."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_IDLE_LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=secure, samesite="lax"
    )


def _sets_session_cookie(response: Response) -> bool:
    return any(
        value.startswith(f"{SESSION_COOKIE}=")
        for value in response.headers.getlist("set-cookie")
    )


def _resolve(auth_services: AuthServices, token: str) -> ResolvedSession | None:
    with auth_transaction(auth_services) as auth:
        return auth.resolve_session(token)


async def session_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Expose the session's account on ``request.state``; slide or clear the cookie."""
    auth_services = services(request)
    token = request.cookies.get(SESSION_COOKIE)
    resolved = (
        await run_in_threadpool(_resolve, auth_services, token) if token else None
    )
    request.state.account = resolved.account if resolved else None
    response = await call_next(request)
    if token and not _sets_session_cookie(response):
        if resolved is None:
            clear_session_cookie(response, secure=auth_services.secure_cookies)
        elif resolved.renewed:
            set_session_cookie(response, token, secure=auth_services.secure_cookies)
    return response


def require_account(request: Request) -> Account:
    account: Account | None = request.state.account
    if account is None:
        query = f"?{request.url.query}" if request.url.query else ""
        raise LoginRequiredError(f"{request.url.path}{query}")
    return account


def redirect_to_login(request: Request, error: Exception) -> Response:
    assert isinstance(error, LoginRequiredError)  # noqa: S101  (handler registered for this type)
    target = f"{LOGIN_PATH}?suite={quote(error.next_path, safe='')}"
    return RedirectResponse(target, status_code=303)


def install(app: FastAPI, auth_services: AuthServices) -> None:
    app.state.auth = auth_services
    app.middleware("http")(session_middleware)
    app.add_exception_handler(LoginRequiredError, redirect_to_login)
    app.include_router(router)


CurrentAccount = Annotated[Account, Depends(require_account)]


def _page(
    request: Request, name: str, status_code: int = 200, **context: object
) -> HTMLResponse:
    return templates(request).TemplateResponse(
        request, name, context, status_code=status_code
    )


def _opened(
    auth_services: AuthServices, opened: SessionOpened, target: str
) -> Response:
    response = RedirectResponse(target, status_code=303)
    set_session_cookie(
        response, opened.session_token, secure=auth_services.secure_cookies
    )
    return response


@router.get("/", response_class=HTMLResponse)
def home(request: Request, account: CurrentAccount) -> HTMLResponse:
    """Temporary home page; the web shell replaces it in step B4."""
    return _page(request, "home.html", account=account)


@router.get(LOGIN_PATH, response_class=HTMLResponse)
def login_form(
    request: Request, suite: str | None = None, info: str | None = None
) -> Response:
    if request.state.account is not None:
        return RedirectResponse(safe_next_path(suite), status_code=303)
    return _page(
        request,
        "auth/login.html",
        suite=safe_next_path(suite),
        info=MESSAGES.get(info or ""),
    )


@router.post(LOGIN_PATH, response_class=HTMLResponse)
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    suite: Annotated[str, Form()] = "/",
) -> Response:
    auth_services = services(request)
    with auth_transaction(auth_services) as auth:
        result = auth.login(email, password)
    if isinstance(result, SessionOpened):
        return _opened(auth_services, result, safe_next_path(suite))
    return _page(
        request,
        "auth/login.html",
        status_code=401,
        suite=safe_next_path(suite),
        email=email,
        error=MESSAGES["refused"],
    )


@router.post("/deconnexion")
def logout(request: Request) -> Response:
    auth_services = services(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with auth_transaction(auth_services) as auth:
            auth.logout(token)
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    clear_session_cookie(response, secure=auth_services.secure_cookies)
    return response


@router.get("/activation", response_class=HTMLResponse)
def activation_form(request: Request, jeton: str = "") -> HTMLResponse:
    return _page(request, "auth/set_password.html", action="/activation", jeton=jeton)


@router.post("/activation", response_class=HTMLResponse)
def activate(
    request: Request,
    jeton: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
) -> Response:
    auth_services = services(request)
    error = _password_error(password, confirmation)
    if error is None:
        try:
            with auth_transaction(auth_services) as auth:
                result = auth.activate(jeton, password)
        except InvalidPasswordError as invalid:
            error = str(invalid)
        else:
            if isinstance(result, SessionOpened):
                return _opened(auth_services, result, "/")
            error = MESSAGES["invalid_link"]
    return _page(
        request,
        "auth/set_password.html",
        status_code=400,
        action="/activation",
        jeton=jeton,
        error=error,
    )


@router.get("/mot-de-passe-oublie", response_class=HTMLResponse)
def forgotten_form(request: Request) -> HTMLResponse:
    return _page(request, "auth/forgotten.html")


@router.post("/mot-de-passe-oublie", response_class=HTMLResponse)
def forgotten(request: Request, email: Annotated[str, Form()]) -> HTMLResponse:
    auth_services = services(request)
    with auth_transaction(auth_services) as auth:
        mail = auth.request_reset(email)
    if mail is not None:
        try:
            auth_services.mailer.send(mail)
        except (MailNotConfiguredError, MailDeliveryError):
            logger.exception("password reset e-mail not sent")
            return _page(
                request,
                "auth/forgotten.html",
                status_code=503,
                error=MESSAGES["mail_failed"],
            )
    return _page(request, "auth/forgotten.html", info=MESSAGES["reset_sent"])


@router.get("/reinitialisation", response_class=HTMLResponse)
def reset_form(request: Request, jeton: str = "") -> HTMLResponse:
    return _page(
        request, "auth/set_password.html", action="/reinitialisation", jeton=jeton
    )


@router.post("/reinitialisation", response_class=HTMLResponse)
def reset(
    request: Request,
    jeton: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
) -> Response:
    auth_services = services(request)
    error = _password_error(password, confirmation)
    if error is None:
        try:
            with auth_transaction(auth_services) as auth:
                result = auth.reset_password(jeton, password)
        except InvalidPasswordError as invalid:
            error = str(invalid)
        else:
            if not isinstance(result, InvalidLink):
                response = RedirectResponse(
                    f"{LOGIN_PATH}?info=password_changed", status_code=303
                )
                clear_session_cookie(response, secure=auth_services.secure_cookies)
                return response
            error = MESSAGES["invalid_link"]
    return _page(
        request,
        "auth/set_password.html",
        status_code=400,
        action="/reinitialisation",
        jeton=jeton,
        error=error,
    )


def _password_error(password: str, confirmation: str) -> str | None:
    return None if password == confirmation else MESSAGES["mismatch"]
