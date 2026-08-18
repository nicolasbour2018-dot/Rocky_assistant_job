"""Chargement centralisé de la configuration de Rocky.

Toutes les variables d'environnement sont lues ici. Les autres modules
reçoivent un objet Settings et n'accèdent jamais directement au fichier .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_DIR / ".env"
load_dotenv(ENV_PATH)


def _integer(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError:
        return default


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
    mistral_model: str = os.getenv(
        "MISTRAL_MODEL", "mistral-small-latest"
    ).strip()
    france_travail_client_id: str = os.getenv(
        "FRANCE_TRAVAIL_CLIENT_ID", ""
    ).strip()
    france_travail_client_secret: str = os.getenv(
        "FRANCE_TRAVAIL_CLIENT_SECRET", ""
    ).strip()
    adzuna_app_id: str = os.getenv("ADZUNA_APP_ID", "").strip()
    adzuna_app_key: str = os.getenv("ADZUNA_APP_KEY", "").strip()
    adzuna_country: str = os.getenv("ADZUNA_COUNTRY", "fr").strip()
    theirstack_api_key: str = os.getenv("THEIRSTACK_API_KEY", "").strip()
    theirstack_indeed_max_age_days: int = _integer(
        "THEIRSTACK_INDEED_MAX_AGE_DAYS", 30
    )
    match_threshold: int = _integer("MATCH_THRESHOLD", 70)
    watch_results_per_query: int = _integer("WATCH_RESULTS_PER_QUERY", 20)
    storage_dir_override: str = os.getenv("ROCKY_STORAGE_DIR", "").strip()
    hf_space_id: str = os.getenv("SPACE_ID", "").strip()

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
        return self.storage_dir / "output" / "candidatures"

    @property
    def profiles_dir(self) -> Path:
        return self.storage_dir / "data" / "profiles"

    @property
    def storage_dir(self) -> Path:
        """Racine des données modifiables, locale ou montée par Hugging Face."""
        if self.storage_dir_override:
            return Path(self.storage_dir_override).expanduser()
        return self.project_dir

    @property
    def is_huggingface_space(self) -> bool:
        return bool(self.hf_space_id)

    def diagnostic(self) -> dict[str, bool]:
        """Indique la présence des réglages, jamais leur valeur."""
        return {
            "PostgreSQL": self.database_url is not None,
            "Mistral AI": bool(self.mistral_api_key),
            "France Travail": bool(
                self.france_travail_client_id
                and self.france_travail_client_secret
            ),
            "Adzuna": bool(self.adzuna_app_id and self.adzuna_app_key),
            "TheirStack (Indeed + enrichissement)": bool(
                self.theirstack_api_key
            ),
        }
