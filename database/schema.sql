-- Schéma idempotent de Rocky.
-- Il peut être rejoué après chaque évolution sans effacer les données.

CREATE TABLE IF NOT EXISTS job_offers (
    id BIGSERIAL PRIMARY KEY,
    external_id TEXT,
    source_name TEXT,
    collector_name TEXT,
    source_url TEXT,
    application_url TEXT,
    job_title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    city TEXT,
    country TEXT,
    remote_policy TEXT,
    contract_type TEXT,
    work_schedule TEXT,
    experience_level TEXT,
    salary_min NUMERIC,
    salary_max NUMERIC,
    salary_currency TEXT,
    short_description TEXT,
    description_is_full BOOLEAN NOT NULL DEFAULT FALSE,
    description_enrichment_source TEXT,
    description_enrichment_external_id TEXT,
    responsibilities TEXT NOT NULL,
    required_skills TEXT[] DEFAULT '{}',
    preferred_skills TEXT[] DEFAULT '{}',
    required_education TEXT,
    minimum_experience_years NUMERIC,
    main_domain TEXT,
    programming_languages TEXT[] DEFAULT '{}',
    technical_tools TEXT[] DEFAULT '{}',
    soft_skills TEXT[] DEFAULT '{}',
    languages_required TEXT[] DEFAULT '{}',
    keywords TEXT[] DEFAULT '{}',
    publication_date DATE,
    application_deadline DATE,
    status TEXT NOT NULL DEFAULT 'NOUVELLE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS application_url TEXT;
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS collector_name TEXT;
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS work_schedule TEXT;
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS description_is_full BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS description_enrichment_source TEXT;
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS description_enrichment_external_id TEXT;
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE job_offers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_job_offers_publication
    ON job_offers (publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_job_offers_source_external
    ON job_offers (source_name, external_id);
CREATE INDEX IF NOT EXISTS idx_job_offers_source_url
    ON job_offers (source_url);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id BIGSERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL,
    summary TEXT,
    target_job_titles TEXT[] DEFAULT '{}',
    preferred_contracts TEXT[] DEFAULT '{}',
    preferred_locations TEXT[] DEFAULT '{}',
    remote_preferences TEXT[] DEFAULT '{}',
    minimum_salary NUMERIC,
    cv_path TEXT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS cv_path TEXT;
ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_candidate_profile
    ON candidate_profiles (is_active)
    WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS candidate_skills (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    skill_category TEXT NOT NULL,
    skill_level TEXT,
    years_experience NUMERIC,
    is_core_skill BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candidate_skills_profile
    ON candidate_skills (profile_id);

-- Relation légère entre un profil de recherche et une annonce centrale.
-- Le matching reste séparé car une annonce incomplète peut être liée sans score.
CREATE TABLE IF NOT EXISTS profile_jobs (
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    job_id BIGINT NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (profile_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_profile_jobs_job
    ON profile_jobs (job_id);

CREATE TABLE IF NOT EXISTS job_matches (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    score NUMERIC(5,2) NOT NULL,
    breakdown JSONB NOT NULL DEFAULT '{}',
    strengths TEXT[] DEFAULT '{}',
    gaps TEXT[] DEFAULT '{}',
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, profile_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'DOSSIER PRÉPARÉ',
    cv_path TEXT NOT NULL,
    letter_docx_path TEXT NOT NULL,
    letter_pdf_path TEXT NOT NULL,
    notes TEXT,
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS watch_runs (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT REFERENCES candidate_profiles(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]',
    source_results JSONB NOT NULL DEFAULT '[]'
);

ALTER TABLE watch_runs
    ADD COLUMN IF NOT EXISTS source_results JSONB NOT NULL DEFAULT '[]';

-- Migration historique idempotente : les relations explicites sont prioritaires.
INSERT INTO profile_jobs (profile_id, job_id)
SELECT DISTINCT profile_id, job_id FROM job_matches
ON CONFLICT (profile_id, job_id) DO NOTHING;

INSERT INTO profile_jobs (profile_id, job_id)
SELECT DISTINCT profile_id, job_id FROM applications
ON CONFLICT (profile_id, job_id) DO NOTHING;

-- Les annonces créées pendant une veille appartiennent au profil de cette veille,
-- y compris lorsqu'elles étaient incomplètes et n'avaient donc aucun matching.
INSERT INTO profile_jobs (profile_id, job_id)
SELECT DISTINCT runs.profile_id, jobs.id
FROM watch_runs AS runs
JOIN job_offers AS jobs
  ON jobs.created_at >= runs.started_at
 AND jobs.created_at <= runs.finished_at
WHERE runs.profile_id IS NOT NULL
  AND runs.finished_at IS NOT NULL
ON CONFLICT (profile_id, job_id) DO NOTHING;

-- Dernier filet de rétrocompatibilité pour d'anciennes annonces sans trace :
-- Rocky étant historiquement mono-profil, elles restent visibles sur le profil
-- le plus ancien au lieu d'être perdues du cockpit après la migration.
INSERT INTO profile_jobs (profile_id, job_id)
SELECT oldest.id, jobs.id
FROM job_offers AS jobs
CROSS JOIN LATERAL (
    SELECT id FROM candidate_profiles ORDER BY created_at, id LIMIT 1
) AS oldest
WHERE NOT EXISTS (
    SELECT 1 FROM profile_jobs AS links WHERE links.job_id = jobs.id
)
ON CONFLICT (profile_id, job_id) DO NOTHING;
