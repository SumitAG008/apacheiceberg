# CLAUDE.md

meldra: verifiable energy data platform. FastAPI backend (`backend/`), DuckDB/Iceberg query engine
(`backend/query_engine/`), ETP verifier/gateway (`backend/etp/`), C++20 core (`cpp/`), React/Vite/TS
frontend (`frontend/vite-project/`). Deploys: Railway (backend), Vercel (frontend, help-site).

## Operating model — read `docs/governance/README.md`
- **Evidence over intent.** Cite `file:line`, a test run, a commit or a URL. Otherwise label it
  ASSUMPTION or UNKNOWN. Never invent numbers.
- **Done = a test that can fail proves it.**
- **Decisions are recorded before work starts:** `/decide` → `docs/governance/decisions/`.
- **External claims need evidence** in `docs/governance/CLAIMS_REGISTER.md`. Never write
  "tamper-proof", "guaranteed", "certified" or "compliant with X" unless it's ✅ there.
- **Plan of record:** `PROJECT_PLAN.md` (once merged). `NOVEMBER_GO_LIVE_ROADMAP.md` is historical,
  and its scorecard does not reflect the code.
- **Nothing reaches `main` without CI + review.** Work on a branch and open a PR. The git guard hook
  blocks direct pushes, force-push, `--no-verify` and `reset --hard`.
- Never mask a failing check (`|| true`, `continue-on-error`, skipped tests). The governance gate fails on it.

## Leadership agents (`.claude/agents/`)
project-planner · chief-strategist · cfo · cto · strategic-initiatives · gtm-lead · code-checker
(read-only) · release-engineer · auditor (read-only except audit reports)

## Commands
`/board-review <question>` · `/decide <decision>` · `/plan-update` · `/ship-check` · `/audit [scope]`

## Verify locally
```bash
python tools/governance/check_governance.py
python -m ruff check backend --select E9,F63,F7,F82 --exclude backend/warehouse,backend/data
python .claude/hooks/audit_log.py --verify
```
Backend tests: from `backend/`, use `.venv/Scripts/python.exe -m pytest <file> -q` with the env vars
from `.github/workflows/ci-cd.yml` (`ENVIRONMENT=development`, `JWT_SECRET_KEY`, `ETP_SECRET_KEY`).
