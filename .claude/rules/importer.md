---
paths:
  - "dashboard/rocky/job_importer.py"
  - "dashboard/page_import_url.py"
---

# URL import

- `job_importer.py` reads an offer URL: JSON-LD first, HTML parsing as fallback.
- Some platforms (LinkedIn, Indeed, Welcome to the Jungle) block automated reads: show a clear error and keep the manual paste form working; never bypass the protection.
