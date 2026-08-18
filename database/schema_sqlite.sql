-- Schéma SQLite utilisé par le Space Hugging Face.
-- Les listes et objets JSON sont stockés sous forme de texte JSON.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 30000;

CREATE TABLE IF NOT EXISTS job_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    description_is_full BOOLEAN NOT NULL DEFAULT 0,
    description_enrichment_source TEXT,
    description_enrichment_external_id TEXT,
    responsibilities TEXT NOT NULL,
    required_skills TEXT NOT NULL DEFAULT '[]',
    preferred_skills TEXT NOT NULL DEFAULT '[]',
    required_education TEXT,
    minimum_experience_years NUMERIC,
    main_domain TEXT,
    programming_languages TEXT NOT NULL DEFAULT '[]',
    technical_tools TEXT NOT NULL DEFAULT '[]',
    soft_skills TEXT NOT NULL DEFAULT '[]',
    languages_required TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    publication_date DATE,
    application_deadline DATE,
    status TEXT NOT NULL DEFAULT 'NOUVELLE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_offers_publication
    ON job_offers (publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_job_offers_source_external
    ON job_offers (source_name, external_id);
CREATE INDEX IF NOT EXISTS idx_job_offers_source_url
    ON job_offers (source_url);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_name TEXT NOT NULL,
    summary TEXT,
    target_job_titles TEXT NOT NULL DEFAULT '[]',
    preferred_contracts TEXT NOT NULL DEFAULT '[]',
    preferred_locations TEXT NOT NULL DEFAULT '[]',
    remote_preferences TEXT NOT NULL DEFAULT '[]',
    minimum_salary NUMERIC,
    cv_path TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_candidate_profile
    ON candidate_profiles (is_active) WHERE is_active = 1;

CREATE TABLE IF NOT EXISTS candidate_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    skill_category TEXT NOT NULL,
    skill_level TEXT,
    years_experience NUMERIC,
    is_core_skill BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidate_skills_profile
    ON candidate_skills (profile_id);

-- Relation légère entre un profil de recherche et une annonce centrale.
CREATE TABLE IF NOT EXISTS profile_jobs (
    profile_id INTEGER NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    linked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_profile_jobs_job
    ON profile_jobs (job_id);

CREATE TABLE IF NOT EXISTS job_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    score NUMERIC NOT NULL,
    breakdown TEXT NOT NULL DEFAULT '{}',
    strengths TEXT NOT NULL DEFAULT '[]',
    gaps TEXT NOT NULL DEFAULT '[]',
    analyzed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, profile_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'DOSSIER PRÉPARÉ',
    cv_path TEXT NOT NULL,
    letter_docx_path TEXT NOT NULL,
    letter_pdf_path TEXT NOT NULL,
    notes TEXT,
    prepared_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES candidate_profiles(id) ON DELETE SET NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    errors TEXT NOT NULL DEFAULT '[]',
    source_results TEXT NOT NULL DEFAULT '[]'
);

INSERT OR IGNORE INTO profile_jobs (profile_id, job_id)
SELECT DISTINCT profile_id, job_id FROM job_matches;

INSERT OR IGNORE INTO profile_jobs (profile_id, job_id)
SELECT DISTINCT profile_id, job_id FROM applications;

INSERT OR IGNORE INTO profile_jobs (profile_id, job_id)
SELECT DISTINCT runs.profile_id, jobs.id
FROM watch_runs AS runs
JOIN job_offers AS jobs
  ON jobs.created_at >= runs.started_at
 AND jobs.created_at <= runs.finished_at
WHERE runs.profile_id IS NOT NULL
  AND runs.finished_at IS NOT NULL;

INSERT OR IGNORE INTO profile_jobs (profile_id, job_id)
SELECT (
        SELECT id FROM candidate_profiles ORDER BY created_at, id LIMIT 1
    ), jobs.id
FROM job_offers AS jobs
WHERE EXISTS (SELECT 1 FROM candidate_profiles)
  AND NOT EXISTS (
      SELECT 1 FROM profile_jobs AS links WHERE links.job_id = jobs.id
  );
