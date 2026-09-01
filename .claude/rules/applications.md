---
paths:
  - "dashboard/rocky/applications.py"
  - "dashboard/rocky/cv_tailoring.py"
  - "dashboard/rocky/browser_apply.py"
  - "scripts/prefill_application.py"
---

# Supervised application

- Prefill never identifies or clicks a submit button; the window stays open and the user sends the application themselves.
- The target URL is validated as http(s) before opening; otherwise `ConfigurationError`.
- `cv_tailoring.py` never modifies the source PDF: hash and page count are checked, redaction stays inside authorized zones. PyMuPDF is approved only in this module (see `ats.md`).
