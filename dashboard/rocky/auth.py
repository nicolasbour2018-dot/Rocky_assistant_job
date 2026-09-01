"""Authentification locale et e-mails transactionnels de Rocky.

Les jetons bruts ne sont jamais stockés : la base conserve uniquement leur
empreinte SHA-256. Les réponses publiques restent volontairement neutres afin
de ne pas révéler si une adresse possède déjà un compte.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import Engine, text

from .config import Settings
from .errors import ConfigurationError, RockyError
from .models import AuthenticatedUser

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LENGTH = 12
SESSION_DURATION = timedelta(days=30)
VERIFICATION_DURATION = timedelta(hours=24)
RESET_DURATION = timedelta(hours=1)
LOCK_DURATION = timedelta(minutes=15)
MAX_LOGIN_FAILURES = 5


def normalize_email(value: str) -> str:
    """Normalise une adresse avant toute comparaison ou contrainte d'unicité."""
    email = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise RockyError("Saisis une adresse e-mail valide.")
    return email


def validate_password(value: str) -> None:
    """Applique une politique lisible sans imposer de composition arbitraire."""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise RockyError(
            f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères."
        )


def _now() -> datetime:
    """Fournit une horloge UTC unique pour les jetons et sessions de sécurité."""
    return datetime.now(UTC)


def _hash_token(value: str) -> str:
    """Transforme un jeton opaque en empreinte persistable, jamais réversible."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_datetime(value: Any) -> datetime | None:
    """Relit de façon homogène les timestamps SQLite et PostgreSQL."""
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return result.replace(tzinfo=result.tzinfo or UTC)


class TransactionalMailer:
    """Petit client SMTP dédié aux liens de sécurité du compte."""

    def __init__(self, settings: Settings):
        """Configure l'expéditeur SMTP utilisé uniquement pour les liens de compte."""
        self.settings = settings

    def send(self, recipient: str, subject: str, body: str) -> None:
        """Envoie un message transactionnel de sécurité après vérification de la configuration."""
        if not self.settings.smtp_is_configured:
            raise ConfigurationError(
                "L'envoi SMTP n'est pas configuré. Renseigne SMTP_HOST et SMTP_FROM."
            )
        message = EmailMessage()
        message["From"] = self.settings.smtp_from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(
                self.settings.smtp_host, self.settings.smtp_port, timeout=15
            ) as smtp:
                if self.settings.smtp_use_tls:
                    smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise RockyError("L'e-mail de sécurité n'a pas pu être envoyé.") from error


