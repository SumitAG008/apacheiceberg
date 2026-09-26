#!/usr/bin/env python3
"""Governance gate: fails CI when the decision trail, claim hygiene or CI integrity breaks.

Checks
  1. Every decision in docs/governance/DECISION_LOG.md links to an existing DEC file,
     IDs are unique, and each DEC has the required fields and sections.
  2. External-facing prose contains no unproven claim words (tamper-proof, guaranteed, ...),
     except known violations listed in KNOWN_CLAIM_VIOLATIONS until their expiry date.
  3. No workflow masks failures (`|| true`, `continue-on-error: true`).
  4. Risk-register rows past their review date are reported as warnings.

Run locally:  python tools/governance/check_governance.py
"""
import datetime
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOV = os.path.join(ROOT, "docs", "governance")
TODAY = datetime.date.today()

REQUIRED_FIELDS = ["Date (UTC)", "Type", "Status", "Decider", "Reversibility", "Review by"]
REQUIRED_SECTIONS = ["## Context", "## Options considered", "## Decision", "## Success / kill criteria"]

EXTERNAL_PROSE = [
    "README.md", "ETP_PRODUCT_OVERVIEW.md", "ETP_EXECUTIVE_PRESENTATION.md", "MSG-001-messaging-pack.md",
    "BC-002-etp-business-case.md", "help_guide.md", "business_case_guide.md", "product_blueprint.md",
    "help-site/**/*.md", "help-site/**/*.html",
]
FORBIDDEN_CLAIMS = re.compile(r"(?i)\b(tamper[- ]proof|guaranteed|certified|compliant with)\b")

# (file, phrase) -> expiry date. Existing debt only; new entries need a DEC record.
KNOWN_CLAIM_VIOLATIONS = {
    ("ETP_PRODUCT_OVERVIEW.md", "tamper-proof"): datetime.date(2026, 10, 10),  # RSK-005, CLM-002
    ("BC-002-etp-business-case.md", "tamper-proof"): datetime.date(2026, 10, 10),  # RSK-005, CLM-002
    ("product_blueprint.md", "certified"): datetime.date(2026, 10, 10),  # RSK-005, CLM-004
}

errors, warnings = [], []


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def check_decisions():
    log_path = os.path.join(GOV, "DECISION_LOG.md")
    if not os.path.exists(log_path):
        errors.append("docs/governance/DECISION_LOG.md is missing")
        return
    log = open(log_path, encoding="utf-8").read()
    ids = re.findall(r"^\|\s*\[(DEC-\d{4})\]\((decisions/[^)]+)\)", log, re.M)
    seen = set()
    for dec_id, link in ids:
        if dec_id in seen:
            errors.append(f"DECISION_LOG: duplicate {dec_id}")
        seen.add(dec_id)
        if not os.path.exists(os.path.join(GOV, link)):
            errors.append(f"DECISION_LOG: {dec_id} links to missing file {link}")

    for path in sorted(glob.glob(os.path.join(GOV, "decisions", "DEC-*.md"))):
        name = os.path.basename(path)
        if name.startswith("DEC-0000"):
            continue
        dec_id = name[:8]
        if dec_id not in seen:
            errors.append(f"{rel(path)}: not listed in DECISION_LOG.md")
        text = open(path, encoding="utf-8").read()
        for field in REQUIRED_FIELDS:
            if not re.search(rf"^\|\s*{re.escape(field)}\s*\|\s*\S", text, re.M):
                errors.append(f"{rel(path)}: missing field '{field}'")
        for section in REQUIRED_SECTIONS:
            if section not in text:
                errors.append(f"{rel(path)}: missing section '{section}'")


def check_claims():
    files = set()
    for pattern in EXTERNAL_PROSE:
        files.update(glob.glob(os.path.join(ROOT, pattern), recursive=True))
    for path in sorted(files):
        r = rel(path)
        for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            for m in FORBIDDEN_CLAIMS.finditer(line):
                phrase = m.group(1).lower().replace(" ", "-")
                expiry = KNOWN_CLAIM_VIOLATIONS.get((r, phrase))
                where = f"{r}:{n} '{m.group(1)}'"
                if expiry and TODAY < expiry:
                    warnings.append(f"{where}: known unproven claim, must be fixed or proven by {expiry} (CLAIMS_REGISTER)")
                elif expiry:
                    errors.append(f"{where}: known-violation grace period expired {expiry}")
                else:
                    errors.append(f"{where}: unproven claim word; add evidence to CLAIMS_REGISTER.md or reword")


def check_workflows():
    for path in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.y*ml")):
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\|\|\s*true\b", code) or re.search(r"continue-on-error:\s*true", code):
                errors.append(f"{rel(path)}:{n}: masked failure ({line.strip()})")


def check_risks():
    path = os.path.join(GOV, "RISK_REGISTER.md")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^\|\s*(RSK-\d+)\s*\|.*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*$", line)
        if m and datetime.date.fromisoformat(m.group(2)) < TODAY:
            warnings.append(f"RISK_REGISTER: {m.group(1)} review overdue (was due {m.group(2)})")


def report():
    lines = ["## Governance check", ""]
    lines += [f"- ❌ {e}" for e in errors] or ["- ✅ No blocking issues"]
    lines += [f"- ⚠️ {w}" for w in warnings]
    out = "\n".join(lines)
    print(out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(out + "\n")
    for e in errors:
        print(f"::error::{e}")
    for w in warnings:
        print(f"::warning::{w}")


if __name__ == "__main__":
    check_decisions()
    check_claims()
    check_workflows()
    check_risks()
    report()
    sys.exit(1 if errors else 0)
