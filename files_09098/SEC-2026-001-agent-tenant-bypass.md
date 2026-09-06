# SEC-2026-001 — Agent DQE tools bypassed tenant scoping and RBAC role binding

| Field | Value |
|---|---|
| **Record ID** | SEC-2026-001 |
| **Severity** | High |
| **Status** | Remediated — awaiting verification in staging |
| **Raised** | 2026-09-05T13:12:00Z |
| **Remediated** | 2026-09-05T13:19:00Z |
| **Affected components** | `backend/tools.py`, `backend/query_engine/sql_executor.py`, `backend/query_engine/python_executor.py` |
| **CWE** | CWE-863 Incorrect Authorization; CWE-1220 Insufficient Granularity of Access Control |
| **Regulatory relevance** | UK GDPR Art. 5(1)(f), Art. 32; NIS Regulations 2018 Reg. 10; NCSC CAF Objective B2 (Identity and Access Control) |
| **Regression test** | `backend/tests/test_sec_2026_regressions.py` |

---

## 1. Summary

All four `QueryJob` constructions inside the LangChain agent's Distributed
Query Engine tools omitted the `tenant_id` and `role` fields. Both have
permissive defaults in `query_engine/models.py`:

```python
role: str = "Business Analyst"
tenant_id: str = ""
```

`tenant_id = ""` causes `SQLExecutor` and `PythonExecutor` to skip
`tenancy.scope_namespace()` entirely and query the catalog using the raw,
client-supplied namespace string. `role = "Business Analyst"` causes
`rbac_utils.enforce_rbac()` to evaluate column masking and row filters
against a role the caller may not hold.

## 2. Why this mattered more than it looks

The tenant isolation mechanism in `tenancy.py` was correctly designed and
correctly implemented. It simply was never passed a tenant on this path,
and nothing in the system objected. The `query_iceberg_data` tool *did*
pass tenant and role correctly — so the codebase contained a safe path and
an unsafe path to the same data.

The system prompt in `agent.py` then actively steered traffic to the unsafe
one:

> "Distributed Query Engine (DQE) — **Prefer these** for complex or
> large-scale queries… Use this **instead of** `query_iceberg_data`."

The chat agent is the primary product surface. In practice the default
route to customer data was the route with no tenant scoping.

## 3. Impact assessment

**Confidentiality — namespace scoping.** Namespaces created through the
tenant-aware API are prefixed (`t_<tenant>__default`), so an unscoped
lookup for `"default"` usually misses. The exposure is therefore limited
to **unprefixed namespaces**: anything created by `catalog_setup.py`,
`ingest_climate.py`, `generate_large_dataset.py`, or by any operator or
test predating the tenancy work. Those namespaces were readable by any
authenticated tenant through the chat interface. We have not established
which unprefixed namespaces exist in each deployed environment — see
Action A-4.

**Confidentiality — RBAC role binding.** This is unconditional and does not
depend on legacy namespaces. Every DQE query from the agent evaluated
column masking against `"Business Analyst"` regardless of the caller's real
role. Two consequences, in opposite directions:

- A **Consultant** (deny-by-default per `roles.py`) was evaluated as a
  Business Analyst, so the deny-by-default posture did not apply on this
  path. This is the material finding.
- An **Admin** was over-masked, receiving redacted values they were
  entitled to see. Not a breach, but it means query results returned to
  privileged users were silently wrong.

**Integrity / availability.** No impact. The path is read-only.

**Audit.** Before this remediation there was no record distinguishing a
scoped from an unscoped execution, so retrospective determination of what
was actually read is limited to whatever application logs exist. This gap
is itself the reason `observability/audit_log.py` was introduced.

## 4. Root cause

Pydantic field defaults were used to express *security* state. A default of
`""` for `tenant_id` makes "no tenant" a silently valid, permissive value,
and a default of `"Business Analyst"` makes "no role stated" resolve to a
role with real data access. Nothing at the boundary distinguished "this
caller is a library/test with no tenant" from "this caller is a user whose
tenant we forgot to pass."

The contributing factor is that the safe and unsafe paths were written at
different times, and the newer, faster path was documented as preferred
without a security review of its context propagation.

## 5. Remediation

**R-1 — Bind tenant and role from request context, not from arguments.**
`backend/tools.py` now exposes `_job_context()`, which reads the
`current_tenant_id` and `current_user_role` ContextVars set by the
`/v1/chat` handler, and every DQE tool passes both into `QueryJob`.

The ContextVar source matters: the LLM never sees these values as tool
parameters, so a prompt-injected instruction cannot cause the model to
name a tenant it does not belong to. The agent is structurally unable to
cross tenants, not merely instructed not to.

**R-2 — Fail-closed tenant guard at the executor boundary.**
`assert_tenant_scoped()` in `sql_executor.py` is invoked by both the SQL
and Python executors. Any job arriving without a tenant is audited
unconditionally; whether it is also refused is governed by
`MELDRA_REQUIRE_TENANT_SCOPE`, which **defaults to enabled** whenever
`MELDRA_ENV` is not `development`/`local`/`test`/`ci`. Production is secure
without configuration; local development and the existing test suite remain
usable.

**R-3 — Make omission a build failure.**
`test_every_queryjob_carries_tenant_and_role` walks the AST of `tools.py`
and `api/main.py` and fails if any `QueryJob(...)` lacks explicit
`tenant_id` and `role` keywords. A future contributor reintroducing this
defect gets a red CI run, not a reviewer's good luck.

**R-4 — Audit every execution.** Allow, deny and error records now carry
tenant, role, subject, resource and a UTC ISO-8601 timestamp
(`observability/audit_log.py`).

## 6. Residual risk

- `MELDRA_REQUIRE_TENANT_SCOPE=0` in a production environment re-opens the
  gap. Mitigated by the default and by the audit record; not prevented.
- The guard covers SQL and Python executors. `graph_executor.py` reaches
  Apache AGE by graph name rather than by Iceberg namespace and needs its
  own scoping review — tracked as A-2 below.
- The `role` fallback in `api/main.py` is still
  `user.get("role", "Business Analyst")`. If a JWT is ever issued without a
  role claim, that fallback grants Business Analyst access. It should
  become a hard rejection — tracked as A-3.

## 7. Actions

| ID | Action | Owner | Due |
|---|---|---|---|
| A-1 | Deploy remediation to staging; verify with two tenants and a Consultant account | Eng | Next release |
| A-2 | Scope review of `graph_executor.py` / Apache AGE graph naming | Eng | +2 weeks |
| A-3 | Replace the `"Business Analyst"` role fallback with a 403 on a role-less JWT | Eng | +2 weeks |
| A-4 | Inventory unprefixed namespaces in every deployed environment; migrate or delete | Ops | +1 week |
| A-5 | Ship audit records to the central log store with ≥13-month retention | Ops | +1 month |
| A-6 | Determine whether any real customer data sat in an unprefixed namespace; if yes, run the UK GDPR Art. 33 72-hour assessment | DPO | +1 week |

> **A-6 is the one that carries a legal clock.** Remediating the code does
> not discharge a notification obligation if customer personal data was
> reachable. That assessment needs a decision from the data controller, not
> from engineering.

---

*Related: [SEC-2026-002](SEC-2026-002-explain-endpoint-scope.md) ·
[Security Architecture](../architecture/04-security-architecture.md)*
