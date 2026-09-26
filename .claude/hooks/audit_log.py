#!/usr/bin/env python3
"""PostToolUse hook: append a tamper-evident audit record for every change Claude makes.

Each line in .claude/audit/audit-log.jsonl carries the SHA-256 of the previous line
(`prev`) and of itself (`hash`), so deleting or editing any record breaks the chain.
Verify with:  python .claude/hooks/audit_log.py --verify

Secrets are redacted before anything is written. Never blocks Claude: any failure
exits 0 silently so a logging problem can't stop work.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
LOG = os.path.join(ROOT, ".claude", "audit", "audit-log.jsonl")
GENESIS = "0" * 64

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=\-]+"),
    re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|authorization)(\s*[:=]\s*|\s+)(\"[^\"]*\"|'[^']*'|\S+)"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)(postgres(?:ql)?|redis|mysql|mongodb)://[^\s:@/]+:[^\s@/]+@"),
]


def redact(text: str) -> str:
    for pat in SECRET_PATTERNS:
        if pat.groups >= 3:
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        elif pat.groups == 1:
            text = pat.sub(lambda m: f"{m.group(1)}://[REDACTED]@", text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


def line_hash(prev: str, body: str) -> str:
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def last_hash() -> str:
    if not os.path.exists(LOG):
        return GENESIS
    with open(LOG, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 8192))
        tail = f.read().decode("utf-8", "replace").strip().splitlines()
    return json.loads(tail[-1])["hash"] if tail else GENESIS


def git_branch() -> str:
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def summarize(tool: str, ti: dict) -> dict:
    if tool == "Bash":
        return {"command": redact(str(ti.get("command", "")))[:500],
                "description": str(ti.get("description", ""))[:200]}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if path:
        try:
            path = os.path.relpath(path, ROOT)
        except ValueError:
            pass
    out = {"file": path.replace("\\", "/")}
    if tool == "Write":
        out["bytes"] = len(str(ti.get("content", "")))
    elif tool == "Edit":
        out["replace_all"] = bool(ti.get("replace_all"))
    return out


def record(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "session": payload.get("session_id", ""),
        "agent": payload.get("agent_type") or "main",
        "tool": tool,
        "branch": git_branch(),
        **summarize(tool, payload.get("tool_input") or {}),
    }
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    prev = last_hash()
    body = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    entry["prev"] = prev
    entry["hash"] = line_hash(prev, body)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")


def verify() -> int:
    if not os.path.exists(LOG):
        print("No audit log yet.")
        return 0
    prev = GENESIS
    with open(LOG, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            e = json.loads(raw)
            h, p = e.pop("hash"), e.pop("prev")
            body = json.dumps(e, sort_keys=True, ensure_ascii=False)
            if p != prev or line_hash(p, body) != h:
                print(f"CHAIN BROKEN at line {n}")
                return 1
            prev = h
    print(f"OK: {n} records, chain intact, head={prev[:16]}")
    return 0


if __name__ == "__main__":
    if "--verify" in sys.argv:
        sys.exit(verify())
    try:
        record(json.load(sys.stdin))
    except Exception:
        pass
    sys.exit(0)
