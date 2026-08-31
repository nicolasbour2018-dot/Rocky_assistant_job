---
paths:
  - "Dockerfile"
  - ".dockerignore"
  - "deployment/**"
  - "scripts/deploy_hf.py"
  - "scripts/activate_hf.py"
  - "scripts/check_hf_deployment.py"
  - "scripts/start_local.py"
---

# Deployment

- The Hugging Face Space stays PRIVATE (it holds the CV and application data). Secrets (Mistral, France Travail, Adzuna) live in Space secrets, never in the image or the repo.
- Split: `/app` read-only code, `/data` volume `rocky-data` with the SQLite DB and documents. Without the volume, data can vanish on Space restart.
- `scripts/activate_hf.py` performs the final switch and volume mount without deleting files; `deploy_hf.py` and `check_hf_deployment.py` handle push and verification.
- Local detached run: `.venv/bin/python scripts/start_local.py` (PID and logs under `logs/`, no system service).
