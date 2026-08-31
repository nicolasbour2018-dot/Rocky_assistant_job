---
paths:
  - "dashboard/rocky/watch.py"
  - "dashboard/rocky/statuses.py"
  - "dashboard/page_monitoring.py"
  - "scripts/run_watch.py"
  - "cron/**"
---

# Daily watch

- `watch.py` orchestrates: sources from `registry.py`, hydration of incomplete offers via `job_importer`, matching, then per-source detail in the `watch_runs` table and `logs/veille.log`.
- Incomplete offers are kept with `INCOMPLETE_STATUS`; `SOURCE_REFRESH_FIELDS` lists the fields a source refresh may overwrite.
- A blocked platform yields a `PARTIAL` summary; never bypass its protection.
- Scheduling: `cron/rocky.cron.example` at 07:30 (installed manually with `crontab -e`); the HF Space runs an internal 07:30 Paris scheduler and catches up at next startup if it slept.
