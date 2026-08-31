---
paths:
  - "dashboard/rocky/llm.py"
---

# LLM access

- `llm.py` is the ONLY Mistral access point; model `mistral-small-latest`, SDK JSON mode, every structured output validated field by field.
- Error paths never expose credentials or raw SDK errors; `_safe_failure_detail` keeps at most an HTTP status. `tests/test_llm.py` enforces this.
- The Mistral client is imported lazily and built per call; `is_configured` gates every use.
- The match score is never decided by the LLM (`matching.py` owns it).
