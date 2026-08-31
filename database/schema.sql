-- Schéma courant de Rocky pour une base vide.

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    email_verified_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'PENDING',
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_normalized
    ON users (LOWER(email));

CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user
    ON user_sessions (user_id, expires_at);

CREATE TABLE IF NOT EXISTS account_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_tokens_user
    ON account_tokens (user_id, purpose, expires_at);

CREATE TABLE IF NOT EXISTS job_offers (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
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
    detected_language TEXT NOT NULL DEFAULT 'fr',
    language_confidence NUMERIC,
    language_override TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_offers_publication
    ON job_offers (publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_job_offers_source_external
    ON job_offers (source_name, external_id);
CREATE INDEX IF NOT EXISTS idx_job_offers_source_url
    ON job_offers (source_url);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    profile_name TEXT NOT NULL,
    summary TEXT,
    target_job_titles TEXT[] DEFAULT '{}',
    preferred_contracts TEXT[] DEFAULT '{}',
    preferred_locations TEXT[] DEFAULT '{}',
    remote_preferences TEXT[] DEFAULT '{}',
    minimum_salary NUMERIC,
    cv_path TEXT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    postal_code TEXT,
    home_city TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    portfolio_url TEXT,
    onboarding_status TEXT NOT NULL DEFAULT 'COMPLETE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_candidate_profile_per_user
    ON candidate_profiles (user_id)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_candidate_profiles_user
    ON candidate_profiles (user_id, onboarding_status, is_active);

CREATE TABLE IF NOT EXISTS profile_localizations (
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    locale TEXT NOT NULL CHECK (locale IN ('fr', 'en')),
    summary TEXT,
    target_job_titles TEXT[] DEFAULT '{}',
    target_domains TEXT[] DEFAULT '{}',
    translation_status TEXT NOT NULL DEFAULT 'ready',
    source_hash TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (profile_id, locale)
);

CREATE TABLE IF NOT EXISTS profile_documents (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    locale TEXT NOT NULL CHECK (locale IN ('fr', 'en')),
    kind TEXT NOT NULL,
    source_path TEXT NOT NULL,
    preview_pdf_path TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('uploaded', 'generated')),
    status TEXT NOT NULL DEFAULT 'ready',
    sha256 TEXT NOT NULL,
    source_hash TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (profile_id, locale, kind, version)
);

CREATE INDEX IF NOT EXISTS idx_profile_documents_profile
    ON profile_documents (profile_id, locale, kind);

CREATE TABLE IF NOT EXISTS profile_analyses (
    profile_id BIGINT PRIMARY KEY REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    analysis_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ready',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS candidate_skills (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    skill_name_en TEXT,
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
    profile_locale TEXT NOT NULL DEFAULT 'fr',
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, profile_id)
);

-- ``job_matches`` fournit la valeur courante ; chaque recalcul est conservé
-- ici pour pouvoir analyser l'évolution des résultats et du moteur employé.
CREATE TABLE IF NOT EXISTS job_match_history (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    score NUMERIC(5,2) NOT NULL,
    breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    strengths TEXT[] NOT NULL DEFAULT '{}',
    gaps TEXT[] NOT NULL DEFAULT '{}',
    profile_locale TEXT NOT NULL DEFAULT 'fr',
    scoring_version TEXT NOT NULL DEFAULT 'matching-v1',
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_match_history_pair
    ON job_match_history (job_id, profile_id, analyzed_at DESC);

CREATE TABLE IF NOT EXISTS applications (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'DOSSIER PRÉPARÉ',
    cv_path TEXT NOT NULL,
    letter_docx_path TEXT,
    letter_pdf_path TEXT NOT NULL,
    notes TEXT,
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status_source TEXT NOT NULL DEFAULT 'USER',
    last_email_at TIMESTAMPTZ,
    profile_locale TEXT NOT NULL DEFAULT 'fr'
);

CREATE TABLE IF NOT EXISTS profile_projects (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    locale TEXT NOT NULL DEFAULT 'fr' CHECK (locale IN ('fr', 'en')),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    problem TEXT NOT NULL DEFAULT '',
    stack TEXT[] NOT NULL DEFAULT '{}',
    deliverable TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    skills TEXT[] NOT NULL DEFAULT '{}',
    results TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (profile_id, locale, slug)
);

CREATE TABLE IF NOT EXISTS application_documents (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_application_documents_application
    ON application_documents (application_id, created_at DESC);

CREATE TABLE IF NOT EXISTS application_events (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    source TEXT NOT NULL DEFAULT 'USER',
    confidence NUMERIC(4,3),
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reverted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_application_events_application
    ON application_events (application_id, created_at DESC);

CREATE TABLE IF NOT EXISTS email_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    gmail_account TEXT NOT NULL,
    gmail_message_id TEXT NOT NULL,
    gmail_thread_id TEXT,
    sender TEXT,
    subject TEXT,
    received_at TIMESTAMPTZ,
    snippet TEXT,
    classification TEXT NOT NULL DEFAULT 'UNKNOWN',
    classification_manual BOOLEAN NOT NULL DEFAULT FALSE,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
    matched_application_id BIGINT REFERENCES applications(id) ON DELETE SET NULL,
    processing_state TEXT NOT NULL DEFAULT 'PENDING',
    reason TEXT,
    extracted_links JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, gmail_account, gmail_message_id)
);

CREATE INDEX IF NOT EXISTS idx_email_messages_state
    ON email_messages (processing_state, received_at DESC);

CREATE TABLE IF NOT EXISTS application_browser_sessions (
    id BIGSERIAL PRIMARY KEY,
    application_id BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    target_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'STARTING',
    filled_fields JSONB NOT NULL DEFAULT '[]',
    missing_fields JSONB NOT NULL DEFAULT '[]',
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watch_runs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    profile_id BIGINT REFERENCES candidate_profiles(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    searched_job_titles JSONB NOT NULL DEFAULT '[]',
    errors JSONB NOT NULL DEFAULT '[]',
    source_results JSONB NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS monitoring_notes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    profile_id BIGINT REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monitoring_notes_profile
    ON monitoring_notes (profile_id, updated_at DESC);
