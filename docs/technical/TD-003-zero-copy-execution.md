# TD-003 — Zero-copy execution path

**Document ID:** TD-003 · **Version:** 1.0 · **Issued:** 2026-09-05T13:55:00Z
**Component:** `backend/query_engine/sql_executor.py`, `sql_backends.py`, `rbac_utils.py`
**Related finding:** PERF-2026-003

---

## 1. What was wrong

Every SQL query executed this sequence:

```python
primary_arrow = self._load_iceberg(...)                    # Arrow table
primary_df = enforce_rbac(primary_arrow.to_pandas(), ...)  # full copy #1
backend.register_table("iceberg_table", primary_df)        # copy #2
backend.register_table(fq_name, primary_df)                # copy #3
```

Three materialisations of the same dataset per query, unconditionally —
including when the caller's role had no masking policy at all, so the
transform was a no-op that still paid for itself in full.

For a product positioned on **zero-copy**, the hot path did the opposite.
On a multi-gigabyte grid table this is the difference between a query and
an OOM kill.

---

## 2. What it does now

```python
if rbac_is_noop(job.namespace, job.table_name, job.role):
    registered = primary_arrow          # zero-copy: DuckDB scans buffers in place
    copy_mode = "arrow-zero-copy"
else:
    registered = enforce_rbac(primary_arrow.to_pandas(), ...)
    copy_mode = "pandas-rbac-materialised"

backend.register_table("iceberg_table", registered)
backend.register_view(fq_name, "iceberg_table")   # alias, not a second copy
```

Two changes:

1. **Arrow fast path.** `duckdb.register()` accepts a `pyarrow.Table` and
   scans its buffers without copying. When no RBAC transform applies, the
   pandas materialisation is skipped entirely.
2. **Single registration.** The join alias is now a SQL view over the
   already-registered relation instead of a second shipment of the payload.

`copy_mode` is surfaced in the EXPLAIN plan text and in the audit record,
so which path a query took is observable rather than assumed.

---

## 3. The safety contract

The fast path is only safe if `rbac_is_noop()` can never return `True` when
a policy exists. Three properties enforce that:

| Property | Implementation |
|---|---|
| Table access is still checked on the fast path | `rbac_is_noop()` calls `check_table_access()` before anything else; an unauthorised role raises `TableAccessDenied` identically on both paths |
| Any applicable policy forces the slow path | Column policies and row filters matching the namespace/table (including `*` wildcards) return `False` |
| **Unknown policy state fails closed** | Any exception reaching the policy store returns `False` — a database blip degrades performance, never confidentiality |

That last row is the important one, and it is the direct application of
architecture principle **P1 (fail closed)**. The tempting implementation —
"if we can't find a policy, there probably isn't one" — is how masking
controls silently stop working during an unrelated outage.

Pinned by `test_rbac_noop_probe_fails_closed` and three sibling tests.

---

## 4. Also added: projection pushdown

`_load_iceberg()` now accepts `projection` and passes it as
`scan(selected_fields=…)`, so unreferenced columns are never read from
object storage. Unknown column names are dropped rather than raising, so a
stale projection degrades to reading more data — never to an error.

For wide grid tables (AMI records with 30+ columns where a query touches
three) this is a larger practical saving than the Arrow fast path.

---

## 5. What is still not zero-copy

Stated plainly, because the marketing term invites over-claiming:

- **When any masking or row filter applies**, the pandas materialisation
  still happens. An Arrow-native RBAC implementation using `pyarrow.compute`
  would remove it. Not attempted here — it would change tested behaviour of
  a confidentiality control, which is not a change to make in the same pass
  as a security fix.
- **`execute()` returns `fetchdf()`**, a pandas result. Fine for result-set
  sizes; would matter for large extracts.
- **Spark and Doris backends** convert Arrow to pandas on registration.
  Documented in the backend, not hidden.

**Recommended external wording:** "zero-copy scan path" or
"zero-materialisation query execution" — accurate, and defensible when a
data architect reads the code. Avoid unqualified "zero-copy architecture";
it is a claim about the whole system that the whole system does not yet
support.

---

## 6. Verification

| Test | Asserts |
|---|---|
| `test_duckdb_registers_arrow_without_copy` | DuckDB queries a `pyarrow.Table` in place; view aliasing works |
| `test_sql_executor_registers_payload_once` | Exactly one `register_table` in `execute()` |
| `test_rbac_noop_probe_fails_closed` | Policy-store error → slow path |
| `test_rbac_noop_probe_detects_column_policy` | Mask policy → slow path |
| `test_rbac_noop_probe_detects_row_filter` | Row filter → slow path |
| `test_rbac_noop_probe_true_when_no_policies` | Clean case → fast path |

Not yet measured: actual memory and latency deltas on a realistic grid
table. The change is structurally sound but the benefit is currently
reasoned, not benchmarked. Benchmarking is part of GAP-06.

---

## 7. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T13:55:00Z | Baseline issue |
