# Rocky

Personal, explainable job-search assistant.

Python 3.11+ / Streamlit monolith, SQLAlchemy; PostgreSQL locally, SQLite on the Hugging Face Space.

Docstrings, UI text, DB status values, and docs are in French — keep that convention.

Detail lives in path-scoped `.claude/rules/`; each rule loads when you read a matching file.

## Commands

```bash
source .venv/bin/activate
python -m pytest
python -m pytest tests/test_llm.py -k credentials
python -m compileall dashboard scripts
python -m streamlit run dashboard/dashboard_v2.py
python scripts/smoke_dashboard.py
python scripts/check_connections.py [--only apec]
```

The project virtual environment is mandatory.

The full pytest suite is expected to run offline with APIs mocked.

Do not invoke external API probes during an architectural audit unless the mission explicitly requires it.

## Layout and invariants

* UI lives in `dashboard/`.
* `dashboard/dashboard_v2.py` is the single UI entry point.
* UI-free business logic lives in `dashboard/rocky/`.
* Do not bypass the project's canonical access points:

  * `config.py` for environment/configuration
  * `repository.py` for SQL access
  * `llm.py` for LLM access
  * `sources/registry.py` for source registration
* The match score is deterministic and implemented in `matching.py`.
* The LLM must never determine the match score.

## Hard rules

* Rocky never submits an application.
* Rocky never clicks « Postuler ».
* Rocky never bypasses CAPTCHA, authentication, login or anti-bot protections.
* Blocked sources are reported `PARTIAL`.
* Never log, expose or echo secrets.
* Error messages must remain credential-free.
* The Hugging Face Space remains private because it may contain CV and application data.
* Deployment secrets belong in Space secrets.

# Agent System V3

## Source of truth

Repository code, tests, configuration and documentation are the source of truth.

Do not invent components, flows, services, integrations or architectural properties that cannot be supported by repository evidence.

When documentation and implementation disagree, explicitly report the discrepancy rather than silently choosing one.

## Architectural audit mission

For `rocky-architecture-audit-v1-2026-09-23`, the repository is being audited, not refactored.

The objective is to understand and assess the architecture as it currently exists.

Distinguish clearly between:

1. observed facts,
2. inferred risks,
3. recommendations.

Important conclusions should be traceable to concrete files, modules, tests, configuration or observed code paths.

## Write boundary

During the architectural audit:

* Do not modify application source code.
* Do not modify tests.
* Do not modify dependencies.
* Do not modify production or deployment configuration.
* Do not perform refactoring.
* Do not fix issues discovered during the audit.

The only permitted mission output is:

`docs/rocky-architecture-audit.md`

## Network and external services

Do not make external network calls for the architectural audit.

Do not invoke Rocky's production LLM provider or external job-source APIs merely to understand the architecture.

Prefer static repository inspection and offline tests where validation is necessary.

## Audit scope

Inspect the implementation that actually exists, including where applicable:

* Streamlit UI and navigation
* business/domain layer
* PostgreSQL / SQLite persistence
* repositories and data access
* job-source ingestion and normalization
* deterministic matching
* LLM integration
* scheduling/background execution
* configuration and secrets boundaries
* error handling and resilience
* tests
* coupling between modules
* separation of responsibilities
* observability
* maintainability and testability
* deployment assumptions

Do not assume that a feature exists simply because it appears in old documentation.

## Recommendations

Recommendations must remain proportional to Rocky's actual needs and maturity.

Avoid introducing enterprise-scale infrastructure, distributed systems, microservices or additional abstraction unless a concrete problem in the existing repository justifies it.

For significant recommendations, describe:

* the observed problem,
* why it matters,
* the proposed direction,
* expected benefit,
* approximate implementation effort,
* migration or regression risk.

Do not design a complete replacement architecture before documenting the current architecture.

## Review standard

The `general_reviewer` should challenge:

* unsupported architectural claims,
* recommendations not grounded in observed problems,
* accidental modifications outside the allowed output,
* inconsistencies between findings and repository evidence,
* unnecessary architectural complexity.

The final audit must make clear where evidence is strong, where a conclusion is inferred, and where the repository does not provide enough information to conclude.
