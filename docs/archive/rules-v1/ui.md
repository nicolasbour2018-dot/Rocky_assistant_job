---
paths:
  - "dashboard/*.py"
---

# Streamlit UI

- `dashboard_v2.py` is the single entry point; every page is registered there via `st.Page` (detail pages use `visibility="hidden"`).
- `dashboard_b.py` is the cockpit (default page); shared components live in `dashboard_common.py` and `job_detail_components.py`.
- Pages stay UI-only: no SQL, no `.env` reads, no direct API calls; go through `dashboard/rocky/`.
- All user-facing text is French.
- Check a UI change with `python scripts/smoke_dashboard.py` (real DB, no server) before launching Streamlit.
