---
paths:
  - "dashboard/rocky/llm.py"
---

# LLM access

- `llm.py` is the ONLY Groq access point; model `groq/compound-mini`, API JSON mode, every structured output validated field by field.
- Error paths never expose credentials or raw SDK errors; `_safe_failure_detail` keeps at most an HTTP status. `tests/test_llm.py` enforces this.
- The Groq HTTP client is built per call; `is_configured` gates every use.
- The match score is never decided by the LLM (`matching.py` owns it).
