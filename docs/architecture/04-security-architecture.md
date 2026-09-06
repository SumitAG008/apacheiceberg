# Security Architecture

**Document ID:** ARC-004 · **Version:** 1.0 · **Issued:** 2026-09-05T13:45:00Z
**TOGAF ADM:** Cross-cutting (Phases B–D) · **Status:** Baseline
**Classification:** Internal

---

## 1. Threat model summary

| # | Threat | Vector | Control | Status |
|---|---|---|---|---|
| T1 | Cross-tenant data read | Unscoped namespace lookup | Context-bound tenant + fail-closed guard | ● Remediated (SEC-2026-001) |
| T2 | Privilege confusion | Role defaulted rather than bound | Role bound from JWT; AST test in CI | ● Remediated |
| T3 | Masked-column recovery | SQL aliasing, subqueries, CTEs | Data-layer PEP before engine registration | ● |
| T4 | Prompt injection steering the agent | Malicious content in queried data or user turn | Tenant/role from ContextVars, never tool arguments | ● Structural |
| T5 | Sandbox escape via Python transform | `exec` of user script | AST pre-scan + restricted builtins + timeout | ● |
| T6 | Data exfiltration via inference egress | Telemetry sent to external endpoint | **None** | ○ **GAP-01** |
| T7 | Audit tampering | Log mutation | Append-only by convention only | ◐ Not cryptographic |
| T8 | Unauthenticated Arrow Flight access | gRPC endpoint | **None** | ○ GAP-04 |
| T9 | Credential compromise | Password/token theft | OIDC + MFA + bcrypt + rate limiting | ● |
| T10 | Retention destruction | Careless snapshot expiry | `meldra.retention.min_days` hard block | ● |

---

## 2. Defence in depth

```
 1. Network            TLS; private networking (deployment-dependent)
 2. Identity           OIDC · MFA (mfa_service.py) · bcrypt · JWT
 3. Endpoint RBAC      roles.py capability sets, enforced server-side
 4. Tenant isolation   tenancy.py prefixing + assert_tenant_scoped guard
 5. Data-layer RBAC    enforce_rbac: table access → row filter → column mask
 6. Execution sandbox  AST scan, restricted builtins, timeouts,
                       DuckDB enable_external_access=false
 7. Audit              observability/audit_log.py, UTC, append-only
```

Layers 4 and 5 are the ones that carry the confidentiality guarantee. Layer
3 protects endpoints; it does not protect data, and should never be
presented as if it does.

---

## 3. Tenant isolation model

One registered account = one tenant. `tenant_id` is the JWT `sub` claim and
is **never** read from a request body.

- `scope_namespace()` prefixes every client-supplied namespace:
  `default` → `t_<tenant>__default`.
- `unscope_namespace()` returns `None` for a namespace not belonging to the
  caller — the isolation boundary. A foreign namespace is never revealed,
  not even by name.
- `assert_tenant_scoped()` refuses any data-touching job carrying no
  tenant. Defaults to **enforced** whenever `MELDRA_ENV` is not
  development/local/test/ci, so production is secure without configuration.

Every unscoped execution is audited whether or not it is refused, so the
condition is detectable in an environment where enforcement has been
disabled.

**Known residual:** graph queries reach Apache AGE by graph name rather
than by Iceberg namespace and are not covered by this guard. Tracked as
SEC-2026-001 action A-2.

---

## 4. Authorisation model

Eight personas (`roles.py`), evaluated at two levels.

| Role | Endpoint capability | Data-layer default |
|---|---|---|
| Admin | Full | Unmasked |
| Data Engineer | Ingest, query, Python transforms | Bronze/Silver RW, Gold R |
| Data Architect | Schema and namespace lifecycle | Structural, not row data |
| Business Analyst | Query Gold | PII masked |
| **Consultant** | Query | **Deny-by-default on every namespace** until an Admin grants one |
| CIO / COO / Viewer | Dashboards only — no ad-hoc query | Aggregates only |

