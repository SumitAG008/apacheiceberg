# Governance Operating Model

How decisions get made, recorded, shipped and audited on this platform. It applies to the humans
and to every Claude agent in [`.claude/agents/`](../../.claude/agents/).

**Owner:** Sumit Sen (founder; final say on every decision)
**Created:** 2026-09-26

---

## 1. Ground rules (apply to everyone)

1. **Evidence over intent.** Every claim cites evidence: `file:line`, a test name, a commit, a CI
   run, or a source URL. Anything without evidence is labelled **ASSUMPTION** or **UNKNOWN**.
2. **No invented numbers.** Financials, market sizes, customer counts and benchmarks come from a
   cited source or are marked as assumptions with the reasoning shown.
3. **"Done" means a test that can fail proves it.** Nothing is marked done because code exists.
4. **Every decision is written down** in [`decisions/`](decisions/) before work starts on it.
5. **Nothing reaches `main` without CI + review.** Enforced by the git guard hook and branch rules.
6. **The founder decides.** Agents recommend, dissent is recorded, and the founder signs off.

## 2. Source-of-truth documents

| Document | What it holds | Owner agent |
|---|---|---|
| `PROJECT_PLAN.md` (repo root, once merged) | What we build, in what order, and why; status; change log | project-planner |
| [`DECISION_LOG.md`](DECISION_LOG.md) + [`decisions/`](decisions/) | Every strategic, financial, technical and GTM decision | chief-strategist |
| [`INITIATIVES.md`](INITIATIVES.md) | Portfolio of strategic initiatives with stage gates and kill criteria | strategic-initiatives |
| [`RISK_REGISTER.md`](RISK_REGISTER.md) | Open risks, owner, mitigation, review date | cto (tech) / cfo (financial) |
| [`FINANCE_MODEL.md`](FINANCE_MODEL.md) | Costs, pricing, unit economics, runway, with every assumption labelled | cfo |
| [`CLAIMS_REGISTER.md`](CLAIMS_REGISTER.md) | Every external claim, with the evidence that proves it or "not yet" | gtm-lead |
| [`audits/`](audits/) | Dated audit reports | auditor |
| [`../adr/`](../adr/) | Architecture decision records | cto |
| `NOVEMBER_GO_LIVE_ROADMAP.md` | **Historical.** Its readiness scorecard does not reflect the code | none |

## 3. The leadership team (Claude subagents)

| Role | Agent | Decides / owns | Can edit |
|---|---|---|---|
| Project Planner | `project-planner` | Sequencing, milestones, plan status, change log | Plan + governance docs |
| Chief Strategist | `chief-strategist` | Frames strategic decisions, convenes the board, writes DEC records | Governance docs |
| CFO | `cfo` | Costs, pricing, unit economics, runway, ROI of initiatives | FINANCE_MODEL, risk register |
| CTO | `cto` | Architecture, tech debt, security posture, build vs buy, ADRs | ADRs, risk register |
| Strategic Initiatives | `strategic-initiatives` | Initiative portfolio, stage gates, kill/continue calls | INITIATIVES |
| GTM Lead | `gtm-lead` | ICP, positioning, messaging, pricing page, claim hygiene | CLAIMS_REGISTER, messaging docs |
| Code Checker | `code-checker` | Reviews diffs for correctness, security and tests | Nothing (read-only + runs tests) |
| Release Engineer | `release-engineer` | CI/CD pipelines, deploy health, release gates | `.github/workflows/`, deploy config |
| Auditor | `auditor` | Independent check that the other roles did what they claim | `audits/` only |

The auditor never audits its own work, and never edits what it audits.

## 4. Processes (slash commands in Claude Code)

| Command | When | What happens | Output |
|---|---|---|---|
| `/board-review <topic>` | Any strategic question | CFO, CTO, GTM and Initiatives each assess; Strategist synthesises and recommends | Draft `DEC-NNNN` for founder sign-off |
| `/decide <decision>` | A decision has been made | Records it with options, rationale, reversibility and review date | `decisions/DEC-NNNN-*.md` + log row |
| `/plan-update` | After any change of direction | Planner updates plan status and change log | `PROJECT_PLAN.md` diff |
| `/ship-check` | Before opening a PR | Code Checker reviews the diff, tests run, Auditor checks new claims | Pass/fail report |
| `/audit [scope]` | Weekly, or before a release or investor meeting | Auditor verifies plan, claims, decisions, CI and the audit trail | `audits/AUDIT-YYYY-MM-DD.md` |

## 5. Automation and audit trail

| Layer | Mechanism | Where |
|---|---|---|
| Every Claude edit and command | PostToolUse hook, hash-chained, secrets redacted | `.claude/audit/audit-log.jsonl` (local, gitignored) |
| Verify the trail hasn't been altered | `python .claude/hooks/audit_log.py --verify` | Run by `/audit` |
| Destructive git blocked | PreToolUse guard: force-push, push to main, `--no-verify`, `reset --hard` | `.claude/hooks/git_guard.py` |
| Every PR | Tests, C++ sanitizers, Docker build (existing pipeline) | `.github/workflows/ci-cd.yml` |
| Every PR | Lint, security scan, secret scan, dependency audit, governance checks | `.github/workflows/code-quality.yml` |
| Every PR | Claude code review against the Code Checker rubric | `.github/workflows/claude-review.yml` |
| Weekly (Mon 07:00 UTC) | Claude governance audit, filed as a GitHub issue | `.github/workflows/weekly-audit.yml` |
| Permanent record | Git history of `docs/governance/` + PR reviews + CI logs | GitHub |

## 6. Decision rights (RACI)

R = responsible, A = accountable, C = consulted, I = informed.

| Decision type | R | A | C | I |
|---|---|---|---|---|
| Strategy / market / positioning | chief-strategist | Founder | cfo, cto, gtm-lead | all |
| Pricing / spend over budget | cfo | Founder | gtm-lead, chief-strategist | all |
| Architecture / security | cto | Founder | code-checker, release-engineer | all |
| Start / kill an initiative | strategic-initiatives | Founder | cfo, cto, gtm-lead | all |
| External claim / messaging | gtm-lead | Founder | cto (evidence), auditor | all |
| Merge to main | release-engineer | Founder | code-checker | all |
