"""Cases for guard_paths.py. Run: /usr/bin/python3 .claude/hooks/check_guard_paths.py"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().with_name("guard_paths.py")
P = str(HOOK.parents[2])
W = str(HOOK.parents[3] / "Rocky_v1")

# (tool, input, expected: "deny" | "allow")
CASES = [
    # secrets: always denied
    ("Read", {"file_path": f"{P}/.env"}, "deny"),
    ("Read", {"file_path": ".env.local"}, "deny"),
    ("Read", {"file_path": f"{P}/.secrets/gmail/credentials.json"}, "deny"),
    ("Grep", {"pattern": "KEY", "path": ".env"}, "deny"),
    ("Write", {"file_path": f"{P}/token.json", "content": ""}, "deny"),
    ("Bash", {"command": "cat .env"}, "deny"),
    ("Bash", {"command": "grep GROQ ../Rocky_v1/.env"}, "deny"),
    ("Bash", {"command": "ls .secrets/gmail"}, "deny"),
    ("Bash", {"command": "cp credentials.json /tmp"}, "deny"),
    # secret-looking but allowed
    ("Read", {"file_path": f"{P}/.env.example"}, "allow"),
    ("Edit", {"file_path": ".env.example"}, "allow"),
    ("Bash", {"command": "cat .env.example"}, "allow"),
    ("Bash", {"command": "python -m dotenv --help"}, "allow"),
    ("Bash", {"command": "ls rocky/system/environment.py"}, "allow"),
    # old Rocky: readable, not writable
    ("Read", {"file_path": f"{P}/dashboard/rocky/matching.py"}, "allow"),
    ("Edit", {"file_path": f"{P}/dashboard/rocky/matching.py"}, "deny"),
    ("Write", {"file_path": "scripts/new.py"}, "deny"),
    ("Write", {"file_path": f"{P}/Dockerfile"}, "deny"),
    ("Write", {"file_path": f"{P}/compose.yaml"}, "deny"),
    ("Edit", {"file_path": f"{P}/tests/test_matching.py"}, "deny"),
    ("Write", {"file_path": f"{P}/backups/x.txt"}, "deny"),
    ("Edit", {"file_path": f"{P}/docs/archive/rocky-refonte-plan.md"}, "deny"),
    ("Edit", {"file_path": f"{W}/dashboard/dashboard_v2.py"}, "deny"),
    ("Read", {"file_path": f"{W}/dashboard/dashboard_v2.py"}, "allow"),
    # new Rocky: writable
    ("Write", {"file_path": f"{P}/rocky/offres/scoring.py"}, "allow"),
    ("Write", {"file_path": f"{P}/tests/offres/test_scoring.py"}, "allow"),
    ("Write", {"file_path": f"{P}/tests/conftest.py"}, "allow"),
    ("Edit", {"file_path": f"{P}/docs/rocky-refonte-plan-v2.md"}, "allow"),
    ("Write", {"file_path": f"{P}/docs/decisions/A2-cadrage.md"}, "allow"),
    ("Edit", {"file_path": f"{P}/pyproject.toml"}, "allow"),
    ("Write", {"file_path": f"{P}/docker-compose.yml"}, "allow"),
    ("Edit", {"file_path": f"{P}/AGENTS.md"}, "allow"),
    ("Write", {"file_path": "/private/tmp/scratch/notes.md"}, "allow"),
    ("Bash", {"command": "git status"}, "allow"),
]

env = dict(os.environ, CLAUDE_PROJECT_DIR=P)
failures = 0
for tool, tool_input, expected in CASES:
    out = subprocess.run(
        ["/usr/bin/python3", HOOK],
        input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        capture_output=True, text=True, cwd=P, env=env, check=False,
    )
    got = "deny" if '"deny"' in out.stdout else "allow"
    if out.returncode != 0 or out.stderr:
        got = f"error: {out.stderr.strip()}"
    ok = got == expected
    failures += not ok
    print(f"{'ok ' if ok else 'KO '} {expected:5} {tool:6} {json.dumps(tool_input)[:80]}" + ("" if ok else f"  -> {got}"))
print(f"\n{len(CASES) - failures}/{len(CASES)} cases pass")
sys.exit(1 if failures else 0)