class AuthService:
    """Gère comptes, mots de passe, jetons à usage unique et sessions."""

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        mailer: TransactionalMailer | None = None,
    ):
        """Assemble les dépendances d'authentification et le hachage de mots de passe."""
        self.engine = engine
        self.settings = settings
        self.mailer = mailer or TransactionalMailer(settings)
        self.passwords = PasswordHasher()

    def _issue_account_token(
        self, user_id: int, purpose: str, duration: timedelta
    ) -> str:
        """Émet un jeton unique et invalide les anciens liens du même parcours de compte."""
        raw_token = secrets.token_urlsafe(32)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE account_tokens SET used_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = :user_id AND purpose = :purpose AND used_at IS NULL"
                ),
                {"user_id": user_id, "purpose": purpose},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO account_tokens (
                        user_id, purpose, token_hash, expires_at
                    ) VALUES (:user_id, :purpose, :token_hash, :expires_at)
                    """
                ),
                {
                    "user_id": user_id,
                    "purpose": purpose,
                    "token_hash": _hash_token(raw_token),
                    "expires_at": _now() + duration,
                },
            )
        return raw_token

    def _send_token(self, email: str, purpose: str, raw_token: str) -> None:
        """Compose et délègue un lien d'activation ou de réinitialisation temporaire."""
        if purpose == "VERIFY_EMAIL":
            query_name = "verify"
            subject = "Active ton espace Rocky"
            introduction = "Crée ton mot de passe et active ton espace personnel :"
        else:
            query_name = "reset"
            subject = "Réinitialise ton mot de passe Rocky"
            introduction = "Choisis un nouveau mot de passe avec ce lien :"
        url = f"{self.settings.rocky_public_url}/?{query_name}={raw_token}"
        self.mailer.send(
            email,
            subject,
            f"{introduction}\n\n{url}\n\nCe lien est personnel et temporaire.",
        )

    def register(self, email_value: str) -> None:
        """Crée un compte en attente et envoie son lien d'activation.

        Un compte déjà présent produit la même réponse côté interface. Seul un
        compte encore en attente reçoit un nouveau lien.
        """
        email = normalize_email(email_value)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("SELECT id, status FROM users WHERE LOWER(email) = :email"),
                    {"email": email},
                )
                .mappings()
                .first()
            )
            if row is None:
                user_id = int(
                    connection.execute(
                        text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
                        {"email": email},
                    ).scalar_one()
                )
                status = "PENDING"
            else:
                user_id = int(row["id"])
                status = str(row["status"])
        if status == "PENDING":
            token = self._issue_account_token(
                user_id, "VERIFY_EMAIL", VERIFICATION_DURATION
            )
            self._send_token(email, "VERIFY_EMAIL", token)

    def request_password_reset(self, email_value: str) -> None:
        """Envoie un lien si le compte existe, sans divulguer cette existence."""
        try:
            email = normalize_email(email_value)
        except RockyError:
            return
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id FROM users WHERE LOWER(email) = :email "
                    "AND status = 'ACTIVE'"
                ),
                {"email": email},
            ).first()
        if row:
            token = self._issue_account_token(
                int(row[0]), "RESET_PASSWORD", RESET_DURATION
            )
            self._send_token(email, "RESET_PASSWORD", token)

    def _consume_token(self, raw_token: str, purpose: str) -> int:
        """Valide puis consomme un lien à usage unique avant tout changement de compte."""
        token_hash = _hash_token(raw_token)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT id, user_id, expires_at FROM account_tokens
                    WHERE token_hash = :token_hash AND purpose = :purpose
                      AND used_at IS NULL
                    """
                    ),
                    {"token_hash": token_hash, "purpose": purpose},
                )
                .mappings()
                .first()
            )
            if row is None or (_as_datetime(row["expires_at"]) or _now()) <= _now():
                raise RockyError("Ce lien est invalide ou a expiré.")
            connection.execute(
                text(
                    "UPDATE account_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": int(row["id"])},
            )
            return int(row["user_id"])

    def activate_account(self, raw_token: str, password: str) -> AuthenticatedUser:
        """Valide l'adresse, définit le premier mot de passe et active le compte."""
        validate_password(password)
        user_id = self._consume_token(raw_token, "VERIFY_EMAIL")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE users SET password_hash = :password_hash,
                        status = 'ACTIVE', email_verified_at = CURRENT_TIMESTAMP,
                        failed_login_count = 0, locked_until = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": user_id, "password_hash": self.passwords.hash(password)},
            )
        return self.fetch_user(user_id)

    def reset_password(self, raw_token: str, password: str) -> None:
        """Remplace le mot de passe puis révoque toutes les sessions existantes."""
        validate_password(password)
        user_id = self._consume_token(raw_token, "RESET_PASSWORD")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE users SET password_hash = :password_hash, "
                    "failed_login_count = 0, locked_until = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": user_id, "password_hash": self.passwords.hash(password)},
            )
            connection.execute(
                text(
                    "UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = :user_id AND revoked_at IS NULL"
                ),
                {"user_id": user_id},
            )

    def authenticate(
        self, email_value: str, password: str
    ) -> tuple[AuthenticatedUser, str]:
        """Vérifie les identifiants, applique le verrou et crée une session opaque."""
        email = normalize_email(email_value)
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM users WHERE LOWER(email) = :email"),
                    {"email": email},
                )
                .mappings()
                .first()
            )
        if row is None:
            # Le message ne doit pas confirmer qu'une adresse possède un compte.
            raise RockyError("Adresse ou mot de passe incorrect.")
        locked_until = _as_datetime(row.get("locked_until"))
        valid = bool(row.get("password_hash") and row.get("status") == "ACTIVE")
        if valid and locked_until and locked_until > _now():
            # Le verrou ne doit pas confirmer qu'une adresse possède un compte.
            raise RockyError("Adresse ou mot de passe incorrect.")
        if valid:
            try:
                self.passwords.verify(str(row["password_hash"]), password)
            except VerifyMismatchError:
                valid = False
        if not valid:
            failures = int(row.get("failed_login_count") or 0) + 1
            lock = _now() + LOCK_DURATION if failures >= MAX_LOGIN_FAILURES else None
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE users SET failed_login_count = :failures, "
                        "locked_until = :locked_until WHERE id = :id"
                    ),
                    {
                        "failures": failures,
                        "locked_until": lock,
                        "id": int(row["id"]),
                    },
                )
            raise RockyError("Adresse ou mot de passe incorrect.")

        user_id = int(row["id"])
        raw_session = secrets.token_urlsafe(32)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE users SET failed_login_count = 0, locked_until = NULL "
                    "WHERE id = :id"
                ),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
                    "VALUES (:user_id, :token_hash, :expires_at)"
                ),
                {
                    "user_id": user_id,
                    "token_hash": _hash_token(raw_session),
                    "expires_at": _now() + SESSION_DURATION,
                },
            )
        return self.fetch_user(user_id), raw_session

    def user_from_session(self, raw_session: str | None) -> AuthenticatedUser | None:
        """Résout une session valide et actualise sa dernière utilisation."""
        if not raw_session:
            return None
        token_hash = _hash_token(raw_session)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT s.id AS session_id, s.expires_at, u.*
                    FROM user_sessions s JOIN users u ON u.id = s.user_id
                    WHERE s.token_hash = :token_hash AND s.revoked_at IS NULL
                      AND u.status = 'ACTIVE'
                    """
                    ),
                    {"token_hash": token_hash},
                )
                .mappings()
                .first()
            )
            if row is None or (_as_datetime(row["expires_at"]) or _now()) <= _now():
                return None
            connection.execute(
                text(
                    "UPDATE user_sessions SET last_seen_at = CURRENT_TIMESTAMP "
                    "WHERE id = :id"
                ),
                {"id": int(row["session_id"])},
            )
        return self._user_from_row(row)

    def revoke_session(self, raw_session: str | None) -> None:
        """Révoque un seul jeton de session lors de la déconnexion du compte Rocky."""
        if not raw_session:
            return
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP "
                    "WHERE token_hash = :token_hash"
                ),
                {"token_hash": _hash_token(raw_session)},
            )

    def fetch_user(self, user_id: int) -> AuthenticatedUser:
        """Relit un compte destiné à borner les accès de l'interface et des services."""
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM users WHERE id = :id"), {"id": user_id}
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RockyError("Compte introuvable.")
        return self._user_from_row(row)

    @staticmethod
    def _user_from_row(row: Any) -> AuthenticatedUser:
        """Convertit une ligne SQL en identité minimale, sans exposer de données sensibles."""
        return AuthenticatedUser(
            id=int(row["id"]),
            email=str(row["email"]),
            status=str(row.get("status") or "ACTIVE"),
            email_verified_at=_as_datetime(row.get("email_verified_at")),
        )
