---
paths:
  - "dashboard/rocky/sources/**"
---

# Job sources

- A source implements the `JobSource` protocol (`base.py`): a `name` attribute and `search(profile, results_per_query) -> list[JobOffer]` returning normalized offers.
- Register a platform ONLY in `registry.py` (`build_watch_sources`); dashboard, cron, and diagnostics stay aligned automatically.
- `source_name` is the functional source (e.g. `Indeed`), `collector_name` the technical collector (e.g. `TheirStack`). Indeed is collected through the TheirStack Job Search API, never scraped.
- A platform that refuses an automated request is reported in the `PARTIAL` run summary; never bypass CAPTCHA, login, or anti-bot protection.
- TheirStack collection requests one page capped by `WATCH_RESULTS_PER_QUERY` to control credits.
- France Travail uses only the official Offres d'emploi v2 API (`/partenaire/offresdemploi/v2/offres/search`) with application OAuth credentials.
- `apec_detail.py` + `scripts/extract_apec_offer.py` use Playwright (visible browser by default, `--headless` flag). Playwright is NOT in `requirements.txt`. The script writes only `output/apec/<offer>.json`, never touches the DB, never clicks « Postuler ».
