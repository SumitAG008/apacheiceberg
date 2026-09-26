#!/usr/bin/env python3
"""PreToolUse hook (Bash): refuse git operations that destroy history or skip checks.

Blocks: force-push, pushing straight to main, --no-verify, reset --hard, and
branch -D on main. Changes reach main through a PR so CI and review run first.
"""
import json
import re
import sys

RULES = [
    (r"\bgit\s+push\b.*(\s--force(?!-with-lease)\b|\s-f\b)", "Force-push rewrites shared history."),
    (r"\bgit\s+push\b.*\s(origin\s+)?(HEAD:)?main\b", "Push to a branch and open a PR; main only changes through CI + review."),
    (r"--no-verify\b", "Skipping hooks bypasses the quality gates."),
    (r"\bgit\s+reset\s+--hard\b", "reset --hard discards work irreversibly."),
    (r"\bgit\s+branch\s+-D\s+main\b", "Deleting main is not allowed."),
]


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    for pattern, why in RULES:
        if re.search(pattern, cmd):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Governance guard: {why} (see docs/governance/README.md)",
            }}))
            return


if __name__ == "__main__":
    main()
