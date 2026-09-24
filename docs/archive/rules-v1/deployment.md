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

- Rocky is currently run natively on macOS; GitHub `main` is the delivery target.
- Keep `.env`, `.secrets/`, `data/`, `logs/`, and `backups/` outside commits.
- Local detached run: `.venv/bin/python scripts/start_local.py` (PID and logs under `logs/`, no system service).
- Hugging Face deployment scripts remain historical tooling and are not part of this local release.
