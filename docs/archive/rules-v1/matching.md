---
paths:
  - "dashboard/rocky/matching.py"
  - "dashboard/job_analysis.py"
---

# Matching

- The score is deterministic and explainable, computed in `matching.py`; the LLM never decides it.
- Weights: skills 55, title 20, contract 8, location 8, remote 5, salary 4. Changing them changes every displayed score; update README section 4 in the same change.
- `dashboard/job_analysis.py` holds the skills dictionary the matcher relies on.
- `MATCH_THRESHOLD` (default 70) gates the daily watch.
