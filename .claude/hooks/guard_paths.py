#!/usr/bin/env python3
"""PreToolUse guard for the Rocky rewrite (see AGENTS.md, section 3).

Denies:
- any access (read, write, search, shell mention) to secrets;
- any write, through file tools, to the old Rocky, its data, the archive and the old-Rocky worktree.

Shell commands are only checked for secret mentions: writes through Bash stay governed by AGENTS.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]).resolve()
OLD_ROCKY_WORKTREE = (PROJECT.parent / "Rocky_v1").resolve()

READ_TOOLS = {"Read", "Grep", "Glob"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Old Rocky and its runtime artefacts: read-only until the switch-over (step F2).
LEGACY_DIRS = (
    "dashboard", "database", "scripts", "cron", "templates", "deployment", "assets",
    ".streamlit", "output", "data", "logs", "backups", "docs/archive",
)
LEGACY_FILES = {"Dockerfile", ".dockerignore", "compose.yaml", "requirements.txt"}
LEGACY_TEST = re.compile(r"^tests/test_[^/]*$")  # old tests are flat; new ones live in tests/<module>/

SECRET_NAME = re.compile(r"^(\.env(\.(?!example$)[\w.-]+)?|credentials[\w.-]*\.json|token[\w.-]*\.json)$")
SECRET_DIRS = {".secrets"}
SECRET_IN_SHELL = re.compile(
    r"(?<![\w.-])(\.env(\.(?!example\b)[\w-]+)?|\.secrets/?|credentials[\w.-]*\.json|token[\w.-]*\.json)(?![\w.-])"
)


def relative(path_value: str) -> PurePosixPath | None:
    """Path relative to the project, or None when outside it."""
    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT / path
    try:
        return PurePosixPath(path.resolve().relative_to(PROJECT).as_posix())
    except ValueError:
        return None


def is_secret(path_value: str) -> bool:
    parts = PurePosixPath(Path(path_value).as_posix()).parts
    return any(p in SECRET_DIRS for p in parts) or bool(parts and SECRET_NAME.match(parts[-1]))


def is_legacy(path_value: str) -> bool:
    absolute = Path(path_value) if Path(path_value).is_absolute() else PROJECT / path_value
    if absolute.resolve().is_relative_to(OLD_ROCKY_WORKTREE):
        return True
    rel = relative(path_value)
    if rel is None:
        return False
    text = rel.as_posix()
    return (
        text in LEGACY_FILES
        or any(text == d or text.startswith(d + "/") for d in LEGACY_DIRS)
        or bool(LEGACY_TEST.match(text))
    )


def paths_of(tool_input: dict) -> list[str]:
    keys = ("file_path", "notebook_path", "path")
    return [str(tool_input[k]) for k in keys if tool_input.get(k)]


def check(tool_name: str, tool_input: dict) -> str | None:
    if tool_name == "Bash":
        match = SECRET_IN_SHELL.search(str(tool_input.get("command", "")))
        if match:
            return f"the command mentions a secret ({match.group(1)}); secrets are never read or written by agents"
        return None
    for value in paths_of(tool_input):
        if is_secret(value):
            return f"{value} is a secret; secrets are never read or written by agents"
        if tool_name in WRITE_TOOLS and is_legacy(value):
            return f"{value} belongs to the old Rocky or its data (read-only until F2)"
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    reason = check(payload.get("tool_name", ""), payload.get("tool_input") or {})
    if reason:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked by .claude/hooks/guard_paths.py: {reason}. "
                        "See AGENTS.md section 3. Do not work around it; ask Nicolas."
                    ),
                }
            },
            sys.stdout,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
