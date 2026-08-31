---
paths:
  - "dashboard/rocky/repository.py"
  - "dashboard/rocky/database.py"
  - "dashboard/rocky/models.py"
  - "database/**"
  - "scripts/init_db.py"
---

# Data layer

- `repository.py` holds ALL SQL; business modules never write queries.
- `models.py` holds plain dataclasses (`JobOffer`, `CandidateProfile`, `MatchResult`); no ORM models.
- Two schemas must stay in sync: `database/schema.sql` (PostgreSQL, local) and `database/schema_sqlite.sql` (HF Space). Both are idempotent; rerun `python scripts/init_db.py` after a schema change without wiping data.
- Multi-profile model (see `docs/multi_profile_jobs.md`): `profile_jobs` means "this offer belongs to this profile's feed" (no score); `job_matches(job_id, profile_id)` holds the score and its detail. Offers are never duplicated across profiles.
- `description_enrichment_source` is reserved for voluntary re-enrichment of an already known offer; it never describes collection.
