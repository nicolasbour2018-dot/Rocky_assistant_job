---
paths:
  - "tests/**"
  - "pyproject.toml"
---

# Tests

- Tests run offline: no network, no API credit spend. Mistral and API clients are mocked (monkeypatch pattern in `tests/test_llm.py`).
- Repository tests use SQLite under `tmp_path` via `Settings(database_url_override=...)` (pattern in `tests/test_sqlite_repository.py`).
- Pytest config lives in `pyproject.toml`: `testpaths = tests`, `pythonpath = .`, `addopts = -q`.
- `tests/test_llm.py` asserts error messages never expose credentials; keep that guarantee.
- One file: `python -m pytest tests/test_matching.py`; one test: `python -m pytest tests/test_llm.py -k credentials`.
