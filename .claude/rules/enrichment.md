---
paths:
  - "dashboard/rocky/enrichment.py"
  - "dashboard/rocky/theirstack.py"
  - "dashboard/page_enrichment.py"
  - "scripts/refresh_job_descriptions.py"
---

# Enrichment (TheirStack)

- Enrichment runs only on a voluntary user action, on an offer marked `INCOMPLÈTE`; TheirStack is never recorded as a collection source.
- Endpoint `POST /v1/jobs/search`: exact company name, title, limit 3 results to bound credit spend.
- A candidate result must pass title and company similarity thresholds, then be corroborated by an identical URL, a close date, or a compatible location.
- The description is kept only if untruncated and clearly longer than the Rocky preview.
- Rocky's id and collection provenance are preserved; only `description_enrichment_source=TheirStack` and the TheirStack id describe the enrichment.
- Reference: `docs/theirstack_enrichment.md`.
