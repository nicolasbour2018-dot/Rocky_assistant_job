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
- `database/schema.sql` and `database/schema_sqlite.sql` describe the complete current schema for a new empty database and must stay in sync. Rocky validates an existing database and fails clearly when it is incompatible; schema migrations and compatibility paths are intentionally out of scope.
- Multi-profile model (see `docs/multi_profile_jobs.md`): `profile_jobs` means "this offer belongs to this profile's feed" (no score); `job_matches(job_id, profile_id)` holds the score and its detail. Offers are never duplicated across profiles.
- `description_enrichment_source` is reserved for voluntary re-enrichment of an already known offer; it never describes collection.
