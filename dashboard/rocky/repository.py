"""Accès PostgreSQL de Rocky.

Toutes les requêtes SQL sont regroupées ici. Les modules métier peuvent ainsi
être testés sans connaître la structure exacte de la base.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

from .models import CandidateProfile, JobOffer, MatchResult
from .text_utils import canonical_url, ensure_list


STATUS_TO_JOB_STATUS = {
    "DOSSIER PRÉPARÉ": "RETENUE",
    "CANDIDATURE ENVOYÉE": "CANDIDATURE ENVOYÉE",
    "ENTRETIEN": "ENTRETIEN",
    "REFUS": "REFUS",
}


def _clean(value: Any) -> Any:
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

    def __init__(self, engine: Engine):
        self.engine = engine

    @property
    def is_sqlite(self) -> bool:
        return self.engine.dialect.name == "sqlite"

    def _list_value(self, value: list[Any]) -> list[Any] | str:
        """Adapte les listes aux tableaux PostgreSQL ou au JSON SQLite."""
        if self.is_sqlite:
            return json.dumps(value, ensure_ascii=False)
        return value

    def fetch_jobs(self, profile_id: int | None = None) -> pd.DataFrame:
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
            WHERE :profile_id IS NULL OR EXISTS (
                SELECT 1
                FROM profile_jobs pj
                WHERE pj.job_id = j.id
                  AND pj.profile_id = :profile_id
            )
            ORDER BY j.publication_date DESC NULLS LAST, j.created_at DESC
        """
        return pd.read_sql(
            text(query), self.engine, params={"profile_id": profile_id}
        )

    def get_jobs_for_profile(self, profile_id: int) -> pd.DataFrame:
        """Retourne uniquement les annonces rattachées au profil demandé."""
        return self.fetch_jobs(profile_id)

    def link_job_to_profile(self, job_id: int, profile_id: int) -> bool:
        """Crée la relation profil-annonce sans dupliquer l'annonce centrale."""
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
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM job_offers WHERE id = :id"),
                {"id": job_id},
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
        )

    def fetch_profiles(self) -> pd.DataFrame:
        return pd.read_sql(
            text(
                """
                SELECT * FROM candidate_profiles
                ORDER BY is_active DESC, id
                """
            ),
            self.engine,
        )

    def fetch_profile(self, profile_id: int) -> CandidateProfile | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM candidate_profiles WHERE id = :id"),
                {"id": profile_id},
            ).mappings().first()
        if not row:
            return None
        return CandidateProfile(
            id=int(row["id"]),
            profile_name=row["profile_name"],
            summary=row.get("summary") or "",
            target_job_titles=ensure_list(row.get("target_job_titles")),
            preferred_contracts=ensure_list(row.get("preferred_contracts")),
            preferred_locations=ensure_list(row.get("preferred_locations")),
            remote_preferences=ensure_list(row.get("remote_preferences")),
            minimum_salary=_clean(row.get("minimum_salary")),
            cv_path=row.get("cv_path") or "",
            is_active=bool(row.get("is_active")),
        )

    def fetch_active_profile(self) -> CandidateProfile | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id FROM candidate_profiles
                    WHERE is_active = TRUE
                    ORDER BY id LIMIT 1
                    """
                )
            ).first()
        return self.fetch_profile(int(row[0])) if row else None

    def fetch_skills(self, profile_id: int) -> list[dict[str, Any]]:
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

    def create_profile(self, name: str, summary: str = "") -> int:
        with self.engine.begin() as connection:
            profile_id = connection.execute(
                text(
                    """
                    INSERT INTO candidate_profiles (profile_name, summary)
                    VALUES (:name, :summary)
                    RETURNING id
                    """
                ),
                {"name": name.strip(), "summary": summary.strip() or None},
            ).scalar_one()
        return int(profile_id)

    def update_profile(self, profile: CandidateProfile) -> None:
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
                        summary = :summary,
                        target_job_titles = :target_job_titles,
                        preferred_contracts = :preferred_contracts,
                        preferred_locations = :preferred_locations,
                        remote_preferences = :remote_preferences,
                        minimum_salary = :minimum_salary,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                values,
            )

    def set_active_profile(self, profile_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE candidate_profiles SET is_active = FALSE")
            )
            connection.execute(
                text(
                    """
                    UPDATE candidate_profiles
                    SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": profile_id},
            )

    def save_cv_path(self, profile_id: int, relative_path: str) -> None:
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

    def add_skill(
        self,
        profile_id: int,
        name: str,
        category: str,
        level: str = "",
        years: float | None = None,
        is_core: bool = False,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO candidate_skills (
                        profile_id, skill_name, skill_category,
                        skill_level, years_experience, is_core_skill
                    ) VALUES (
                        :profile_id, :name, :category, :level, :years, :is_core
                    )
                    """
                ),
                {
                    "profile_id": profile_id,
                    "name": name.strip(),
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
    ) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE candidate_skills
                    SET skill_name = :name,
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
                    "category": category,
                    "level": level or None,
                    "years": years,
                    "is_core": is_core,
                },
            )
        return bool(result.rowcount)

    def delete_skill(self, skill_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM candidate_skills WHERE id = :id"),
                {"id": skill_id},
            )

    def find_duplicate(self, offer: JobOffer) -> int | None:
        conditions = []
        params: dict[str, Any] = {}
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
                    + " OR ".join(conditions)
                    + " ORDER BY id LIMIT 1"
                ),
                params,
            ).first()
        return int(row[0]) if row else None

    def insert_job(
        self, offer: JobOffer, profile_id: int | None = None
    ) -> tuple[int, bool]:
        duplicate_id = self.find_duplicate(offer)
        if duplicate_id is not None:
            if profile_id is not None:
                self.link_job_to_profile(duplicate_id, profile_id)
            return duplicate_id, False

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
                        external_id, source_name, collector_name,
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
                        application_deadline, status
                    ) VALUES (
                        :external_id, :source_name, :collector_name,
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
                        :application_deadline, :status
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
        self.link_job_to_profile(job_id, profile_id)
        breakdown_parameter = ":breakdown"
        if not self.is_sqlite:
            breakdown_parameter = "CAST(:breakdown AS JSONB)"
        query = f"""
            INSERT INTO job_matches (
                job_id, profile_id, score, breakdown, strengths, gaps
            ) VALUES (
                :job_id, :profile_id, :score,
                {breakdown_parameter}, :strengths, :gaps
            )
            ON CONFLICT (job_id, profile_id) DO UPDATE SET
                score = EXCLUDED.score,
                breakdown = EXCLUDED.breakdown,
                strengths = EXCLUDED.strengths,
                gaps = EXCLUDED.gaps,
                analyzed_at = CURRENT_TIMESTAMP
        """
        with self.engine.begin() as connection:
            connection.execute(
                text(query),
                {
                    "job_id": job_id,
                    "profile_id": profile_id,
                    "score": result.score,
                    "breakdown": json.dumps(
                        result.breakdown, ensure_ascii=False
                    ),
                    "strengths": self._list_value(result.strengths),
                    "gaps": self._list_value(result.gaps),
                },
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

    def update_job_status(self, job_id: int, status: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE job_offers
                    SET status = :status, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "status": status},
            )

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
                    WHERE id = :id
                    """
                ),
                [{"id": job_id, "status": status} for job_id in unique_ids],
            )
        return max(0, int(result.rowcount or 0))

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
                        publication_date = :publication_date,
                        application_deadline = :application_deadline,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                values,
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
        docx_path: str,
        pdf_path: str,
    ) -> int:
        self.link_job_to_profile(job_id, profile_id)
        with self.engine.begin() as connection:
            application_id = connection.execute(
                text(
                    """
                    INSERT INTO applications (
                        job_id, profile_id, cv_path,
                        letter_docx_path, letter_pdf_path
                    ) VALUES (
                        :job_id, :profile_id, :cv_path, :docx_path, :pdf_path
                    ) RETURNING id
                    """
                ),
                {
                    "job_id": job_id,
                    "profile_id": profile_id,
                    "cv_path": cv_path,
                    "docx_path": docx_path,
                    "pdf_path": pdf_path,
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
        return int(application_id)

    def fetch_applications(self) -> pd.DataFrame:
        return pd.read_sql(
            text(
                """
                SELECT a.*, j.job_title, j.company_name, j.application_url
                FROM applications a
                JOIN job_offers j ON j.id = a.job_id
                ORDER BY a.prepared_at DESC
                """
            ),
            self.engine,
        )

    def update_application_status(
        self, application_id: int, status: str
    ) -> None:
        """Met à jour le dossier et synchronise le statut de l'annonce."""
        with self.engine.begin() as connection:
            job_id = connection.execute(
                text(
                    """
                    UPDATE applications
                    SET status = :status,
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
                    "mark_sent": status == "CANDIDATURE ENVOYÉE",
                },
            ).scalar_one()
            if status in STATUS_TO_JOB_STATUS:
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
                        "status": STATUS_TO_JOB_STATUS[status],
                    },
                )

    def start_watch_run(self, profile_id: int) -> int:
        with self.engine.begin() as connection:
            run_id = connection.execute(
                text(
                    """
                    INSERT INTO watch_runs (profile_id)
                    VALUES (:profile_id) RETURNING id
                    """
                ),
                {"profile_id": profile_id},
            ).scalar_one()
        return int(run_id)

    def finish_watch_run(self, run_id: int, summary: dict[str, Any]) -> None:
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
            WHERE id = :id
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
                },
            )

    def has_watch_run_on(self, day: date) -> bool:
        """Indique si une veille a déjà démarré pendant la journée locale."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT 1 FROM watch_runs
                    WHERE DATE(started_at) = :day
                    LIMIT 1
                    """
                ),
                {"day": day.isoformat()},
            ).first()
        return row is not None

    def fetch_watch_runs(self, limit: int = 20) -> pd.DataFrame:
        """Retourne l'historique récent utilisé par le monitoring V2."""
        return pd.read_sql(
            text(
                """
                SELECT wr.*, cp.profile_name
                FROM watch_runs wr
                LEFT JOIN candidate_profiles cp ON cp.id = wr.profile_id
                ORDER BY wr.started_at DESC
                LIMIT :limit
                """
            ),
            self.engine,
            params={"limit": max(1, int(limit))},
        )

    def fetch_latest_completed_watch_run(
        self, profile_id: int
    ) -> dict[str, Any] | None:
        """Retourne la dernière veille terminée pour le profil demandé."""
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
