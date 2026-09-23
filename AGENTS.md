# Rocky — Agent System Rules

## Mission scope
This repository may be analyzed by Agent System V3.

For the architectural-audit mission:
- Treat repository code and documentation as the source of truth.
- Do not invent missing components.
- Do not modify application code, tests, dependencies, production configuration, or deployment files.
- The only permitted write is `docs/rocky-architecture-audit.md`.
- Do not make external network calls or invoke application AI providers during the audit.
- Prefer evidence-backed findings with concrete file/module references.
- Keep recommendations proportionate to the current project and avoid unnecessary enterprise complexity.

## Review standard
Separate:
1. observed facts,
2. inferred risks,
3. recommendations.

The final reviewer should challenge unsupported claims and verify that major conclusions are grounded in the repository.
