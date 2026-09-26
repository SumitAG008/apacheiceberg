# AUDIT-YYYY-MM-DD: <scope>

| Field | Value |
|---|---|
| Auditor | auditor agent |
| Scope | full · plan · claims · decisions · ci · security · <custom> |
| Commit audited | `<sha>` on `<branch>` |
| Audit-trail check | `python .claude/hooks/audit_log.py --verify` → <result> |

## Verdict
🟢 On track · 🟡 Issues found · 🔴 Material problems (one paragraph)

## Findings
| # | Severity | Area | Finding | Evidence | Owner | Due |
|---|---|---|---|---|---|---|

Severity: **Critical** (false external claim, security hole, broken chain) · **High** · **Medium** · **Low**

## Checks performed
- [ ] Plan status matches code and tests (sample at least 5 "done" items and run their tests)
- [ ] Every ✅ claim in CLAIMS_REGISTER has evidence that still passes
- [ ] Every decision since the last audit has a DEC record written before its work started
- [ ] Risk register reviewed; overdue review dates flagged
- [ ] CI on `main` is green; no gates masked (`|| true`, `continue-on-error`, skipped tests)
- [ ] Audit-trail hash chain intact
- [ ] Findings from the previous audit: closed, or carried forward with a reason

## Carried forward from previous audit
| Finding | Status | Reason |
|---|---|---|
