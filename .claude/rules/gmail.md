---
paths:
  - "dashboard/rocky/gmail_service.py"
  - "dashboard/rocky/scheduler.py"
  - "scripts/run_daily.py"
---

# Gmail and daily run

- `gmail_service.py` requests only the `gmail.readonly` scope; it never sends or modifies email.
- The full email body is never stored; email content is untrusted: only local patterns and links to allowlisted job domains are interpreted.
- `scripts/run_daily.py` orchestrates Gmail triage then the watch under an exclusive `fcntl` lock; one run at a time.
- `scheduler.py` is a fallback active while Rocky runs; the system cron stays the documented path.
