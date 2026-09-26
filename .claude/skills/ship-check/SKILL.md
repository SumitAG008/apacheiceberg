---
name: ship-check
description: Pre-PR gate - code-checker reviews the diff, the CI test suites run locally, the governance check runs, and new external claims are verified. Use before opening a PR or when asked "is this ready to ship?".
argument-hint: [base branch, default main]
---

# Ship check

Base branch: $ARGUMENTS (use `main` if empty)

Run these, in parallel where independent:

1. **Code review:** launch the `code-checker` agent on `git diff <base>...HEAD` plus uncommitted
   changes.
2. **Governance:** `python tools/governance/check_governance.py`
3. **Lint gate:** `python -m ruff check backend --select E9,F63,F7,F82 --exclude backend/warehouse,backend/data`
4. **Tests for what changed:** map the changed files to their suites, as in
   `.github/workflows/ci-cd.yml`, and run them from `backend/` with the CI environment variables
   (`ENVIRONMENT=development`, `JWT_SECRET_KEY`, `ETP_SECRET_KEY` as in the workflow). Use
   `backend/.venv/Scripts/python.exe` when it exists. For frontend changes, run
   `npx tsc --noEmit` in `frontend/vite-project`.
5. **Claims:** if the diff touches docs, the help site or UI copy, check each capability statement
   against `docs/governance/CLAIMS_REGISTER.md`.

## Verdict
- **READY:** code-checker PASS or PASS WITH NOTES, and all commands green.
- **NOT READY:** list each blocker with its fix. Never report a check as passing without having run it.

If READY and the founder asks to ship: create a branch if on `main`, commit, push the branch, and
open a PR. Direct pushes to `main` are blocked by the git guard.
