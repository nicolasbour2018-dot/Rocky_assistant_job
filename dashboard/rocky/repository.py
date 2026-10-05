"""Accès PostgreSQL de Rocky.

Toutes les requêtes SQL sont regroupées ici. Les modules métier peuvent ainsi
être testés sans connaître la structure exacte de la base.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import Engine, text

from .application_statuses import (
    APPLICATION_TO_JOB_STATUS,
    normalize_application_status,
)
from .language import detect_language
from .models import (
    CandidateProfile,
    JobOffer,
    MatchResult,
    ProfileAnalysis,
    ProfileDocument,
    ProfileLocalization,
    ProfileProject,
)
from .text_utils import canonical_url, ensure_list


def _clean(value: Any) -> Any:
    """Normalise une valeur SQL hétérogène avant de la remettre aux flux métier."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (date, datetime, Decimal, int, float, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


class RockyRepository:
    """Façade de persistance utilisée par le dashboard et la veille."""

    def __init__(self, engine: Engine, user_id: int | None = None):
        """Lie la façade SQL à un moteur et, si besoin, à la frontière d'un compte."""
        self.engine = engine
        self.user_id = int(user_id) if user_id is not None else None

    def for_user(self, user_id: int) -> "RockyRepository":
        """Crée une façade dont toutes les racines métier sont bornées au compte."""
        return RockyRepository(self.engine, user_id)

    def fetch_active_user_ids(self) -> list[int]:
        """Retourne les comptes actifs pour une routine planifiée locale."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id FROM users WHERE status = 'ACTIVE' ORDER BY id")
            ).scalars().all()
        return [int(user_id) for user_id in rows]

    def _profile_is_owned(self, profile_id: int) -> bool:
        """Centralise le contrôle d'accès utilisé avant toute écriture enfant."""
        if self.user_id is None:
            return True
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT 1 FROM candidate_profiles "
                    "WHERE id = :id AND user_id = :user_id"
                ),
                {"id": profile_id, "user_id": self.user_id},
            ).first() is not None

    def _require_profile(self, profile_id: int) -> None:
        """Bloque immédiatement une lecture ou écriture de profil hors périmètre utilisateur."""
        if not self._profile_is_owned(profile_id):
            raise PermissionError("Ce profil n'appartient pas au compte connecté.")

    def _application_is_owned(self, application_id: int) -> bool:
        """Vérifie une candidature via son profil, source d'autorité du compte."""
        if self.user_id is None:
            return True
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    """
                    SELECT 1 FROM applications a
                    JOIN candidate_profiles p ON p.id = a.profile_id
                    WHERE a.id = :id AND p.user_id = :user_id
                    """
                ),
                {"id": application_id, "user_id": self.user_id},
            ).first() is not None

    def _require_application(self, application_id: int) -> None:
        """Vérifie qu'une candidature appartient au compte avant une action ciblée."""
        if not self._application_is_owned(application_id):
            raise PermissionError(
                "Cette candidature n'appartient pas au compte connecté."
            )

    def _email_is_owned(self, email_id: int) -> bool:
        """Empêche qu'un identifiant Gmail direct contourne l'isolation."""
        if self.user_id is None:
            return True
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT 1 FROM email_messages "
                    "WHERE id = :id AND user_id = :user_id"
                ),
                {"id": email_id, "user_id": self.user_id},
            ).first() is not None

    def _require_email(self, email_id: int) -> None:
        """Vérifie l'appartenance d'un e-mail afin de protéger la file Gmail par compte."""
        if not self._email_is_owned(email_id):
            raise PermissionError("Cet e-mail n'appartient pas au compte connecté.")

    @property
    def is_sqlite(self) -> bool:
        """Indique le dialecte pour adapter les types JSON et listes sans changer le métier."""
        return self.engine.dialect.name == "sqlite"

    def _list_value(self, value: list[Any]) -> list[Any] | str:
        """Adapte les listes aux tableaux PostgreSQL ou au JSON SQLite."""
        if self.is_sqlite:
            return json.dumps(value, ensure_ascii=False)
        return value

    def fetch_jobs(self, profile_id: int | None = None) -> pd.DataFrame:
        """Charge les annonces visibles d'un profil avec leur score courant pour les pages Rocky."""
        query = """
            SELECT
                j.*,
                CASE WHEN j.description_is_full THEN m.score END AS match_score,
                CASE WHEN j.description_is_full THEN m.breakdown END AS match_breakdown,
                CASE WHEN j.description_is_full THEN m.strengths END AS match_strengths,
                CASE WHEN j.description_is_full THEN m.gaps END AS match_gaps
            FROM job_offers j
            LEFT JOIN job_matches m
                ON m.job_id = j.id
                AND (:profile_id IS NOT NULL AND m.profile_id = :profile_id)
            WHERE (:user_id IS NULL OR j.user_id = :user_id)
              AND (:profile_id IS NULL OR EXISTS (
                SELECT 1
                FROM profile_jobs pj
                WHERE pj.job_id = j.id
                  AND pj.profile_id = :profile_id
            ))
            ORDER BY j.publication_date DESC NULLS LAST, j.created_at DESC
        """
        return pd.read_sql(
            text(query), self.engine,
            params={"profile_id": profile_id, "user_id": self.user_id},
        )

    def get_jobs_for_profile(self, profile_id: int) -> pd.DataFrame:
        """Retourne uniquement les annonces rattachées au profil demandé."""
        return self.fetch_jobs(profile_id)

    def link_job_to_profile(self, job_id: int, profile_id: int) -> bool:
        """Crée la relation profil-annonce sans dupliquer l'annonce centrale."""
        self._require_profile(profile_id)
        if self.user_id is not None:
            with self.engine.connect() as connection:
                owned_job = connection.execute(
                    text("SELECT 1 FROM job_offers WHERE id = :id AND user_id = :user_id"),
                    {"id": job_id, "user_id": self.user_id},
                ).first()
            if owned_job is None:
                raise PermissionError("Cette annonce n'appartient pas au compte connecté.")
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    INSERT INTO profile_jobs (profile_id, job_id)
                    VALUES (:profile_id, :job_id)
                    ON CONFLICT (profile_id, job_id) DO NOTHING
                    """
                ),
                {"profile_id": profile_id, "job_id": job_id},
            )
        return bool(result.rowcount)

    def has_job_match(self, job_id: int, profile_id: int) -> bool:
        """Indique si le matching propre à ce profil existe déjà."""
        self._require_profile(profile_id)
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    """
                    SELECT 1 FROM job_matches
                    WHERE job_id = :job_id AND profile_id = :profile_id
                    """
                ),
                {"job_id": job_id, "profile_id": profile_id},
            ).first() is not None

    def fetch_job(self, job_id: int) -> dict[str, Any] | None:
        """Relit une annonce complète pour sa fiche, son enrichissement ou son dossier."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM job_offers WHERE id = :id "
                    "AND (:user_id IS NULL OR user_id = :user_id)"
                ),
                {"id": job_id, "user_id": self.user_id},
            ).mappings().first()
        return dict(row) if row else None

    def fetch_job_offer(self, job_id: int) -> JobOffer | None:
        """Reconstruit l'objet métier complet d'une annonce enregistrée."""
        row = self.fetch_job(job_id)
        if row is None:
            return None
        return JobOffer(
            job_title=str(row.get("job_title") or ""),
            company_name=str(row.get("company_name") or ""),
            responsibilities=str(row.get("responsibilities") or ""),
            source_name=str(row.get("source_name") or "URL"),
            collector_name=str(row.get("collector_name") or ""),
            source_url=str(row.get("source_url") or ""),
            application_url=str(row.get("application_url") or ""),
            external_id=str(row.get("external_id") or ""),
            city=str(row.get("city") or ""),
            country=str(row.get("country") or "France"),
            remote_policy=str(row.get("remote_policy") or ""),
            contract_type=str(row.get("contract_type") or ""),
            work_schedule=str(row.get("work_schedule") or ""),
            experience_level=str(row.get("experience_level") or ""),
            salary_min=_clean(row.get("salary_min")),
            salary_max=_clean(row.get("salary_max")),
            salary_currency=str(row.get("salary_currency") or "EUR"),
            short_description=str(row.get("short_description") or ""),
            description_is_full=bool(row.get("description_is_full")),
            description_enrichment_source=str(
                row.get("description_enrichment_source") or ""
            ),
            description_enrichment_external_id=str(
                row.get("description_enrichment_external_id") or ""
            ),
            required_education=str(row.get("required_education") or ""),
            minimum_experience_years=_clean(
                row.get("minimum_experience_years")
            ),
            main_domain=str(row.get("main_domain") or ""),
            publication_date=row.get("publication_date"),
            application_deadline=row.get("application_deadline"),
            status=str(row.get("status") or "NOUVELLE"),
            detected_skills=ensure_list(row.get("required_skills")),
            detected_language=str(row.get("detected_language") or "fr"),
            language_confidence=_clean(row.get("language_confidence")),
            language_override=str(row.get("language_override") or ""),
        )

    def fetch_profiles(self) -> pd.DataFrame:
        """Liste les profils accessibles afin de permettre leur sélection dans l'interface."""
        return pd.read_sql(
            text(
                """
                SELECT * FROM candidate_profiles
                WHERE :user_id IS NULL OR user_id = :user_id
                ORDER BY is_active DESC, id
                """
            ),
            self.engine,
            params={"user_id": self.user_id},
        )

    def fetch_profile(self, profile_id: int, locale: str = "fr") -> CandidateProfile | None:
        """Reconstruit un profil dans la langue demandée pour matching ou génération."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT p.*, l.summary AS localized_summary,
                           l.target_job_titles AS localized_targets,
                           l.target_domains AS localized_domains,
                           l.translation_status
                    FROM candidate_profiles p
                    LEFT JOIN profile_localizations l
                      ON l.profile_id = p.id AND l.locale = :locale
                    WHERE p.id = :id
                      AND (:user_id IS NULL OR p.user_id = :user_id)
                    """
                ),
                {"id": profile_id, "locale": locale, "user_id": self.user_id},
            ).mappings().first()
        if not row:
            return None
        return CandidateProfile(
            id=int(row["id"]),
            profile_name=row["profile_name"],
            user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
            summary=row.get("localized_summary") or row.get("summary") or "",
            target_job_titles=ensure_list(
                row.get("localized_targets") or row.get("target_job_titles")
            ),
            preferred_contracts=ensure_list(row.get("preferred_contracts")),
            preferred_locations=ensure_list(row.get("preferred_locations")),
            remote_preferences=ensure_list(row.get("remote_preferences")),
            minimum_salary=_clean(row.get("minimum_salary")),
            cv_path=row.get("cv_path") or "",
            is_active=bool(row.get("is_active")),
            full_name=row.get("full_name") or "",
            email=row.get("email") or "",
            phone=row.get("phone") or "",
            address=row.get("address") or "",
            postal_code=row.get("postal_code") or "",
            home_city=row.get("home_city") or "",
            linkedin_url=row.get("linkedin_url") or "",
            github_url=row.get("github_url") or "",
            portfolio_url=row.get("portfolio_url") or "",
            # En attendant la première saisie anglaise, ces champs partagés
            # restent visibles pour que l'utilisateur puisse les reformuler ;
            # aucun texte n'est traduit automatiquement.
            target_domains=ensure_list(
                row.get("localized_domains") or row.get("target_domains")
            ),
            locale="en" if locale == "en" else "fr",
            onboarding_status=str(row.get("onboarding_status") or "COMPLETE"),
        )

    def fetch_active_profile(self) -> CandidateProfile | None:
        """Retourne le profil de recherche actif qui borne cockpit, veille et candidatures."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id FROM candidate_profiles
                    WHERE is_active = TRUE
                      AND (:user_id IS NULL OR user_id = :user_id)
                    ORDER BY id LIMIT 1
                    """
                ),
                {"user_id": self.user_id},
            ).first()
        return self.fetch_profile(int(row[0])) if row else None

    def fetch_skills(self, profile_id: int) -> list[dict[str, Any]]:
        """Relit les compétences validées qui alimentent matching et CV ciblé."""
        self._require_profile(profile_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT * FROM candidate_skills
                    WHERE profile_id = :profile_id
                    ORDER BY is_core_skill DESC, skill_category, skill_name
                    """
                ),
                {"profile_id": profile_id},
            ).mappings()
            return [dict(row) for row in rows]

    def create_profile(
        self, name: str, summary: str = "", onboarding_status: str = "COMPLETE"
    ) -> int:
        """Crée un profil de recherche isolé avant son parcours de complétion documentaire."""
        with self.engine.begin() as connection:
            profile_id = connection.execute(
                text(
                    """
                    INSERT INTO candidate_profiles (
                        user_id, profile_name, summary, onboarding_status
                    ) VALUES (:user_id, :name, :summary, :onboarding_status)
                    RETURNING id
                    """
                ),
                {
                    "user_id": self.user_id,
                    "name": name.strip(),
                    "summary": summary.strip() or None,
                    "onboarding_status": onboarding_status,
                },
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO profile_localizations (
                        profile_id, locale, summary, target_job_titles, target_domains
                    ) VALUES (:profile_id, 'fr', :summary, :targets, :domains)
                    ON CONFLICT (profile_id, locale) DO NOTHING
                    """
                ),
                {
                    "profile_id": profile_id,
                    "summary": summary.strip() or None,
                    "targets": self._list_value([]),
                    "domains": self._list_value([]),
                },
            )
        return int(profile_id)

    def update_profile(self, profile: CandidateProfile) -> None:
        """Persiste les préférences explicitement validées d'un profil Rocky."""
        self._require_profile(profile.id)
        values = asdict(profile)
        for name in (
            "target_job_titles",
            "preferred_contracts",
            "preferred_locations",
            "remote_preferences",
        ):
            values[name] = self._list_value(values[name])
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE candidate_profiles
                    SET profile_name = :profile_name,
                        summary = CASE WHEN :locale = 'fr' THEN :summary ELSE summary END,
                        target_job_titles = CASE WHEN :locale = 'fr' THEN :target_job_titles ELSE target_job_titles END,
                        preferred_contracts = :preferred_contracts,
                        preferred_locations = :preferred_locations,
                        remote_preferences = :remote_preferences,
                        minimum_salary = :minimum_salary,
                        full_name = :full_name,
                        email = :email,
                        phone = :phone,
                        address = :address,
                        postal_code = :postal_code,
                        home_city = :home_city,
                        linkedin_url = :linkedin_url,
                        github_url = :github_url,
                        portfolio_url = :portfolio_url,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND (:owner_id IS NULL OR user_id = :owner_id)
                    """
                ),
                {**values, "owner_id": self.user_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO profile_localizations (
                        profile_id, locale, summary, target_job_titles, target_domains,
                        translation_status, updated_at
                    ) VALUES (
                        :profile_id, :locale, :summary, :targets, :domains,
                        :translation_status, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (profile_id, locale) DO UPDATE SET
                        summary = excluded.summary,
                        target_job_titles = excluded.target_job_titles,
                        target_domains = excluded.target_domains,
                        translation_status = excluded.translation_status,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "profile_id": profile.id,
                    "locale": profile.locale,
                    "summary": profile.summary or None,
                    "targets": self._list_value(profile.target_job_titles),
                    "domains": self._list_value(profile.target_domains),
                    "translation_status": "ready",
                },
            )
            # Les deux versions sont désormais saisies et importées séparément.
            # Une retouche française ne doit donc pas invalider artificiellement
            # les libellés anglais relus par la personne.

    def set_active_profile(self, profile_id: int) -> None:
        """Désigne le profil qui pilote les vues et prochaines veilles de l'utilisateur."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE candidate_profiles SET is_active = FALSE "
                    "WHERE :user_id IS NULL OR user_id = :user_id"
                ),
                {"user_id": self.user_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE candidate_profiles
                    SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND (:user_id IS NULL OR user_id = :user_id)
                    """
                ),
                {"id": profile_id, "user_id": self.user_id},
            )

    def save_cv_path(self, profile_id: int, relative_path: str) -> None:
        """Mémorise le CV source contrôlé du profil, sans modifier le fichier lui-même."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE candidate_profiles
                    SET cv_path = :path, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": profile_id, "path": relative_path},
            )

    def complete_profile(self, profile_id: int, activate: bool = True) -> None:
        """Termine un brouillon sans modifier le profil actif avant validation."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE candidate_profiles SET onboarding_status = 'COMPLETE', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": profile_id},
            )
        if activate:
            self.set_active_profile(profile_id)

    def fetch_localization(
        self, profile_id: int, locale: str
    ) -> ProfileLocalization | None:
        """Lit une version linguistique après contrôle du propriétaire."""
        self._require_profile(profile_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM profile_localizations "
                    "WHERE profile_id = :profile_id AND locale = :locale"
                ),
                {"profile_id": profile_id, "locale": locale},
            ).mappings().first()
        if row is None:
            return None
        return ProfileLocalization(
            profile_id=profile_id,
            locale="en" if locale == "en" else "fr",
            summary=str(row.get("summary") or ""),
            target_job_titles=tuple(ensure_list(row.get("target_job_titles"))),
            target_domains=tuple(ensure_list(row.get("target_domains"))),
            translation_status=str(row.get("translation_status") or "ready"),
            source_hash=str(row.get("source_hash") or ""),
        )

    def save_profile_analysis(
        self, profile_id: int, analysis: ProfileAnalysis, status: str = "ready"
    ) -> None:
        """Persiste le préremplissage afin qu'un brouillon survive à la session."""
        self._require_profile(profile_id)
        payload = json.dumps(asdict(analysis), ensure_ascii=False)
        payload_parameter = ":payload" if self.is_sqlite else "CAST(:payload AS JSONB)"
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    INSERT INTO profile_analyses (
                        profile_id, analysis_data, status, updated_at
                    ) VALUES (:profile_id, {payload_parameter}, :status, CURRENT_TIMESTAMP)
                    ON CONFLICT (profile_id) DO UPDATE SET
                        analysis_data = EXCLUDED.analysis_data,
                        status = EXCLUDED.status,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {"profile_id": profile_id, "payload": payload, "status": status},
            )

    def fetch_profile_analysis(self, profile_id: int) -> ProfileAnalysis | None:
        """Relit un inventaire sans exposer celui d'un autre compte."""
        self._require_profile(profile_id)
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT analysis_data FROM profile_analyses "
                    "WHERE profile_id = :profile_id"
                ),
                {"profile_id": profile_id},
            ).scalar_one_or_none()
        if value is None:
            return None
        data = json.loads(value) if isinstance(value, str) else dict(value)

        def values(name: str) -> tuple[str, ...]:
            """Convertit les listes JSON historiques en tuples stables du modèle de profil."""
            return tuple(str(item) for item in data.get(name, []) if str(item).strip())

        return ProfileAnalysis(
            full_name=str(data.get("full_name") or ""),
            email=str(data.get("email") or ""),
            phone=str(data.get("phone") or ""),
            summary=str(data.get("summary") or ""),
            target_job_titles=values("target_job_titles"),
            target_domains=values("target_domains"),
            skills=values("skills"),
            skill_levels=tuple(
                (str(pair[0]), str(pair[1]))
                for pair in data.get("skill_levels", [])
                if isinstance(pair, (list, tuple)) and len(pair) == 2
            ),
            career_items=values("career_items"),
            project_evidence=values("project_evidence"),
            warnings=values("warnings"),
        )

    def save_localization(self, localization: ProfileLocalization) -> None:
        """Crée ou met à jour une traduction validée par l'utilisateur."""
        self._require_profile(localization.profile_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO profile_localizations (
                        profile_id, locale, summary, target_job_titles,
                        target_domains, translation_status, source_hash, updated_at
                    ) VALUES (
                        :profile_id, :locale, :summary, :targets, :domains,
                        :status, :source_hash, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (profile_id, locale) DO UPDATE SET
                        summary = excluded.summary,
                        target_job_titles = excluded.target_job_titles,
                        target_domains = excluded.target_domains,
                        translation_status = excluded.translation_status,
                        source_hash = excluded.source_hash,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "profile_id": localization.profile_id,
                    "locale": localization.locale,
                    "summary": localization.summary or None,
                    "targets": self._list_value(list(localization.target_job_titles)),
                    "domains": self._list_value(list(localization.target_domains)),
                    "status": localization.translation_status,
                    "source_hash": localization.source_hash or None,
                },
            )

    def save_profile_document(
        self,
        profile_id: int,
        locale: str,
        kind: str,
        source_path: str,
        sha256: str,
        *,
        preview_pdf_path: str = "",
        origin: str = "uploaded",
        status: str = "ready",
        source_hash: str = "",
    ) -> None:
        """Versionne le document courant sans autoriser un écrasement inter-compte."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            next_version = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) + 1 FROM profile_documents "
                        "WHERE profile_id = :profile_id AND locale = :locale "
                        "AND kind = :kind"
                    ),
                    {"profile_id": profile_id, "locale": locale, "kind": kind},
                ).scalar_one()
            )
            connection.execute(
                text(
                    """
                    UPDATE profile_documents SET is_current = FALSE,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = :profile_id AND locale = :locale
                      AND kind = :kind AND is_current = TRUE
                    """
                ),
                {"profile_id": profile_id, "locale": locale, "kind": kind},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO profile_documents (
                        profile_id, locale, kind, source_path, preview_pdf_path,
                        origin, status, sha256, source_hash, version, is_current,
                        updated_at
                    ) VALUES (
                        :profile_id, :locale, :kind, :source_path, :preview_path,
                        :origin, :status, :sha256, :source_hash, :version, TRUE,
                        CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "profile_id": profile_id,
                    "locale": locale,
                    "kind": kind,
                    "source_path": source_path,
                    "preview_path": preview_pdf_path or None,
                    "origin": origin,
                    "status": status,
                    "sha256": sha256,
                    "source_hash": source_hash or None,
                    "version": next_version,
                },
            )
            # Les documents anglais sont des imports autonomes. Un remplacement
            # français ne modifie ni leur contenu ni leur état de validation.

    def fetch_profile_documents(
        self, profile_id: int, locale: str | None = None
    ) -> list[ProfileDocument]:
        """Retourne uniquement les documents du profil contrôlé."""
        self._require_profile(profile_id)
        condition = "AND locale = :locale" if locale else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT * FROM profile_documents WHERE profile_id = :profile_id "
                    f"AND is_current = TRUE "
                    f"{condition} ORDER BY locale, kind"
                ),
                {"profile_id": profile_id, "locale": locale},
            ).mappings().all()
        return [
            ProfileDocument(
                id=int(row["id"]),
                profile_id=profile_id,
                locale="en" if row["locale"] == "en" else "fr",
                kind=str(row["kind"]),
                source_path=str(row["source_path"]),
                preview_pdf_path=str(row.get("preview_pdf_path") or ""),
                origin=str(row["origin"]),
                status=str(row["status"]),
                sha256=str(row["sha256"]),
                source_hash=str(row.get("source_hash") or ""),
                version=int(row.get("version") or 1),
                is_current=bool(row.get("is_current", True)),
            )
            for row in rows
        ]

    def validate_profile_document(
        self, profile_id: int, locale: str, kind: str
    ) -> None:
        """Enregistre la revue humaine d'un document importé devenu ancien."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE profile_documents SET status = 'ready',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = :profile_id AND locale = :locale
                      AND kind = :kind AND origin = 'uploaded'
                      AND is_current = TRUE
                    """
                ),
                {"profile_id": profile_id, "locale": locale, "kind": kind},
            )
        if not result.rowcount:
            raise ValueError("Seul un document importé peut être validé manuellement.")

    def set_job_language(self, job_id: int, locale: str | None) -> None:
        """Enregistre une correction humaine FR/EN, ou rétablit l'automatique."""
        if locale not in {None, "fr", "en"}:
            raise ValueError("La langue doit être fr, en ou automatique.")
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE job_offers SET language_override = :locale, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :id "
                    "AND (:user_id IS NULL OR user_id = :user_id)"
                ),
                {"locale": locale, "id": job_id, "user_id": self.user_id},
            )
        if self.user_id is not None and not result.rowcount:
            raise PermissionError("Cette annonce n'appartient pas au compte connecté.")

    def profile_for_offer(
        self, profile_id: int, offer: JobOffer
    ) -> CandidateProfile | None:
        """Sélectionne la localisation effective avant matching ou génération."""
        self._require_profile(profile_id)
        if offer.detected_language not in {"fr", "en"}:
            detection = detect_language(f"{offer.job_title}\n{offer.responsibilities}")
            offer.detected_language = detection.locale
            offer.language_confidence = detection.confidence
        locale = offer.language_override or offer.detected_language or "fr"
        return self.fetch_profile(profile_id, locale)

    def add_skill(
        self,
        profile_id: int,
        name: str,
        category: str,
        level: str = "",
        years: float | None = None,
        is_core: bool = False,
        name_en: str = "",
    ) -> None:
        """Ajoute une compétence validée au profil pour enrichir les futurs matching."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO candidate_skills (
                        profile_id, skill_name, skill_name_en, skill_category,
                        skill_level, years_experience, is_core_skill
                    ) VALUES (
                        :profile_id, :name, :name_en, :category, :level, :years, :is_core
                    )
                    """
                ),
                {
                    "profile_id": profile_id,
                    "name": name.strip(),
                    "name_en": name_en.strip() or None,
                    "category": category,
                    "level": level or None,
                    "years": years,
                    "is_core": is_core,
                },
            )

    def update_skill(
        self,
        skill_id: int,
        profile_id: int,
        name: str,
        category: str,
        level: str = "",
        years: float | None = None,
        is_core: bool = False,
        name_en: str = "",
    ) -> bool:
        """Met à jour une compétence du profil sans contourner son isolement utilisateur."""
        self._require_profile(profile_id)
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE candidate_skills
                    SET skill_name = :name,
                        skill_name_en = :name_en,
                        skill_category = :category,
                        skill_level = :level,
                        years_experience = :years,
                        is_core_skill = :is_core
                    WHERE id = :skill_id AND profile_id = :profile_id
                    """
                ),
                {
                    "skill_id": skill_id,
                    "profile_id": profile_id,
                    "name": name.strip(),
                    "name_en": name_en.strip() or None,
                    "category": category,
                    "level": level or None,
                    "years": years,
                    "is_core": is_core,
                },
            )
        return bool(result.rowcount)

    def set_skill_translation(self, skill_id: int, name_en: str) -> None:
        """Attache un libellé anglais à l'identité canonique de la compétence."""
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE candidate_skills SET skill_name_en = :name_en
                    WHERE id = :id AND EXISTS (
                        SELECT 1 FROM candidate_profiles p
                        WHERE p.id = candidate_skills.profile_id
                          AND (:user_id IS NULL OR p.user_id = :user_id)
                    )
                    """
                ),
                {"id": skill_id, "name_en": name_en.strip(), "user_id": self.user_id},
            )
        if self.user_id is not None and not result.rowcount:
            raise PermissionError("Cette compétence n'appartient pas au compte connecté.")

    def delete_skill(self, skill_id: int) -> None:
        """Retire une compétence lorsque l'utilisateur la juge non pertinente pour son profil."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM candidate_skills WHERE id = :id AND EXISTS ("
                    "SELECT 1 FROM candidate_profiles p "
                    "WHERE p.id = candidate_skills.profile_id "
                    "AND (:user_id IS NULL OR p.user_id = :user_id))"
                ),
                {"id": skill_id, "user_id": self.user_id},
            )

    def find_duplicate(self, offer: JobOffer) -> int | None:
        """Cherche l'annonce équivalente pour éviter de dupliquer une opportunité du flux."""
        conditions = []
        params: dict[str, Any] = {"user_id": self.user_id}
        if offer.external_id:
            conditions.append(
                "(source_name = :source_name AND external_id = :external_id)"
            )
            params.update(
                source_name=offer.source_name, external_id=offer.external_id
            )
        if offer.source_url:
            conditions.append(
                "(source_url = :source_url OR application_url = :source_url)"
            )
            params["source_url"] = canonical_url(offer.source_url)
        if offer.application_url:
            conditions.append(
                "(application_url = :application_url "
                "OR source_url = :application_url)"
            )
            params["application_url"] = canonical_url(offer.application_url)
        if not conditions:
            return None
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id FROM job_offers WHERE "
                    "(:user_id IS NULL OR user_id = :user_id) AND ("
                    + " OR ".join(conditions) + ")"
                    + " ORDER BY id LIMIT 1"
                ),
                params,
            ).first()
        return int(row[0]) if row else None

    def insert_job(
        self, offer: JobOffer, profile_id: int | None = None
    ) -> tuple[int, bool]:
        """Ajoute une annonce ou retourne son identifiant dédupliqué, puis la lie au profil."""
        duplicate_id = self.find_duplicate(offer)
        if duplicate_id is not None:
            if profile_id is not None:
                self.link_job_to_profile(duplicate_id, profile_id)
            return duplicate_id, False

        if offer.detected_language not in {"fr", "en"}:
            detection = detect_language(f"{offer.job_title}\n{offer.responsibilities}")
            offer.detected_language = detection.locale
            offer.language_confidence = detection.confidence
        values = offer.to_dict()
        values["source_url"] = (
            canonical_url(offer.source_url) if offer.source_url else None
        )
        values["application_url"] = (
            canonical_url(offer.application_url)
            if offer.application_url
            else values["source_url"]
        )
        for key, value in list(values.items()):
            values[key] = _clean(value)
        values.update(
            user_id=self.user_id,
            required_skills=self._list_value(offer.detected_skills),
            preferred_skills=self._list_value([]),
            programming_languages=self._list_value([]),
            technical_tools=self._list_value([]),
            soft_skills=self._list_value([]),
            languages_required=self._list_value([]),
            keywords=self._list_value([]),
        )
        with self.engine.begin() as connection:
            job_id = connection.execute(
                text(
                    """
                    INSERT INTO job_offers (
                        user_id, external_id, source_name, collector_name,
                        source_url, application_url,
                        job_title, company_name, city, country, remote_policy,
                        contract_type, work_schedule, experience_level,
                        salary_min, salary_max,
                        salary_currency, short_description,
                        description_is_full, description_enrichment_source,
                        description_enrichment_external_id, responsibilities,
                        required_skills, preferred_skills, required_education,
                        minimum_experience_years, main_domain,
                        programming_languages, technical_tools, soft_skills,
                        languages_required, keywords, publication_date,
                        application_deadline, status, detected_language,
                        language_confidence, language_override
                    ) VALUES (
                        :user_id, :external_id, :source_name, :collector_name,
                        :source_url, :application_url,
                        :job_title, :company_name, :city, :country, :remote_policy,
                        :contract_type, :work_schedule, :experience_level,
                        :salary_min, :salary_max,
                        :salary_currency, :short_description,
                        :description_is_full, :description_enrichment_source,
                        :description_enrichment_external_id, :responsibilities,
                        :required_skills, :preferred_skills, :required_education,
                        :minimum_experience_years, :main_domain,
                        :programming_languages, :technical_tools, :soft_skills,
                        :languages_required, :keywords, :publication_date,
                        :application_deadline, :status, :detected_language,
                        :language_confidence, :language_override
                    ) RETURNING id
                    """
                ),
                values,
            ).scalar_one()
        job_id = int(job_id)
        if profile_id is not None:
            self.link_job_to_profile(job_id, profile_id)
        return job_id, True

    def save_match(
        self, job_id: int, profile_id: int, result: MatchResult
    ) -> None:
        """Enregistre le score courant et ajoute son instantané à l'historique.

        La table ``job_matches`` reste volontairement une vue rapide de la
        dernière analyse. ``job_match_history`` ne subit aucune mise à jour :
        chaque appel, y compris un recalcul identique, représente un essai
        daté et comparable par version de moteur.
        """
        self.link_job_to_profile(job_id, profile_id)
        breakdown_parameter = ":breakdown"
        if not self.is_sqlite:
            breakdown_parameter = "CAST(:breakdown AS JSONB)"
        values = {
            "job_id": job_id,
            "profile_id": profile_id,
            "score": result.score,
            "breakdown": json.dumps(result.breakdown, ensure_ascii=False),
            "strengths": self._list_value(result.strengths),
            "gaps": self._list_value(result.gaps),
            "profile_locale": result.profile_locale,
            "scoring_version": result.scoring_version,
        }
        query = f"""
            INSERT INTO job_matches (
                job_id, profile_id, score, breakdown, strengths, gaps, profile_locale
            ) VALUES (
                :job_id, :profile_id, :score,
                {breakdown_parameter}, :strengths, :gaps, :profile_locale
            )
            ON CONFLICT (job_id, profile_id) DO UPDATE SET
                score = EXCLUDED.score,
                breakdown = EXCLUDED.breakdown,
                strengths = EXCLUDED.strengths,
                gaps = EXCLUDED.gaps,
                profile_locale = EXCLUDED.profile_locale,
                analyzed_at = CURRENT_TIMESTAMP
        """
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    INSERT INTO job_match_history (
                        job_id, profile_id, score, breakdown, strengths, gaps,
                        profile_locale, scoring_version
                    ) VALUES (
                        :job_id, :profile_id, :score, {breakdown_parameter},
                        :strengths, :gaps, :profile_locale, :scoring_version
                    )
                    """
                ),
                values,
            )
            connection.execute(
                text(query),
                values,
            )
            # Le recalcul peut découvrir de nouvelles compétences dans la
            # description. On les conserve sur l'annonce pour que le tableau,
            # les prochains affichages et les futurs calculs restent cohérents.
            if result.detected_job_skills:
                connection.execute(
                    text(
                        """
                        UPDATE job_offers
                        SET required_skills = :required_skills,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :job_id
                        """
                    ),
                    {
                        "job_id": job_id,
                        "required_skills": self._list_value(
                            result.detected_job_skills
                        ),
                    },
                )

    def fetch_match_history(self, job_id: int, profile_id: int) -> pd.DataFrame:
        """Retourne la chronologie des scores d'une annonce pour un profil.

        Cette lecture bornée est destinée aux futures analyses ou exports : le
        score actif ne doit pas être utilisé à la place de ses recalculs.
        """
        self._require_profile(profile_id)
        return pd.read_sql(
            text(
                """
                SELECT * FROM job_match_history
                WHERE job_id = :job_id AND profile_id = :profile_id
                ORDER BY analyzed_at ASC, id ASC
                """
            ),
            self.engine,
            params={"job_id": job_id, "profile_id": profile_id},
        )

    def recalculate_profile_matches(self, profile_id: int) -> dict[str, int]:
        """Recalcule tous les scores complets d'un profil, sans toucher aux offres.

        Le profil peut avoir changé (compétence, préférence ou projet) alors
        que les annonces historiques restent identiques. Seules les annonces
        dont la description est complète sont recalculées, conformément à la
        règle du cockpit ; les annonces incomplètes restent dans la file
        d'enrichissement et ne reçoivent pas un score artificiel.
        """
        from .matching import calculate_match

        skills = self.fetch_skills(profile_id)
        profile = self.fetch_profile(profile_id)
        if profile is None:
            return {
                "recalculated": 0,
                "skipped": 0,
                "incomplete": 0,
                "unavailable": 0,
            }
        jobs = self.fetch_jobs(profile_id)
        recalculated = 0
        incomplete = 0
        unavailable = 0
        for _, row in jobs.iterrows():
            if not bool(row.get("description_is_full")):
                incomplete += 1
                continue
            offer = self.fetch_job_offer(int(row["id"]))
            if offer is None:
                unavailable += 1
                continue
            locale = (
                offer.language_override or offer.detected_language or "fr"
            )
            localized_profile = self.fetch_profile(profile_id, locale) or profile
            result = calculate_match(offer, localized_profile, skills)
            self.save_match(int(row["id"]), profile_id, result)
            recalculated += 1
        return {
            "recalculated": recalculated,
            # ``skipped`` reste disponible pour les anciens appels et scripts.
            "skipped": incomplete + unavailable,
            "incomplete": incomplete,
            "unavailable": unavailable,
        }

    def recalculate_job_match(self, job_id: int, profile_id: int) -> MatchResult | None:
        """Recalcule une annonce après correction de sa langue effective."""
        from .matching import calculate_match

        self._require_profile(profile_id)
        offer = self.fetch_job_offer(job_id)
        if offer is None or not self.fetch_job(job_id).get("description_is_full"):
            return None
        locale = offer.language_override or offer.detected_language or "fr"
        profile = self.fetch_profile(profile_id, locale)
        if profile is None:
            return None
        result = calculate_match(offer, profile, self.fetch_skills(profile_id))
        self.save_match(job_id, profile_id, result)
        return result

    def update_job_status(self, job_id: int, status: str) -> None:
        """Change le statut métier d'une annonce depuis un flux explicitement autorisé."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE job_offers
                    SET status = :status, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND (:user_id IS NULL OR user_id = :user_id)
                    """
                ),
                {"id": job_id, "status": status, "user_id": self.user_id},
            )

    def apply_stale_new_job_policy(
        self, reference_date: date | None = None
    ) -> dict[str, int]:
        """Classe les nouvelles annonces selon leur ancienneté de publication.

        Seules les annonces encore au statut ``NOUVELLE`` sont concernées : une
        candidature préparée, envoyée ou étudiée ne peut donc pas être modifiée
        par cette politique. Les bornes calendaires sont inclusives : 8 à 14
        jours deviennent ``ANCIENNE`` et 15 jours ou plus deviennent
        ``ÉCARTÉE``. Une date inconnue reste volontairement inchangée.
        """
        today = reference_date or date.today()
        ancient_start = today - timedelta(days=14)
        ancient_end = today - timedelta(days=8)
        discarded_before = today - timedelta(days=15)
        scope = "(:user_id IS NULL OR user_id = :user_id)"
        with self.engine.begin() as connection:
            discarded = connection.execute(
                text(
                    f"""
                    UPDATE job_offers
                    SET status = 'ÉCARTÉE', updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'NOUVELLE'
                      AND publication_date IS NOT NULL
                      AND publication_date <= :discarded_before
                      AND {scope}
                    """
                ),
                {
                    "discarded_before": discarded_before,
                    "user_id": self.user_id,
                },
            )
            ancient = connection.execute(
                text(
                    f"""
                    UPDATE job_offers
                    SET status = 'ANCIENNE', updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'NOUVELLE'
                      AND publication_date BETWEEN :ancient_start AND :ancient_end
                      AND {scope}
                    """
                ),
                {
                    "ancient_start": ancient_start,
                    "ancient_end": ancient_end,
                    "user_id": self.user_id,
                },
            )
        return {
            "ancient_count": max(0, int(ancient.rowcount or 0)),
            "discarded_count": max(0, int(discarded.rowcount or 0)),
        }

    def update_job_field(self, job_id: int, field: str, value: str) -> bool:
        """Corrige un champ éditable via une liste blanche stricte."""
        allowed = {
            "job_title",
            "company_name",
            "city",
            "remote_policy",
            "contract_type",
            "work_schedule",
            "application_url",
        }
        if field not in allowed:
            raise ValueError(f"Champ d'annonce non modifiable : {field}")
        cleaned = value.strip()
        if not cleaned:
            return False
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    f"UPDATE job_offers SET {field} = :value, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :id "
                    "AND (:user_id IS NULL OR user_id = :user_id)"
                ),
                {"id": job_id, "value": cleaned, "user_id": self.user_id},
            )
        return bool(result.rowcount)

    def update_jobs_status(self, job_ids: list[int], status: str) -> int:
        """Applique un statut à plusieurs annonces dans une transaction."""
        unique_ids = list(dict.fromkeys(int(job_id) for job_id in job_ids))
        if not unique_ids:
            return 0
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE job_offers
                    SET status = :status, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND (:user_id IS NULL OR user_id = :user_id)
                    """
                ),
                [
                    {"id": job_id, "status": status, "user_id": self.user_id}
                    for job_id in unique_ids
                ],
            )
        return max(0, int(result.rowcount or 0))

    def delete_discarded_jobs(self, job_ids: list[int]) -> dict[str, int]:
        """Supprime seulement des annonces écartées et sans candidature liée.

        Cette opération est volontairement plus stricte qu'un simple ``DELETE`` :
        une annonce suivie par une candidature ou encore active ne peut jamais
        disparaître depuis le flux. Les autres relations techniques (matching,
        profil-annonce) sont supprimées par les contraintes SQL prévues à cet
        effet.
        """
        unique_ids = list(dict.fromkeys(int(job_id) for job_id in job_ids))
        summary = {"deleted": 0, "not_discarded": 0, "linked_to_application": 0}
        if not unique_ids:
            return summary
        with self.engine.begin() as connection:
            for job_id in unique_ids:
                row = connection.execute(
                    text(
                        """
                        SELECT j.status,
                               EXISTS(
                                   SELECT 1 FROM applications a
                                   WHERE a.job_id = j.id
                               ) AS has_application
                        FROM job_offers j
                        WHERE j.id = :id
                          AND (:user_id IS NULL OR j.user_id = :user_id)
                        """
                    ),
                    {"id": job_id, "user_id": self.user_id},
                ).mappings().first()
                if row is None:
                    continue
                if str(row["status"] or "") != "ÉCARTÉE":
                    summary["not_discarded"] += 1
                    continue
                if bool(row["has_application"]):
                    summary["linked_to_application"] += 1
                    continue
                result = connection.execute(
                    text(
                        "DELETE FROM job_offers WHERE id = :id "
                        "AND (:user_id IS NULL OR user_id = :user_id)"
                    ),
                    {"id": job_id, "user_id": self.user_id},
                )
                summary["deleted"] += max(0, int(result.rowcount or 0))
        return summary

    def update_job(self, job_id: int, offer: JobOffer) -> None:
        """Met à jour les champs éditables d'une annonce existante.

        L'identifiant interne, l'identifiant fourni par la plateforme et les
        candidatures liées ne sont jamais modifiés. Cette frontière évite
        qu'une correction manuelle ne casse la déduplication ou l'historique.
        """
        values = offer.to_dict()
        values.update(
            id=job_id,
            source_url=(
                canonical_url(offer.source_url) if offer.source_url else None
            ),
            application_url=(
                canonical_url(offer.application_url)
                if offer.application_url
                else canonical_url(offer.source_url)
                if offer.source_url
                else None
            ),
            required_skills=self._list_value(offer.detected_skills),
        )
        for key, value in list(values.items()):
            values[key] = _clean(value)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE job_offers
                    SET source_name = :source_name,
                        collector_name = :collector_name,
                        source_url = :source_url,
                        application_url = :application_url,
                        job_title = :job_title,
                        company_name = :company_name,
                        city = :city,
                        country = :country,
                        remote_policy = :remote_policy,
                        contract_type = :contract_type,
                        work_schedule = :work_schedule,
                        experience_level = :experience_level,
                        salary_min = :salary_min,
                        salary_max = :salary_max,
                        salary_currency = :salary_currency,
                        short_description = :short_description,
                        description_is_full = :description_is_full,
                        description_enrichment_source = :description_enrichment_source,
                        description_enrichment_external_id = :description_enrichment_external_id,
                        responsibilities = :responsibilities,
                        required_skills = :required_skills,
                        required_education = :required_education,
                        minimum_experience_years = :minimum_experience_years,
                        main_domain = :main_domain,
                        detected_language = :detected_language,
                        language_confidence = :language_confidence,
                        language_override = :language_override,
                        publication_date = :publication_date,
                        application_deadline = :application_deadline,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND (:owner_id IS NULL OR user_id = :owner_id)
                    """
                ),
                {**values, "owner_id": self.user_id},
            )

    def update_job_if_changed(self, job_id: int, offer: JobOffer) -> bool:
        """Actualise une annonce uniquement lorsque ses données ont changé."""
        current = self.fetch_job_offer(job_id)
        if current is None:
            return False
        compared_fields = (
            "source_name",
            "collector_name",
            "source_url",
            "application_url",
            "job_title",
            "company_name",
            "city",
            "country",
            "remote_policy",
            "contract_type",
            "work_schedule",
            "experience_level",
            "salary_min",
            "salary_max",
            "salary_currency",
            "short_description",
            "description_is_full",
            "description_enrichment_source",
            "description_enrichment_external_id",
            "responsibilities",
            "required_education",
            "minimum_experience_years",
            "main_domain",
            "publication_date",
            "application_deadline",
            "detected_skills",
        )
        if all(
            getattr(current, field) == getattr(offer, field)
            for field in compared_fields
        ):
            return False
        self.update_job(job_id, offer)
        return True

    def create_application(
        self,
        job_id: int,
        profile_id: int,
        cv_path: str,
        docx_path: str | None,
        pdf_path: str,
        profile_locale: str = "fr",
    ) -> int:
        """Crée le dossier de candidature qui relie offre, profil et documents générés."""
        self.link_job_to_profile(job_id, profile_id)
        with self.engine.begin() as connection:
            application_id = connection.execute(
                text(
                    """
                    INSERT INTO applications (
                        job_id, profile_id, cv_path,
                        letter_docx_path, letter_pdf_path, profile_locale
                    ) VALUES (
                        :job_id, :profile_id, :cv_path, :docx_path, :pdf_path,
                        :profile_locale
                    ) RETURNING id
                    """
                ),
                {
                    "job_id": job_id,
                    "profile_id": profile_id,
                    "cv_path": cv_path,
                    "docx_path": docx_path or ("" if self.is_sqlite else None),
                    "pdf_path": pdf_path,
                    "profile_locale": profile_locale,
                },
            ).scalar_one()
            connection.execute(
                text(
                    """
                    UPDATE job_offers
                    SET status = 'RETENUE', updated_at = CURRENT_TIMESTAMP
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
            details_parameter = ":details" if self.is_sqlite else "CAST(:details AS JSONB)"
            connection.execute(
                text(
                    f"""
                    INSERT INTO application_events (
                        application_id, event_type, new_status, source, details
                    ) VALUES (
                        :application_id, 'CREATED', 'DOSSIER PRÉPARÉ',
                        'USER', {details_parameter}
                    )
                    """
                ),
                {
                    "application_id": application_id,
                    "details": "{}",
                },
            )
        return int(application_id)

    def fetch_applications(self, profile_id: int | None = None) -> pd.DataFrame:
        """Liste les dossiers suivis, sans remettre les annonces écartées en pile.

        Les dossiers écartés ne sont pas supprimés : leurs documents et leur
        chronologie restent consultables en base. Les exclure ici empêche
        toutefois un ancien dossier, ou une annonce écartée depuis sa fiche,
        de réapparaître dans le carrousel « Mes candidatures ».
        """
        return pd.read_sql(
            text(
                """
                SELECT a.*, j.job_title, j.company_name, j.application_url,
                       j.source_name, m.score AS match_score
                FROM applications a
                JOIN job_offers j ON j.id = a.job_id
                LEFT JOIN job_matches m
                    ON m.job_id = a.job_id AND m.profile_id = a.profile_id
                WHERE (:user_id IS NULL OR j.user_id = :user_id)
                  AND (:profile_id IS NULL OR a.profile_id = :profile_id)
                  AND j.status <> 'ÉCARTÉE'
                  AND a.status NOT IN ('ÉCARTÉE', 'RETIRÉE')
                ORDER BY a.prepared_at DESC
                """
            ),
            self.engine,
            params={"profile_id": profile_id, "user_id": self.user_id},
        )

    def fetch_application(self, application_id: int) -> dict[str, Any] | None:
        """Retourne un dossier avec l'annonce et l'identité du profil."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT a.*, j.job_title, j.company_name,
                           j.application_url, j.source_url,
                           p.full_name, p.email, p.phone, p.address,
                           p.postal_code, p.home_city, p.linkedin_url,
                           p.github_url, p.portfolio_url
                    FROM applications a
                    JOIN job_offers j ON j.id = a.job_id
                    JOIN candidate_profiles p ON p.id = a.profile_id
                    WHERE a.id = :id
                      AND (:user_id IS NULL OR p.user_id = :user_id)
                    """
                ),
                {"id": application_id, "user_id": self.user_id},
            ).mappings().first()
        return dict(row) if row else None

    def fetch_latest_application_for_job(
        self, job_id: int, profile_id: int
    ) -> dict[str, Any] | None:
        """Évite de dupliquer un dossier lors d'une nouvelle version PDF."""
        self._require_profile(profile_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM applications
                    WHERE job_id = :job_id AND profile_id = :profile_id
                    ORDER BY prepared_at DESC, id DESC LIMIT 1
                    """
                ),
                {"job_id": job_id, "profile_id": profile_id},
            ).mappings().first()
        return dict(row) if row else None

    def update_application_paths(
        self, application_id: int, cv_path: str, letter_pdf_path: str,
        profile_locale: str = "fr",
    ) -> None:
        """Pointe le dossier vers sa dernière paire de PDF validée."""
        self._require_application(application_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE applications
                    SET cv_path = :cv_path,
                        letter_pdf_path = :letter_pdf_path,
                        profile_locale = :profile_locale,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {
                    "id": application_id,
                    "cv_path": cv_path,
                    "letter_pdf_path": letter_pdf_path,
                    "profile_locale": profile_locale,
                },
            )

    def update_application_status(
        self,
        application_id: int,
        status: str,
        source: str = "USER",
        confidence: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Met à jour, audite puis synchronise le statut de l'annonce."""
        self._require_application(application_id)
        status = normalize_application_status(status)
        details_value = json.dumps(details or {}, ensure_ascii=False, default=str)
        with self.engine.begin() as connection:
            current = connection.execute(
                text("SELECT status, job_id FROM applications WHERE id = :id"),
                {"id": application_id},
            ).mappings().one()
            old_status = str(current["status"])
            job_id = int(current["job_id"])
            connection.execute(
                text(
                    """
                    UPDATE applications
                    SET status = :status,
                        status_source = :source,
                        updated_at = CURRENT_TIMESTAMP,
                        applied_at = CASE
                            WHEN :mark_sent THEN CURRENT_TIMESTAMP
                            ELSE applied_at
                        END
                    WHERE id = :id
                    RETURNING job_id
                    """
                ),
                {
                    "id": application_id,
                    "status": status,
                    "source": source,
                    "mark_sent": status == "CANDIDATURE ENVOYÉE",
                },
            )
            details_parameter = ":details" if self.is_sqlite else "CAST(:details AS JSONB)"
            event_id = connection.execute(
                text(
                    f"""
                    INSERT INTO application_events (
                        application_id, event_type, old_status, new_status,
                        source, confidence, details
                    ) VALUES (
                        :application_id, 'STATUS_CHANGED', :old_status,
                        :new_status, :source, :confidence, {details_parameter}
                    ) RETURNING id
                    """
                ),
                {
                    "application_id": application_id,
                    "old_status": old_status,
                    "new_status": status,
                    "source": source,
                    "confidence": confidence,
                    "details": details_value,
                },
            ).scalar_one()
            if status in APPLICATION_TO_JOB_STATUS:
                connection.execute(
                    text(
                        """
                        UPDATE job_offers
                        SET status = :status, updated_at = CURRENT_TIMESTAMP
                        WHERE id = :job_id
                        """
                    ),
                    {
                        "job_id": job_id,
                        "status": APPLICATION_TO_JOB_STATUS[status],
                    },
                )
        return int(event_id)

    def fetch_application_events(self, application_id: int) -> pd.DataFrame:
        """Retourne la chronologie complète, y compris les événements annulés."""
        self._require_application(application_id)
        return pd.read_sql(
            text(
                """
                SELECT * FROM application_events
                WHERE application_id = :application_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            self.engine,
            params={"application_id": application_id},
        )

    def revert_application_event(self, event_id: int) -> bool:
        """Annule la dernière transition en restaurant son ancien statut."""
        with self.engine.connect() as connection:
            application_id = connection.execute(
                text("SELECT application_id FROM application_events WHERE id = :id"),
                {"id": event_id},
            ).scalar_one_or_none()
        if application_id is None:
            return False
        self._require_application(int(application_id))
        with self.engine.begin() as connection:
            event = connection.execute(
                text(
                    """
                    SELECT * FROM application_events
                    WHERE id = :id AND reverted_at IS NULL
                      AND event_type = 'STATUS_CHANGED'
                    """
                ),
                {"id": event_id},
            ).mappings().first()
            if not event or not event.get("old_status"):
                return False
            latest = connection.execute(
                text(
                    """
                    SELECT id FROM application_events
                    WHERE application_id = :application_id
                      AND event_type = 'STATUS_CHANGED'
                      AND reverted_at IS NULL
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """
                ),
                {"application_id": event["application_id"]},
            ).scalar_one_or_none()
            if latest != event_id:
                return False
            connection.execute(
                text(
                    "UPDATE application_events "
                    "SET reverted_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": event_id},
            )
        self.update_application_status(
            int(event["application_id"]),
            str(event["old_status"]),
            source="UNDO",
            details={"reverted_event_id": event_id},
        )
        return True

    def replace_profile_projects(
        self, profile_id: int, projects: list[ProfileProject], locale: str = "fr"
    ) -> None:
        """Synchronise les preuves d'une locale sans toucher l'autre version."""
        self._require_profile(profile_id)
        if locale not in {"fr", "en"}:
            raise ValueError("La langue des projets doit être fr ou en.")
        slugs = [project.slug for project in projects]
        with self.engine.begin() as connection:
            if slugs:
                placeholders = ", ".join(
                    f":slug_{index}" for index in range(len(slugs))
                )
                params = {"profile_id": profile_id, "locale": locale}
                params.update(
                    {f"slug_{index}": slug for index, slug in enumerate(slugs)}
                )
                connection.execute(
                    text(
                        "UPDATE profile_projects SET is_active = FALSE "
                        f"WHERE profile_id = :profile_id AND locale = :locale "
                        f"AND slug NOT IN ({placeholders})"
                    ),
                    params,
                )
            else:
                connection.execute(
                    text(
                        "UPDATE profile_projects SET is_active = FALSE "
                        "WHERE profile_id = :profile_id AND locale = :locale"
                    ),
                    {"profile_id": profile_id, "locale": locale},
                )
            for project in projects:
                connection.execute(
                    text(
                        """
                        INSERT INTO profile_projects (
                            profile_id, locale, slug, name, problem, stack,
                            deliverable, details, skills, results,
                            sort_order, is_active, synced_at
                        ) VALUES (
                            :profile_id, :locale, :slug, :name, :problem, :stack,
                            :deliverable, :details, :skills, :results,
                            :sort_order, :is_active, CURRENT_TIMESTAMP
                        )
                        ON CONFLICT (profile_id, locale, slug) DO UPDATE SET
                            name = EXCLUDED.name,
                            problem = EXCLUDED.problem,
                            stack = EXCLUDED.stack,
                            deliverable = EXCLUDED.deliverable,
                            details = EXCLUDED.details,
                            skills = EXCLUDED.skills,
                            results = EXCLUDED.results,
                            sort_order = EXCLUDED.sort_order,
                            is_active = EXCLUDED.is_active,
                            synced_at = CURRENT_TIMESTAMP
                        """
                    ),
                    {
                        "profile_id": profile_id,
                        "locale": locale,
                        "slug": project.slug,
                        "name": project.name,
                        "problem": project.problem,
                        "stack": self._list_value(list(project.stack)),
                        "deliverable": project.deliverable,
                        "details": project.details,
                        "skills": self._list_value(list(project.skills)),
                        "results": project.results,
                        "sort_order": project.sort_order,
                        "is_active": project.is_active,
                    },
                )

    def fetch_profile_projects(
        self, profile_id: int, active_only: bool = True, locale: str = "fr"
    ) -> list[ProfileProject]:
        """Relit les projets validés pour composer un CV ciblé fidèle au profil."""
        self._require_profile(profile_id)
        if locale not in {"fr", "en"}:
            raise ValueError("La langue des projets doit être fr ou en.")
        condition = "AND is_active = TRUE" if active_only else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT * FROM profile_projects
                    WHERE profile_id = :profile_id AND locale = :locale {condition}
                    ORDER BY sort_order, id
                    """
                ),
                {"profile_id": profile_id, "locale": locale},
            ).mappings()
            return [
                ProfileProject(
                    slug=str(row["slug"]),
                    name=str(row["name"]),
                    problem=str(row.get("problem") or ""),
                    stack=tuple(ensure_list(row.get("stack"))),
                    deliverable=str(row.get("deliverable") or ""),
                    details=str(row.get("details") or ""),
                    skills=tuple(ensure_list(row.get("skills"))),
                    results=str(row.get("results") or ""),
                    sort_order=int(row.get("sort_order") or 0),
                    is_active=bool(row.get("is_active")),
                )
                for row in rows
            ]

    def add_application_document(
        self,
        application_id: int,
        kind: str,
        path: str,
        sha256: str,
    ) -> int:
        """Versionne un PDF et rend les anciennes versions non courantes."""
        self._require_application(application_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE application_documents SET is_current = FALSE
                    WHERE application_id = :application_id AND kind = :kind
                    """
                ),
                {"application_id": application_id, "kind": kind},
            )
            document_id = connection.execute(
                text(
                    """
                    INSERT INTO application_documents (
                        application_id, kind, path, sha256
                    ) VALUES (:application_id, :kind, :path, :sha256)
                    RETURNING id
                    """
                ),
                {
                    "application_id": application_id,
                    "kind": kind,
                    "path": path,
                    "sha256": sha256,
                },
            ).scalar_one()
        return int(document_id)

    def fetch_application_documents(self, application_id: int) -> pd.DataFrame:
        """Liste les versions de documents d'un dossier pour son historique téléchargeable."""
        self._require_application(application_id)
        return pd.read_sql(
            text(
                """
                SELECT * FROM application_documents
                WHERE application_id = :application_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            self.engine,
            params={"application_id": application_id},
        )

    def email_message_exists(
        self, gmail_account: str, gmail_message_id: str
    ) -> bool:
        """Teste l'identifiant Gmail uniquement dans sa boîte d'origine."""
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT 1 FROM email_messages "
                    "WHERE gmail_account = :gmail_account "
                    "AND gmail_message_id = :message_id "
                    "AND (:user_id IS NULL OR user_id = :user_id)"
                ),
                {
                    "gmail_account": gmail_account,
                    "message_id": gmail_message_id,
                    "user_id": self.user_id,
                },
            ).first() is not None

    def save_email_message(self, values: dict[str, Any]) -> int | None:
        """Insère une seule fois un message Gmail, sans corps intégral."""
        values = dict(values)
        matched_application_id = values.get("matched_application_id")
        if matched_application_id is not None:
            self._require_application(int(matched_application_id))
        if self.user_id is None and self.email_message_exists(
            str(values.get("gmail_account") or ""),
            str(values.get("gmail_message_id") or ""),
        ):
            return None
        links = json.dumps(
            values.pop("extracted_links", []), ensure_ascii=False, default=str
        )
        links_parameter = (
            ":extracted_links"
            if self.is_sqlite
            else "CAST(:extracted_links AS JSONB)"
        )
        values["extracted_links"] = links
        values["user_id"] = self.user_id
        with self.engine.begin() as connection:
            message_id = connection.execute(
                text(
                    f"""
                    INSERT INTO email_messages (
                        user_id, gmail_account, gmail_message_id, gmail_thread_id,
                        sender, subject,
                        received_at, snippet, classification, confidence,
                        matched_application_id, processing_state, reason,
                        extracted_links
                    ) VALUES (
                        :user_id, :gmail_account, :gmail_message_id, :gmail_thread_id,
                        :sender, :subject,
                        :received_at, :snippet, :classification, :confidence,
                        :matched_application_id, :processing_state, :reason,
                        {links_parameter}
                    )
                    ON CONFLICT (user_id, gmail_account, gmail_message_id) DO NOTHING
                    RETURNING id
                    """
                ),
                values,
            ).scalar_one_or_none()
        return int(message_id) if message_id is not None else None

    def fetch_pending_email_messages(
        self, gmail_account: str | None = None
    ) -> pd.DataFrame:
        """Retourne uniquement les e-mails nécessitant une décision humaine.

        Les messages classés automatiquement comme bruit (`AUTO_IGNORED`) ou
        déjà traités ne doivent jamais réapparaître dans cette file.
        """
        account_clause = (
            "" if gmail_account is None else "AND e.gmail_account = :gmail_account"
        )
        return pd.read_sql(
            text(
                f"""
                SELECT e.*, a.status AS application_status,
                       j.company_name, j.job_title
                FROM email_messages e
                LEFT JOIN applications a ON a.id = e.matched_application_id
                LEFT JOIN job_offers j ON j.id = a.job_id
                WHERE e.processing_state IN ('PENDING', 'REVIEW')
                  AND (:user_id IS NULL OR e.user_id = :user_id)
                {account_clause}
                ORDER BY e.received_at DESC NULLS LAST, e.id DESC
                """
            ),
            self.engine,
            params={"gmail_account": gmail_account, "user_id": self.user_id},
        )

    def fetch_email_messages(
        self, processing_state: str | None = None, limit: int = 100
    ) -> pd.DataFrame:
        """Lit l'historique Gmail pour permettre audit et vérification UI."""
        state_clause = "" if processing_state is None else "AND e.processing_state = :state"
        return pd.read_sql(
            text(
                f"""
                SELECT e.*, a.status AS application_status,
                       j.company_name, j.job_title
                FROM email_messages e
                LEFT JOIN applications a ON a.id = e.matched_application_id
                LEFT JOIN job_offers j ON j.id = a.job_id
                WHERE (:user_id IS NULL OR e.user_id = :user_id) {state_clause}
                ORDER BY e.received_at DESC NULLS LAST, e.id DESC
                LIMIT :limit
                """
            ),
            self.engine,
            params={
                "state": processing_state,
                "user_id": self.user_id,
                "limit": max(1, min(int(limit), 1000)),
            },
        )

    def update_email_triage(
        self,
        email_id: int,
        *,
        classification: str,
        confidence: float,
        processing_state: str,
        reason: str,
        application_id: int | None = None,
    ) -> None:
        """Met à jour une décision automatique de triage locale.

        Cette méthode ne touche jamais Gmail et ne modifie pas l'historique de
        candidature : le changement de statut reste enregistré séparément par
        ``update_application_status``. Une correction humaine est protégée de
        ces recalculs automatiques afin de rester une vérité de travail stable.
        """
        self._require_email(email_id)
        if application_id is not None:
            self._require_application(application_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE email_messages
                    SET classification = :classification,
                        confidence = :confidence,
                        matched_application_id = COALESCE(
                            :application_id, matched_application_id
                        ),
                        processing_state = :processing_state,
                        reason = :reason
                    WHERE id = :id AND classification_manual = FALSE
                    """
                ),
                {
                    "id": email_id,
                    "classification": classification,
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "application_id": application_id,
                    "processing_state": processing_state,
                    "reason": reason,
                },
            )

    def resolve_email_message(
        self,
        email_id: int,
        processing_state: str,
        application_id: int | None = None,
    ) -> None:
        """Résout une proposition Gmail sans modifier le message distant."""
        allowed = {
            "APPROVED",
            "IGNORED",
            "AUTO_IGNORED",
            "REVIEW",
            "AUTO_APPLIED",
            "IMPORTED",
            "CLASSIFIED",
        }
        if processing_state not in allowed:
            raise ValueError("État de traitement Gmail non autorisé.")
        self._require_email(email_id)
        if application_id is not None:
            self._require_application(application_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE email_messages
                    SET processing_state = :state,
                        matched_application_id = COALESCE(
                            :application_id, matched_application_id
                        )
                    WHERE id = :id
                    """
                ),
                {
                    "id": email_id,
                    "state": processing_state,
                    "application_id": application_id,
                },
            )

    def reopen_auto_ignored_email(self, email_id: int, reason: str) -> None:
        """Remet en revue un e-mail écarté automatiquement, sans toucher Gmail."""
        self._require_email(email_id)
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE email_messages
                    SET classification_manual = TRUE,
                        processing_state = 'REVIEW',
                        reason = :reason
                    WHERE id = :id AND processing_state = 'AUTO_IGNORED'
                    """
                ),
                {
                    "id": email_id,
                    "reason": reason.strip() or "Réouverture manuelle",
                },
            )
        if result.rowcount != 1:
            raise ValueError(
                "Seul un e-mail écarté par Rocky peut être requalifié."
            )

    def reclassify_email_as_job_alert(self, email_id: int, reason: str) -> None:
        """Classe définitivement un message comme alerte emploi locale.

        Le rapprochement de candidature est retiré afin que cette décision ne
        modifie jamais un dossier. L'état ``CLASSIFIED`` sort aussitôt le mail
        de la file de revue tout en gardant son classement dans l'historique.
        """
        self._require_email(email_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE email_messages
                    SET classification = 'JOB_ALERT',
                        classification_manual = TRUE,
                        confidence = :confidence,
                        processing_state = 'CLASSIFIED',
                        reason = :reason,
                        matched_application_id = NULL
                    WHERE id = :id
                    """
                ),
                {
                    "id": email_id,
                    "confidence": 0.95,
                    "reason": reason,
                },
            )

    def manually_classify_email(
        self,
        email_id: int,
        *,
        classification: str,
        confidence: float,
        processing_state: str,
        reason: str,
        clear_application: bool,
    ) -> None:
        """Enregistre une correction humaine de classement sans toucher Gmail.

        Un message déclaré hors emploi perd son rattachement éventuel afin de
        ne plus polluer l'historique d'une candidature. Un retour de
        candidature peut au contraire conserver ce rapprochement et rester en
        revue jusqu'à la décision de statut explicite.
        """
        allowed_classifications = {"NOISE", "APPLICATION_UPDATE", "JOB_ALERT"}
        allowed_states = {"REVIEW", "IGNORED", "CLASSIFIED"}
        if classification not in allowed_classifications:
            raise ValueError("Classification Gmail non autorisée.")
        if processing_state not in allowed_states:
            raise ValueError("État de classement Gmail non autorisé.")
        self._require_email(email_id)
        application_assignment = (
            "NULL" if clear_application else "matched_application_id"
        )
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE email_messages
                    SET classification = :classification,
                        classification_manual = TRUE,
                        confidence = :confidence,
                        processing_state = :processing_state,
                        reason = :reason,
                        matched_application_id = {application_assignment}
                    WHERE id = :id
                    """
                ),
                {
                    "id": email_id,
                    "classification": classification,
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "processing_state": processing_state,
                    "reason": reason.strip() or "Classement manuel",
                },
            )

    def undo_job_alert_reclassification(
        self,
        email_id: int,
        application_id: int | None,
        reason: str,
    ) -> None:
        """Restaure une mise à jour de candidature après un reclassement manuel."""
        self._require_email(email_id)
        if application_id is not None:
            self._require_application(application_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE email_messages
                    SET classification = 'APPLICATION_UPDATE',
                        classification_manual = TRUE,
                        confidence = :confidence,
                        processing_state = 'REVIEW',
                        reason = :reason,
                        matched_application_id = :application_id
                    WHERE id = :id
                    """
                ),
                {
                    "id": email_id,
                    "confidence": 0.78,
                    "reason": reason,
                    "application_id": application_id,
                },
            )

    def add_application_note(self, application_id: int, note: str) -> None:
        """Ajoute une note sans écraser le texte déjà saisi."""
        self._require_application(application_id)
        cleaned = note.strip()
        if not cleaned:
            return
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE applications
                    SET notes = CASE
                        WHEN notes IS NULL OR TRIM(notes) = '' THEN :note
                        ELSE notes || :separator || :note
                    END,
                    updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": application_id, "note": cleaned, "separator": "\n\n"},
            )

    def create_browser_session(self, application_id: int, target_url: str) -> int:
        """Crée la trace avant d'ouvrir le navigateur externe."""
        if self.fetch_application(application_id) is None:
            raise PermissionError("Cette candidature n'appartient pas au compte connecté.")
        with self.engine.begin() as connection:
            session_id = connection.execute(
                text(
                    """
                    INSERT INTO application_browser_sessions (
                        application_id, target_url
                    ) VALUES (:application_id, :target_url)
                    RETURNING id
                    """
                ),
                {"application_id": application_id, "target_url": target_url},
            ).scalar_one()
        return int(session_id)

    def update_browser_session(
        self,
        session_id: int,
        status: str,
        filled_fields: list[str] | None = None,
        missing_fields: list[str] | None = None,
        error_message: str | None = None,
    ) -> None:
        """Met à jour le bilan sans journaliser la valeur des champs sensibles."""
        filled = json.dumps(filled_fields or [], ensure_ascii=False)
        missing = json.dumps(missing_fields or [], ensure_ascii=False)
        filled_parameter = ":filled" if self.is_sqlite else "CAST(:filled AS JSONB)"
        missing_parameter = ":missing" if self.is_sqlite else "CAST(:missing AS JSONB)"
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE application_browser_sessions
                    SET status = :status,
                        filled_fields = {filled_parameter},
                        missing_fields = {missing_parameter},
                        error_message = :error_message,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND EXISTS (
                        SELECT 1 FROM applications a
                        JOIN candidate_profiles p ON p.id = a.profile_id
                        WHERE a.id = application_browser_sessions.application_id
                          AND (:user_id IS NULL OR p.user_id = :user_id)
                    )
                    """
                ),
                {
                    "id": session_id,
                    "status": status,
                    "filled": filled,
                    "missing": missing,
                    "error_message": error_message,
                    "user_id": self.user_id,
                },
            )

    def fetch_browser_session(self, session_id: int) -> dict[str, Any] | None:
        """Retourne une session de navigateur appartenant au compte connecté."""
        if self.user_id is None:
            raise PermissionError(
                "Un compte authentifié est requis pour lire une session navigateur."
            )
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT s.*
                    FROM application_browser_sessions s
                    JOIN applications a ON a.id = s.application_id
                    JOIN candidate_profiles p ON p.id = a.profile_id
                    WHERE s.id = :id AND p.user_id = :user_id
                    """
                ),
                {"id": session_id, "user_id": self.user_id},
            ).mappings().first()
        return dict(row) if row else None

    def fetch_browser_sessions(self, application_id: int) -> pd.DataFrame:
        """Restitue les ouvertures ou préremplissages tracés, sans prétendre à un envoi."""
        return pd.read_sql(
            text(
                """
                SELECT * FROM application_browser_sessions
                WHERE application_id = :application_id
                  AND EXISTS (
                    SELECT 1 FROM applications a
                    JOIN candidate_profiles p ON p.id = a.profile_id
                    WHERE a.id = application_browser_sessions.application_id
                      AND (:user_id IS NULL OR p.user_id = :user_id)
                  )
                ORDER BY started_at DESC, id DESC
                """
            ),
            self.engine,
            params={"application_id": application_id, "user_id": self.user_id},
        )

    def start_watch_run(
        self, profile_id: int, searched_job_titles: tuple[str, ...] | list[str] = ()
    ) -> int:
        """Crée une veille avec l'instantané des intitulés réellement cherchés."""
        self._require_profile(profile_id)
        titles = [
            str(title).strip() for title in searched_job_titles if str(title).strip()
        ]
        titles_parameter = ":searched_job_titles"
        if not self.is_sqlite:
            titles_parameter = "CAST(:searched_job_titles AS JSONB)"
        with self.engine.begin() as connection:
            run_id = connection.execute(
                text(
                    """
                    INSERT INTO watch_runs (user_id, profile_id, searched_job_titles)
                    VALUES (:user_id, :profile_id, """
                    + titles_parameter
                    + ") RETURNING id"
                ),
                {
                    "user_id": self.user_id,
                    "profile_id": profile_id,
                    "searched_job_titles": json.dumps(titles, ensure_ascii=False),
                },
            ).scalar_one()
        return int(run_id)

    def create_monitoring_note(self, profile_id: int | None, content: str) -> int | None:
        """Enregistre une note courte liée au projet/profil courant."""
        if profile_id is not None:
            self._require_profile(profile_id)
        cleaned = content.strip()
        if not cleaned:
            return None
        with self.engine.begin() as connection:
            note_id = connection.execute(
                text(
                    """
                    INSERT INTO monitoring_notes (user_id, profile_id, content)
                    VALUES (:user_id, :profile_id, :content) RETURNING id
                    """
                ),
                {"user_id": self.user_id, "profile_id": profile_id, "content": cleaned},
            ).scalar_one()
        return int(note_id)

    def fetch_monitoring_notes(
        self, profile_id: int | None = None, limit: int = 40
    ) -> pd.DataFrame:
        """Retourne les pense-bêtes récents pour le carrousel Monitoring."""
        return pd.read_sql(
            text(
                """
                SELECT id, profile_id, content, created_at, updated_at
                FROM monitoring_notes
                WHERE (:user_id IS NULL OR user_id = :user_id)
                  AND (:profile_id IS NULL OR profile_id = :profile_id)
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
                """
            ),
            self.engine,
            params={
                "profile_id": profile_id,
                "user_id": self.user_id,
                "limit": max(1, min(int(limit), 200)),
            },
        )

    def delete_monitoring_note(self, note_id: int) -> None:
        """Supprime un seul pense-bête identifié par son ID local."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM monitoring_notes WHERE id = :id "
                    "AND (:user_id IS NULL OR user_id = :user_id)"
                ),
                {"id": note_id, "user_id": self.user_id},
            )

    def finish_watch_run(self, run_id: int, summary: dict[str, Any]) -> None:
        """Clôture une veille avec ses volumes, erreurs et résultats détaillés par source."""
        errors_parameter = ":errors"
        sources_parameter = ":source_results"
        if not self.is_sqlite:
            errors_parameter = "CAST(:errors AS JSONB)"
            sources_parameter = "CAST(:source_results AS JSONB)"
        query = f"""
            UPDATE watch_runs
            SET finished_at = CURRENT_TIMESTAMP, status = :status,
                fetched_count = :fetched_count,
                inserted_count = :inserted_count,
                duplicate_count = :duplicate_count,
                rejected_count = :rejected_count,
                errors = {errors_parameter},
                source_results = {sources_parameter}
            WHERE id = :id AND (:user_id IS NULL OR user_id = :user_id)
        """
        with self.engine.begin() as connection:
            connection.execute(
                text(query),
                {
                    "id": run_id,
                    "status": summary["status"],
                    "fetched_count": summary["fetched_count"],
                    "inserted_count": summary["inserted_count"],
                    "duplicate_count": summary["duplicate_count"],
                    "rejected_count": summary["rejected_count"],
                    "errors": json.dumps(
                        summary.get("errors", []), ensure_ascii=False
                    ),
                    "source_results": json.dumps(
                        summary.get("sources", []), ensure_ascii=False
                    ),
                    "user_id": self.user_id,
                },
            )

    def has_watch_run_on(self, day: date) -> bool:
        """Indique si une veille a démarré pendant la journée Europe/Paris.

        Les colonnes historiques sont parfois stockées en UTC naïf (SQLite)
        et parfois avec le fuseau du serveur (PostgreSQL). La conversion côté
        Python évite le décalage d'un jour observé autour de minuit et garde la
        même règle métier pour les deux moteurs.
        """
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT started_at FROM watch_runs
                    WHERE started_at IS NOT NULL
                      AND (:user_id IS NULL OR user_id = :user_id)
                    """
                ),
                {"user_id": self.user_id},
            ).fetchall()
        paris = ZoneInfo("Europe/Paris")
        for (started_at,) in row:
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if not isinstance(started_at, datetime):
                continue
            if started_at.tzinfo is None:
                # CURRENT_TIMESTAMP SQLite et les timestamps PostgreSQL
                # historiques sont UTC lorsqu'ils ne portent pas de fuseau.
                started_at = started_at.replace(tzinfo=timezone.utc)
            if started_at.astimezone(paris).date() == day:
                return True
        return False

    def fetch_watch_runs(self, limit: int = 20) -> pd.DataFrame:
        """Retourne l'historique récent utilisé par le monitoring V2."""
        return pd.read_sql(
            text(
                """
                SELECT wr.*, cp.profile_name
                FROM watch_runs wr
                LEFT JOIN candidate_profiles cp ON cp.id = wr.profile_id
                WHERE :user_id IS NULL OR wr.user_id = :user_id
                ORDER BY wr.started_at DESC
                LIMIT :limit
                """
            ),
            self.engine,
            params={"limit": max(1, int(limit)), "user_id": self.user_id},
        )

    def fetch_latest_completed_watch_run(
        self, profile_id: int
    ) -> dict[str, Any] | None:
        """Retourne la dernière veille terminée pour le profil demandé."""
        self._require_profile(profile_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM watch_runs
                    WHERE profile_id = :profile_id
                      AND finished_at IS NOT NULL
                    ORDER BY finished_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"profile_id": profile_id},
            ).mappings().first()
        return dict(row) if row else None
