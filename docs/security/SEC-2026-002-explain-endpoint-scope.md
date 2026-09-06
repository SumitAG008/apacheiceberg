# SEC-2026-002 — `/v1/query/explain` constructed a data-touching job without tenant or role

| Field | Value |
|---|---|
| **Record ID** | SEC-2026-002 |
| **Severity** | Medium |
| **Status** | Remediated |
| **Raised** | 2026-09-05T13:14:00Z |
| **Remediated** | 2026-09-05T13:18:00Z |
| **Affected component** | `backend/api/main.py` — `dqe_explain` |
| **CWE** | CWE-863 Incorrect Authorization |
| **Regression test** | `test_every_queryjob_carries_tenant_and_role[api/main.py]` |

## Summary

`POST /v1/query/explain` is documented as a dry run:

> "Does not consume compute resources."

That is not what it does. `SQLExecutor.explain()` calls `_load_iceberg()`
and then `register_table()` — it loads the real Iceberg table into memory
and registers it with the backend before returning an EXPLAIN plan. The
`QueryJob` it built passed neither `tenant_id` nor `role`, while the two
neighbouring endpoints (`/v1/query`, `/v1/query/multi`) passed both.

## Impact

Same class as SEC-2026-001 and the same exposure surface: an unscoped
catalog lookup, and RBAC evaluated against the default role. Lower severity
because the endpoint returns only a plan, not rows. But an EXPLAIN plan is
not information-free — it discloses table existence, row counts, and
column names, which is enough to enumerate a namespace.

The docstring claim also had an operational cost: an operator reading it
would reasonably size and rate-limit this endpoint as cheap, when it is as
expensive as a full scan.

## Remediation

- `role` and `tenant_id` are now populated from the authenticated JWT via
  `get_current_tenant_id(user)`, matching the sibling endpoints.
- Covered by the AST regression test, which asserts across *all* `QueryJob`
  constructions in `api/main.py`, so a future endpoint cannot repeat it.

## Follow-up

`SQLExecutor.explain()` should use scan planning metadata rather than
materialising the table, so the endpoint becomes as cheap as its docstring
claims. Tracked in [TD-004](../technical/TD-004-scan-pushdown.md); until
then the docstring has been left accurate rather than aspirational.

---

*Related: [SEC-2026-001](SEC-2026-001-agent-tenant-bypass.md)*
