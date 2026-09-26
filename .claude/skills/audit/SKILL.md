---
name: audit
description: Run an independent governance audit - verifies the tamper-evident audit trail, plan status vs tests, external claims, decision records, risks and CI integrity - and writes a dated report. Use weekly, before releases, or before investor/customer meetings.
argument-hint: [scope: full | plan | claims | decisions | ci | security]
---

# Audit

Scope: $ARGUMENTS (use `full` if empty)

1. Collect the inputs and pass them to the auditor:
   - `python .claude/hooks/audit_log.py --verify` (chain integrity)
   - `python tools/governance/check_governance.py`
   - The latest previous report in `docs/governance/audits/` (if any)
   - `git log --since="<date of last report, or 7 days>" --oneline`
2. Launch the `auditor` agent with the scope and those outputs. It writes
   `docs/governance/audits/AUDIT-<today>.md`.
3. Reply to the founder with the verdict (🟢/🟡/🔴), the counts by severity, the top 3 findings with
   owners, and the report path.
4. For each Critical or High finding, offer the next step, such as a `/decide`, a fix branch, or a
   claims rewording, but don't start fixing without the founder's go-ahead.
