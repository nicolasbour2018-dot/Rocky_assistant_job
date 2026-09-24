---
paths:
  - "dashboard/rocky/letters.py"
  - "templates/**"
---

# Application documents

- `letters.py` produces the cover-letter preview, DOCX, and PDF from `templates/lettre_motivation.txt`.
- Output goes to `output/candidatures/`, which must be writable; the profile CV must be a PDF.
- Rocky prepares documents and opens the official form; it never submits an application.
