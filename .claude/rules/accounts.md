---
paths:
  - "dashboard/rocky/auth.py"
  - "dashboard/rocky/projects.py"
  - "dashboard/rocky/profile_documents.py"
  - "dashboard/rocky/language.py"
---

# Accounts and profiles

- `auth.py` never stores a raw token: SHA-256 fingerprint only; public responses stay neutral so they never reveal whether an account exists.
- `projects.py` parses a Markdown file of `## title` blocks with `Key: value` fields; duplicates and projects without enough facts are refused (no invented CV content).
- `language.py` detects FR/EN locally and deterministically, never via LLM.
