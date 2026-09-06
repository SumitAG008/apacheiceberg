# How to apply this

**Generated:** 2026-09-05T14:20:00Z
**Against:** `SumitAG008/apacheiceberg` @ main (clone of 2026-09-05)

## 1. Apply the patch

```powershell
cd C:\Users\sumit\Documents\icebergAgent
git checkout -b sec-2026-remediation
git am ..\meldra-remediation-2026-09-05.patch
```

If `git am` rejects (your local tree has drifted from GitHub main):

```powershell
git apply --3way ..\meldra-remediation-2026-09-05.patch
```

## 2. Verify

```powershell
cd backend
pip install -r requirements.txt
python -m pytest tests/test_sec_2026_regressions.py -v
```

Expect **16 passed**. These are the tests that pin the security fixes — if
any fails, a confidentiality control has regressed. Do not skip them.

Then the full suite (needs Postgres running):

```powershell
python -m pytest tests/ -q
```

## 3. Set these before deploying

| Variable | Set to | Why |
|---|---|---|
| `MELDRA_ENV` | `production` | Turns on the fail-closed tenant guard by default |
| `MELDRA_AUDIT_LOG_PATH` | e.g. `/var/log/meldra/audit.jsonl` | File sink; stdout always mirrors |
| `MELDRA_REQUIRE_TENANT_SCOPE` | leave unset | Defaults correctly from `MELDRA_ENV` |

Do **not** set `MELDRA_REQUIRE_TENANT_SCOPE=0` in production — it re-opens
SEC-2026-001. Every unscoped job is audited either way, so you will see it
in the log if someone does.

## 4. Then do these three things

1. **SEC-2026-001 action A-4** — inventory unprefixed namespaces in every
   deployed environment. The code is fixed; legacy unprefixed namespaces
   may still exist and were readable cross-tenant before this patch.
2. **SEC-2026-001 action A-6** — decide, as data controller, whether any
   real customer data sat in an unprefixed namespace. If yes, the UK GDPR
   Art. 33 72-hour clock is a legal question, not an engineering one.
   Remediating the code does not discharge a notification obligation.
3. **GAP-01** — inference egress. Read
   `docs/architecture/04-security-architecture.md` §6. This is the item
   that decides whether a regulated pilot is possible at all.

## 5. What's in the patch

| Area | Files |
|---|---|
| Security fixes | `backend/tools.py`, `backend/api/main.py`, `backend/query_engine/sql_executor.py`, `backend/query_engine/python_executor.py` |
| Zero-copy path | `backend/query_engine/sql_executor.py`, `sql_backends.py`, `rbac_utils.py`, `models.py` |
| Correctness | `backend/meldra/catalog.py` |
| Audit logging | `backend/observability/` (new) |
| Regression tests | `backend/tests/test_sec_2026_regressions.py` (new, 16 tests) |
| Documentation | `docs/` — 16 documents |

Nothing in the patch changes the behaviour of `enforce_rbac()` itself. The
masking and filtering logic is untouched; only the paths *reaching* it were
changed, plus a fail-closed fast-path probe alongside it.
