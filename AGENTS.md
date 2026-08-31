# Rocky

Personal, explainable job-search assistant. Python 3.11+ / Streamlit monolith, SQLAlchemy; PostgreSQL locally, SQLite on the Hugging Face Space. Docstrings, UI text, DB status values, and docs are in French — keep that convention.

Detail lives in path-scoped `.claude/rules/`; each rule loads when you read a matching file.

## Commands

```bash
source .venv/bin/activate                     # project venv is mandatory
python -m pytest                              # full suite (offline, APIs mocked)
python -m pytest tests/test_llm.py -k credentials   # one test
python -m compileall dashboard scripts        # syntax check
python -m streamlit run dashboard/dashboard_v2.py   # run the app
python scripts/smoke_dashboard.py             # dashboard check against real DB, no server
python scripts/check_connections.py [--only apec]   # probe external APIs, keys never printed
```

## Layout and invariants

- UI in `dashboard/` (`dashboard_v2.py` is the single entry point); UI-free business layer in `dashboard/rocky/`.
- Single access points, never bypass them: `config.py` (.env), `repository.py` (SQL), `llm.py` (Mistral), `sources/registry.py` (source registration).
- The match score is deterministic (`matching.py`); the LLM never decides it.

## Hard rules

- Rocky never submits an application, never clicks « Postuler », never bypasses CAPTCHA/login/anti-bot; blocked sources are reported `PARTIAL`.
- Never log or echo secrets; error messages stay credential-free (tests enforce this).
- The Hugging Face Space stays private (CV and application data); secrets live in Space secrets.

## Keeping these docs honest

`AGENTS.md` and `.claude/rules/` are living documents: when your change makes a
rule stale, fix the doc in the same commit; when a new convention crystallizes,
add a rule. They guide upfront — never let them re-explain code that should
document itself.
