# DEC-0001: Adopt the governance operating model

| Field | Value |
|---|---|
| Date (UTC) | 2026-09-26 |
| Type | Operating model |
| Status | Accepted |
| Decider | Founder (Sumit Sen) |
| Recommended by | Claude Code (setup session) |
| Reversibility | Two-way door: agents, commands and workflows can be removed without touching product code |
| Review by | 2026-10-26 |

## Context
The founder asked for project planning, strategic decisions, CFO, CTO, strategic-initiative and
GTM roles, a code checker, and CI/CD, with the processes automated and everything audited.

Evidence of the gap:
- `SESSION_LOG.md` records open findings that had not been triaged: a deletable audit trail, no
  security headers, two competing CI/CD configs, and no dependency or image scanning.
- A separate session found that `NOVEMBER_GO_LIVE_ROADMAP.md` reported 92% readiness that the code
  did not support.
- Before this decision the repo had no decision log, no initiative register and no claims register.

## Options considered
| Option | For | Against |
|---|---|---|
| A. Claude subagents + slash commands + hooks + CI (chosen) | Lives in the repo, versioned, runs where the work happens, auditable | Agents are advisory; the founder still has to decide |
| B. External PM/BI tools | Richer dashboards | Separate from the code, so claims drift from reality again |
| Do nothing | No setup cost | The roadmap-drift problem repeats |

## Decision
Adopt the model in [`../README.md`](../README.md): nine role agents, five process commands, a
hash-chained local audit trail, a git safety guard, and CI gates for quality, security, Claude
review and a weekly governance audit.

## Consequences
- Claude cannot push to `main` directly; changes go through a branch and PR.
- Every strategic decision needs a DEC record before work starts.
- Every external claim needs an entry in `CLAIMS_REGISTER.md` with evidence.
- The Claude review and weekly audit workflows need an `ANTHROPIC_API_KEY` (or
  `CLAUDE_CODE_OAUTH_TOKEN`) repository secret, which only the founder can add.

## Success / kill criteria (at 2026-10-26)
- At least 3 DEC records exist and each was written before its work started.
- The weekly audit ran at least 3 times, and its findings were triaged within 7 days.
- No commit reached `main` without a passing CI run.
- If the process costs more time than it saves, cut it back to planner + code-checker + auditor.

## Assumptions
- ASSUMPTION: GitHub branch protection on `main` will be turned on by the founder (it can't be set
  from inside the repo).
