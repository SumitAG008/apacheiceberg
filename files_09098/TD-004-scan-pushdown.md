# TD-004 — Scan pushdown: current state and roadmap

**Document ID:** TD-004 · **Version:** 1.0 · **Issued:** 2026-09-05T13:58:00Z
**Component:** `backend/query_engine/sql_executor.py::_load_iceberg`
**Related:** GAP-09, ARC-003 §4

---

## 1. Current state

| Pushdown | Implemented | Driven by |
|---|---|---|
| Row filter (equality, ANDed) | Yes | `job.filters` dict |
| Column projection | Yes | `job.projection` list |
| **SQL `WHERE` → Iceberg expression** | **No** | — |
| Range/IN/OR predicates | No | — |
| Aggregate pushdown | No | — |

A query such as:

```sql
SELECT mpan, SUM(kwh) FROM iceberg_table
WHERE reading_ts >= '2026-09-01' AND region = 'NW'
GROUP BY mpan
```

reads **the entire table** into Arrow, then lets DuckDB apply the
predicates. Iceberg prunes nothing, because nothing told it to.

On a 52-billion-row AMI table that is not a slow query; it is an incident.

---

## 2. Why the previous documentation was wrong

The module docstring claimed *"executes arbitrary SQL with predicate
pushdown"*. The pushdown code exists but is only reached when `job.filters`
is populated, and no caller populated it — `distributed_sql_query` did not
pass it at all.

The docstring has been corrected to state the limitation explicitly. This
matters beyond tidiness: an operator sizing a cluster from that docstring
would size for pruned scans and get full ones.

---

## 3. Roadmap

### Step 1 — Parse and translate (1–2 weeks)

Add `sqlglot`. Parse the submitted SQL, walk the `WHERE` tree, and
translate the safely-translatable subset into PyIceberg expressions:

| SQL | PyIceberg |
|---|---|
| `col = literal` | `EqualTo` |
| `col > / >= / < / <=` | `GreaterThan`, `GreaterThanOrEqual`, `LessThan`, `LessThanOrEqual` |
| `col IN (…)` | `In` |
| `col IS NULL` | `IsNull` |
| `A AND B` | `And` |
| `A OR B` | `Or` |

**Translation must be conservative.** Anything not confidently
translatable — function calls, casts, correlated subqueries, non-literal
comparisons — is left for the engine. A pushdown that changes results is
far worse than no pushdown; the failure mode must be "read more data",
never "return different rows".

### Step 2 — Derive projection from the SELECT list (3 days)

Extract referenced columns from the projection, `WHERE`, `GROUP BY`,
`ORDER BY` and `HAVING` clauses; pass as `selected_fields`. Fall back to
all columns on `SELECT *` or on any parse failure.

### Step 3 — Make it verifiable (1 week)

Surface in the EXPLAIN plan:

```
[DQE/SQL] Engine: duckdb 1.1.3 | Table: gold.ami_readings
  Files pruned: 1,204 / 1,340
  Rows scanned: 8,400,000 / 52,560,000,000
  Pushed predicates: reading_ts >= '2026-09-01', region = 'NW'
  Projection: mpan, kwh, reading_ts
  Materialisation: arrow-zero-copy
```

This is what an analyst needs to see to trust that the platform is pruning,
and what an architect will ask for in evaluation. It is also the honest
alternative to asserting pushdown in a docstring.

### Step 4 — Interaction with RBAC row filters

Role-based row filters can themselves be pushed to the scan when they are
simple column predicates, which would prune files *and* reduce the masking
work. This must be designed carefully: pushing a filter changes what the
engine sees, and the security property must remain "the value is absent",
not "the value is filtered later". Design review required before
implementation.

---

## 4. Interim guidance

Until Step 1 ships, callers that know their access pattern should populate
`job.filters` and `job.projection` directly. `/v1/query` accepts both.
Documented in [FUNC-001](../functional/FUNC-001-functional-specification.md).

---

## 5. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T13:58:00Z | Baseline issue |
