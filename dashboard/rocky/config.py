"""Chargement centralisé de la configuration de Rocky.

Toutes les variables d'environnement sont lues ici. Les autres modules
reçoivent un objet Settings et n'accèdent jamais directement au fichier .env.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

from .errors import ConfigurationError


PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_DIR / ".env"
load_dotenv(ENV_PATH)


def _integer(name: str, default: int) -> int:
    """Lit un réglage entier et refuse une valeur invalide."""
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(
            f"Le réglage {name} doit être un nombre entier."
        ) from error


def _gmail_accounts(value: str) -> tuple[str, ...]:
    """Normalise la liste ordonnée des boîtes Gmail gérées par Rocky."""
    accounts: list[str] = []
    for raw_account in value.split(","):
        account = raw_account.strip().lower()
        if not account:
            continue
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", account):
            raise ConfigurationError(
                "GMAIL_ACCOUNTS contient une adresse e-mail invalide."
            )
        if account not in accounts:
            accounts.append(account)
    return tuple(accounts)


@dataclass(frozen=True)
class Settings:
    """Configuration immuable utilisée par l'application."""

    project_dir: Path = PROJECT_DIR
    database_url_override: str = os.getenv("DATABASE_URL", "").strip()
    db_user: str = os.getenv("DB_USER", "").strip()
    db_password: str = os.getenv("DB_PASSWORD", "").strip()
    db_host: str = os.getenv("DB_HOST", "localhost").strip()
    db_port: str = os.getenv("DB_PORT", "5432").strip()
    db_name: str = os.getenv("DB_NAME", "rocky").strip()
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "").strip()
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest").strip()
    france_travail_client_id: str = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "").strip()
    france_travail_client_secret: str = os.getenv(
        "FRANCE_TRAVAIL_CLIENT_SECRET", ""
    ).strip()
    adzuna_app_id: str = os.getenv("ADZUNA_APP_ID", "").strip()
    adzuna_app_key: str = os.getenv("ADZUNA_APP_KEY", "").strip()
    adzuna_country: str = os.getenv("ADZUNA_COUNTRY", "fr").strip()
    theirstack_api_key: str = os.getenv("THEIRSTACK_API_KEY", "").strip()
    theirstack_indeed_max_age_days: int = _integer("THEIRSTACK_INDEED_MAX_AGE_DAYS", 30)
    match_threshold: int = _integer("MATCH_THRESHOLD", 70)
    watch_results_per_query: int = _integer("WATCH_RESULTS_PER_QUERY", 20)
    gmail_max_messages: int = _integer("GMAIL_MAX_MESSAGES", 100)
    gmail_lookback_days: int = _integer("GMAIL_LOOKBACK_DAYS", 180)
    gmail_accounts: tuple[str, ...] = _gmail_accounts(os.getenv("GMAIL_ACCOUNTS", ""))
    gmail_oauth_redirect_uri: str = os.getenv(
        "GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8501/"
    ).strip()
    rocky_public_url: str = (
        os.getenv("ROCKY_PUBLIC_URL", "http://localhost:8501").strip().rstrip("/")
    )
    rocky_session_secret: str = os.getenv("ROCKY_SESSION_SECRET", "").strip()
    smtp_host: str = os.getenv("SMTP_HOST", "").strip()
    smtp_port: int = _integer("SMTP_PORT", 587)
    smtp_username: str = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password: str = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from_email: str = os.getenv(
        "SMTP_FROM", os.getenv("SMTP_FROM_EMAIL", "")
    ).strip()
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    storage_dir_override: str = os.getenv("ROCKY_STORAGE_DIR", "").strip()

    @property
    def database_url(self) -> str | None:
        """Construit l'URL SQLAlchemy sans jamais l'écrire dans les logs."""
        if self.database_url_override:
            return self.database_url_override
        if not self.db_user or not self.db_password or not self.db_name:
            return None
        return (
            "postgresql+psycopg2://"
            f"{quote_plus(self.db_user)}:{quote_plus(self.db_password)}@"
            f"{self.db_host}:{self.db_port}/{quote_plus(self.db_name)}"
        )

    @property
    def output_dir(self) -> Path:
        """Retourne le répertoire commun des candidatures lorsque aucun compte n'est isolé."""
        return self.storage_dir / "output" / "candidatures"

    def user_dir(self, user_id: int) -> Path:
        """Retourne la racine privée d'un compte sans dépendre de son e-mail."""
        return self.data_dir / "users" / str(int(user_id))

    def user_profiles_dir(self, user_id: int) -> Path:
        """Isole tous les documents sources et traduits d'un compte."""
        return self.user_dir(user_id) / "profiles"

    def user_output_dir(self, user_id: int) -> Path:
        """Isole les dossiers de candidature générés par compte."""
        return self.user_dir(user_id) / "output" / "candidatures"

    @property
    def smtp_is_configured(self) -> bool:
        """Indique si Rocky peut envoyer les e-mails transactionnels."""
        return bool(self.smtp_host and self.smtp_from_email)

    @property
    def profiles_dir(self) -> Path:
        """Retourne le dossier des profils sans doubler le montage ``/data``.

        En local, les fichiers restent sous ``<projet>/data/profiles``. Dans
        le conteneur, ``ROCKY_STORAGE_DIR=/data`` désigne déjà ce même dossier
        de données : lui rajouter ``data`` faisait chercher les projets dans
        ``/data/data/profiles`` et masquait les fichiers existants.
        """
        return self.data_dir / "profiles"

    @property
    def data_dir(self) -> Path:
        """Racine des données métier, adaptée au montage persistant éventuel."""
        if self.storage_dir_override:
            return self.storage_dir
        return self.project_dir / "data"

    @property
    def storage_dir(self) -> Path:
        """Racine des données modifiables, locale ou montée par Hugging Face."""
        if self.storage_dir_override:
            return Path(self.storage_dir_override).expanduser()
        return self.project_dir

    @property
    def gmail_credentials_path(self) -> Path:
        """Localise le client OAuth partagé, sans jamais lire ou afficher son secret ici."""
        return self.project_dir / ".secrets" / "gmail" / "credentials.json"

    def gmail_oauth_pending_dir_for(self, user_id: int) -> Path:
        """Isole les états OAuth temporaires d'un compte."""
        return self.user_dir(user_id) / "gmail" / "oauth_pending"

    def gmail_token_path_for(self, account_email: str, user_id: int) -> Path:
        """Construit un chemin stable sans utiliser l'adresse comme sous-dossier."""
        slug = re.sub(r"[^a-z0-9]+", "_", account_email.strip().lower()).strip("_")
        if not slug:
            raise ValueError("L'adresse Gmail ne peut pas être vide.")
        directory = self.user_dir(user_id) / "gmail" / "accounts"
        return directory / f"{slug}.json"

    def user_browser_profile_dir(self, user_id: int) -> Path:
        """Évite qu'une session de formulaire web soit partagée entre comptes."""
        return self.user_dir(user_id) / "browser_profile"

    def diagnostic(self) -> dict[str, bool]:
        """Indique la présence des réglages, jamais leur valeur."""
        return {
            "PostgreSQL": self.database_url is not None,
            "Mistral AI": bool(self.mistral_api_key),
            "France Travail": bool(
                self.france_travail_client_id and self.france_travail_client_secret
            ),
            "Adzuna": bool(self.adzuna_app_id and self.adzuna_app_key),
            "TheirStack (Indeed + enrichissement)": bool(self.theirstack_api_key),
            "Gmail OAuth lecture seule": self.gmail_credentials_path.is_file(),
        }