The Consultant persona is the most security-relevant design decision in the
model: external and time-boxed users start with access to nothing, and
access is granted explicitly. This is the right default for a utility
engaging contractors, and it was precisely the persona most affected by
SEC-2026-001, since the hardcoded `"Business Analyst"` fallback bypassed
the deny-by-default posture entirely.

---

## 5. Regulatory mapping

| Obligation | Requirement | Control | Status |
|---|---|---|---|
| **UK GDPR Art. 5(1)(f)** | Integrity and confidentiality | Layers 4–5 | ● |
| **UK GDPR Art. 5(1)(c)** | Data minimisation | Column masking ●; egress minimisation ○ | ◐ |
| **UK GDPR Art. 30** | Records of processing | Audit log | ◐ Feeds it; not a RoPA |
| **UK GDPR Art. 32** | Security of processing | Full stack | ● |
| **UK GDPR Art. 33** | 72-hour breach notification | Audit trail supports assessment | ◐ |
| **NIS Regulations 2018 Reg. 10** | Security duty for OES | Layers 1–7 | ◐ Egress open |
| **NCSC CAF B2** | Identity and access control | RBAC + MFA + tenancy | ● |
| **NCSC CAF C1** | Security monitoring | Structured audit; no SIEM integration yet | ◐ |
| **NCSC CAF C2** | Proactive discovery | Not implemented | ○ |
| **IEC 62443-3-3** | System security requirements | Partial (SR 1.x, 2.x) | ◐ |
| **Smart Energy Code / DCC** | Data access and residency | **Blocked by GAP-01** | ○ |
| **ISO 27001 A.9 / A.12** | Access control, logging | Covered | ◐ Needs formal ISMS |

Nothing here is claimed as certified. These are control mappings for a
readiness assessment, not evidence of assessment.

---

## 6. The egress boundary — GAP-01

Agent reasoning currently calls an external inference endpoint. For a
DCC-connected party or an operator inside NIS scope this is normally a
blocking finding, regardless of contractual data-handling terms, because
the control question is *where the data goes*, not *what the vendor
promises to do with it*.

Three resolutions, in order of deployment realism:

1. **In-region managed inference** — AWS Bedrock (eu-west-2) or Azure with
   UK data residency. Fastest path; satisfies residency, not "never leaves
   our estate".
2. **Redaction gateway ahead of IF-07** — strip MPAN, names, addresses and
   precise geolocation before any inference call; send schema and
   aggregates, never raw rows. Strong minimisation posture, and worth
   building regardless of option 1 or 3.
3. **Self-hosted inference in the operator's VPC** — satisfies the
   strictest reading. Highest operational cost.

**Recommendation:** build option 2 unconditionally — it is good practice
under Art. 5(1)(c) whatever the endpoint — and offer options 1 and 3 as
deployment tiers.

---

## 7. Audit trail

`observability/audit_log.py`. JSON-lines, one object per event, UTC
ISO-8601 to millisecond precision with explicit `Z`. Every record carries
`event_id`, `action`, `outcome`, `tenant_id`, `role`, `subject`,
`resource`, `request_id`, `timestamp`, `schema_version`, `host`, `service`,
`env`.

Design rules enforced in code:

- **No data values.** Column names yes, cell contents never — an audit log
  containing the PII it audits is a second breach surface.
- **Secrets redacted** on every payload via `redact()`.
- **Deny and error records flush synchronously.** Losing an allow record is
  tolerable; losing a deny record is not.
- **Append-only.** No update or delete path exists in the module.

**Residual (T7):** append-only is a property of this module, not of the
storage. A tamper-evident store — object-lock, WORM, or hash-chained
records — is required before the audit trail can be presented as
independently trustworthy. Tracked as GAP-05.

---

## 8. Secure development

- Secrets are not committed; `.gitignore` excludes `.env*` except the
  example. Verified by scan on 2026-09-05.
- Security regressions are pinned by test, not by review attention:
  `backend/tests/test_sec_2026_regressions.py`.
- Security findings are recorded as numbered, dated documents under
  `docs/security/` with impact, root cause, remediation and residual risk.

---

## 9. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T13:45:00Z | Baseline issue following SEC-2026-001/002 |
