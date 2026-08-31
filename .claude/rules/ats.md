---
paths:
  - "dashboard/rocky/ats.py"
  - "dashboard/rocky/ats_v3.py"
  - "dashboard/page_ats_v3.py"
  - "scripts/run_ats_v3.py"
---

# ATS analysis

- ATS V3 (`ats_v3.py`) is a standalone robustness bench, independent from V1/V2 (`ats.py`): it reads the actually uploaded PDF/DOCX, ignores profile skills, never corrects extracted text silently, never uses an LLM verdict.
- PDF: three engines run separately and are compared — pypdf, pdfminer.six, pypdfium2. DOCX: python-docx versus a raw OOXML read.
- `pdftotext -layout` (Poppler) is an optional local diagnostic; it never enters the scores.
- PyMuPDF is excluded from ATS extraction and scoring. Its only approved use is the isolated `cv_tailoring.py` renderer, which edits bounded zones of a user-provided CV without contributing to ATS results.
- Method and provenance: `docs/ats_v3_methodology.md`.
