# OPS-001 — Logging, audit and error handling standard

**Document ID:** OPS-001 · **Version:** 1.0 · **Issued:** 2026-09-05T14:00:00Z
**Component:** `backend/observability/audit_log.py` · **Status:** Baseline

---

## 1. Why a standard rather than a logger

Under NIS Regulations Reg. 10, NCSC CAF objective C1, and the DCC Smart
Energy Code security obligations, a platform touching grid or metering data
must be able to answer, months after the fact:

> On 14 March at 02:11 UTC, who read which table, under which role, from
> which tenant, and what did the platform decide?

`logger.info("query ran")` cannot answer that. Neither can a log with local
timestamps, or one where the format changes between modules. This standard
exists so the answer is reconstructable without heroics.

---

## 2. Record format

One JSON object per line. Every record carries:

| Field | Type | Notes |
|---|---|---|
| `timestamp` | string | **UTC ISO-8601, millisecond precision, explicit `Z`** |
| `event_id` | uuid | Unique per record |
| `request_id` | string | Correlates all records from one HTTP request |
| `action` | string | Dotted verb: `query.execute`, `rbac.check`, `auth.login`, `snapshot.expire` |
| `outcome` | enum | `allow` \| `deny` \| `error` |
| `tenant_id` | string | `""` means unscoped — itself alert-worthy on a data path |
| `role` | string | Role the decision was evaluated against |
| `subject` | string | JWT `sub`, not an email |
| `resource` | string | `namespace.table`, graph name, or endpoint |
| `detail` | object | Non-sensitive structured context |
| `schema_version` | string | Currently `1.0` |
| `host` / `service` / `env` | string | Deployment context |

Local time in an audit trail is a finding at assessment. Always UTC,
always with the `Z`.

Example:

```json
{"action":"query.execute","detail":{"duration_ms":88,"engine":"duckdb","materialisation":"arrow-zero-copy","rows_returned":1420,"source_rows_scanned":8400000},"env":"production","event_id":"0bf017df-…","host":"api-7","outcome":"allow","request_id":"…","resource":"gold.ami_readings","role":"Data Engineer","schema_version":"1.0","service":"meldra-api","subject":"u-9931","tenant_id":"t_a1b2c3","timestamp":"2026-09-05T02:11:04.318Z"}
```

---

## 3. Rules

1. **Append-only.** No update or delete path exists in the module.
2. **Never log data values.** Column *names* yes; cell contents never. An
   audit log containing the PII it audits is a second breach surface.
3. **Never log secrets.** `redact()` runs on every payload and replaces
   password, token, key, authorization, MFA and session fields.
4. **Deny and error records flush synchronously.** Losing an allow record
   is tolerable; losing a deny record is not.
5. **Truncate unbounded content explicitly.** Tracebacks cap at 8,000
   characters with a visible marker — never silently.

---

## 4. Usage

```python
from observability.audit_log import audit

audit.allow("query.execute", tenant_id=t, role=r, subject=u,
            resource=f"{ns}.{tbl}", request_id=job_id,
            detail={"mode": "sql", "rows_returned": 1420})

audit.deny("rbac.check", reason="no grant for namespace",
           tenant_id=t, role=r, resource=f"{ns}.{tbl}")

try:
    ...
except Exception as exc:
    audit.error("query.execute", exc, tenant_id=t, role=r)
    raise
```

### Error handling convention

- **Audit, then re-raise.** Never swallow. The old
  `except Exception: pass` pattern is what allowed `expire_snapshots()` to
  report success for work it did not do.
- **Refuse rather than guess.** If a precondition cannot be established
  (`optimize_table` cannot plan the scan), raise with the reason. Do not
  proceed hopefully.
- **Never report unearned success.** A return string claiming an action
  occurred must be unreachable unless it did.

---

## 5. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MELDRA_AUDIT_LOG_PATH` | unset | Rotating file sink; stdout always mirrors |
| `MELDRA_AUDIT_MAX_BYTES` | 52428800 | Rotation size |
| `MELDRA_AUDIT_BACKUPS` | 20 | Retained rotations |
| `MELDRA_ENV` | `development` | Also drives tenant-guard enforcement |
| `MELDRA_SERVICE_NAME` | `meldra-api` | Service tag |
| `MELDRA_REQUIRE_TENANT_SCOPE` | on unless env is dev/local/test/ci | Fail-closed tenant guard |

---

## 6. Retention and shipping

| Requirement | Target | Status |
|---|---|---|
| Central log store (SIEM) | Splunk / Elastic / CloudWatch | Not wired — GAP-06 |
| Retention | ≥13 months | Deployment-dependent |
| Tamper-evidence | Object-lock / WORM / hash chain | **Not implemented — GAP-05** |

The last row is the honest limitation: records are append-only *by
convention within this module*, not by storage guarantee. Until GAP-05 is
closed, the audit trail should not be described to an assessor as
tamper-evident.

---

## 7. Alerting

| Condition | Severity |
|---|---|
| `query.tenant_scope` deny in production | **Critical** — an unscoped job reached an executor |
| `rbac.check` deny rate spike for one subject | High — possible enumeration |
| `outcome=error` rate above baseline | Medium |
| `snapshot.expire` on a retention-governed table | **Critical** |
| Audit write failure | **Critical** |

---

## 8. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T14:00:00Z | Baseline issue |
