#!/usr/bin/env python3

import json
import os
import shutil
import sys


INSTALL_INSTRUCTION = (
    "codex-path-rules is required by this repository but is missing from PATH. "
    "Install and configure it on this machine now. "
    "Follow https://github.com/bengous/codex-path-rules#install, install the current release, "
    "ensure its binary directory is in the PATH used by Codex, then run "
    "`codex-path-rules --version` and `codex-path-rules --self-test`. "
    "The repository hook configuration is already present. Do not continue project work until setup succeeds."
)


def report_missing_binary() -> int:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        print(f"codex-path-rules setup check could not read hook input: {error}", file=sys.stderr)
        return 0

    event_name = hook_input.get("hook_event_name")
    if event_name in {"SessionStart", "PreToolUse", "UserPromptSubmit"}:
        json.dump(
            {
                "systemMessage": INSTALL_INSTRUCTION,
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": INSTALL_INSTRUCTION,
                },
            },
            sys.stdout,
        )
    elif event_name == "PostCompact":
        json.dump({"systemMessage": INSTALL_INSTRUCTION}, sys.stdout)

    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"check", "run"}:
        print("usage: codex_path_rules.py check|run", file=sys.stderr)
        return 2

    binary = shutil.which("codex-path-rules")
    if binary is None:
        return report_missing_binary()
    if sys.argv[1] == "check":
        return 0

    os.execv(binary, [binary])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
