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
- Scheduling: `cron/rocky.cron.example` at 12:00 Europe/Paris (installed manually with `crontab -e`).
