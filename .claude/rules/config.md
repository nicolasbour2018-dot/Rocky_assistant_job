---
paths:
  - "dashboard/rocky/config.py"
  - ".env.example"
---

# Configuration

- `config.py` is the ONLY module that reads `.env`; every other module receives a frozen `Settings` dataclass.
- `DATABASE_URL` overrides the five `DB_*` variables (SQLite on the HF Space, PostgreSQL locally).
- A new environment variable goes to three places: `Settings`, `.env.example`, README section 2.
