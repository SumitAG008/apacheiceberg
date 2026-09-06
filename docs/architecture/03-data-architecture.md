# Data Architecture — Lakehouse, Catalog and Retention

**Document ID:** ARC-003 · **Version:** 1.0 · **Issued:** 2026-09-05T13:40:00Z
**TOGAF ADM:** Phase C (Data Architecture) · **Status:** Baseline

---

## 1. Storage foundation

| Layer | Technology | Role |
|---|---|---|
| Object store | S3 (or Azure ADLS / GCS) | Immutable Parquet data files |
| Table format | **Apache Iceberg** | Manifests, snapshots, schema evolution, ACID |
| Catalog | AWS Glue or Iceberg REST | Namespace → table resolution |
| Query | DuckDB (default), Spark / Doris (pluggable) | Vectorised execution |
| Graph | Apache AGE on PostgreSQL | Network topology, lineage, asset relationships |
| Control plane | PostgreSQL | Identity, roles, RBAC policies, row filters |

**Why Iceberg and not Delta or Hudi.** Recorded in
[ADR-0001](../adr/ADR-0001-iceberg-table-format.md). Summary: hidden
partitioning removes the partition-column trap that catches domain analysts;
snapshot isolation gives the reproducible as-of query that settlement
disputes require; and the format is genuinely multi-engine, which satisfies
principle P3 (asset lifecycles outlive vendors).

---

## 2. Medallion model

| Layer | Namespace convention | Content | Write pattern | Typical retention |
|---|---|---|---|---|
| **Bronze** | `<tenant>__bronze` | Raw as-received, nothing dropped | Append-only | Full regulatory window |
| **Silver** | `<tenant>__silver` | Conformed, typed, deduplicated, validated | Append + merge | Full regulatory window |
| **Gold** | `<tenant>__gold` | Aggregates, settlement-ready marts | Overwrite by partition | Per business need |

Layer is recorded in Iceberg table properties (`layer`) and surfaced by
`MeldraCatalog.get_table_details()`.

**Bronze is never edited.** If a reading is wrong, Silver corrects it and
records why. Editing Bronze destroys the evidence that the correction was
needed — which is the record a regulator actually asks for.

---

## 3. Partitioning for grid-scale data

The dominant access patterns are *recent time range* and *specific
region/feeder*. Partition accordingly:

| Table class | Recommended partition spec | Reasoning |
|---|---|---|
| AMI half-hourly readings | `days(reading_ts)`, `bucket(16, mpan)` | Time-bounded queries prune to days; bucketing spreads write skew across a large meter estate |
| SCADA / PMU telemetry | `hours(event_ts)`, `identity(substation_id)` | Sub-hour incident investigation; substation is the natural operational unit |
| Asset master | `identity(asset_class)` | Small, low-cardinality, joined not scanned |
| Settlement aggregates | `days(settlement_date)` | Reprocessed by settlement day |

Iceberg's **hidden partitioning** means analysts write
`WHERE reading_ts > '2026-09-01'` and pruning happens automatically — they
do not need to know a partition column exists. This is the single largest
usability advantage over Hive-style layouts for a non-specialist user base,
and it is worth stating explicitly in demos.

### Volume model — one 3-million-meter estate

| Metric | Value |
|---|---|
| Meters | 3,000,000 |
| Readings/meter/day (half-hourly) | 48 |
| Readings/day | 144,000,000 |
| **Readings/year** | **52,560,000,000** |
| Compressed Parquet @ ~12 bytes/reading | ~630 GB/year |
| With Silver + Gold derivatives | ~1.5–2 TB/year |

At object-storage pricing this is a rounding error; the cost is entirely in
compute and in the discipline of pruning. Which is why §4 matters.

---

## 4. Scan pushdown

Two pushdowns are implemented in `SQLExecutor._load_iceberg()`:

| Pushdown | Mechanism | Populated by |
|---|---|---|
| Row filter | PyIceberg `EqualTo`/`And` → `scan(row_filter=…)` | `job.filters` |
| Column projection | `scan(selected_fields=…)` | `job.projection` |

Both prune at **scan planning** time, so whole manifests and data files are
skipped before any byte is read.

> **Known limitation, stated plainly.** Predicates written inline in the SQL
> `WHERE` clause are **not** auto-translated into Iceberg expressions. They
> are evaluated by DuckDB *after* the scan. A caller that needs file-level
> pruning must populate `job.filters` explicitly. SQL-derived pushdown
> requires a SQL parser (sqlglot) and is tracked in
> [TD-004](../technical/TD-004-scan-pushdown.md).
>
> This limitation was previously contradicted by the module docstring, which
> claimed predicate pushdown unconditionally. The docstring has been
> corrected. On a 52-billion-row table the difference between planned and
> unplanned pruning is the difference between a query and an outage.

---

## 5. Time travel, lineage and retention

**Time travel.** Every commit creates a snapshot.
`MeldraCatalog.run_time_travel_scan(namespace, table, snapshot_id)` reads
the table as it stood. This is what makes VS-3 (regulatory response)
possible: the regulator's question is always "what did you know on date X",
and the answer must be reproducible.

**Recommendation not yet implemented:** return the snapshot ID alongside
every query result, so an answer is self-describing and re-runnable. Small
change, disproportionate assurance value. Tracked as GAP-08.

**Lineage.** `lineage_graph.py` tracks table-to-table relationships.
Column-level lineage is not implemented; for settlement defensibility
("which source column produced this figure") it will be needed.

**Retention.** `expire_snapshots()` now:

1. refuses if fewer snapshots exist than `retain_last` (default 10);
2. **hard-blocks** on any table carrying the `meldra.retention.min_days`
   property, raising `PermissionError` rather than silently expiring;
3. commits a real expiry and reports the actual count.

The previous implementation returned *"Expired older snapshots … to free S3
storage space"* from a function body containing `pass`. For a platform whose
value proposition is auditability, a maintenance operation that reports
unearned success is a compliance defect, not a cosmetic bug. It is now
covered by a regression test.

**Set `meldra.retention.min_days` on every regulated table at creation
time.** It is the only thing standing between a well-meaning storage
cleanup and the destruction of an audit window.

---

## 6. Data classification and masking

| Class | Examples | Default treatment |
|---|---|---|
| **Restricted** | MPAN/MPRN, customer name/address, meter serial | Masked for all roles except explicit grant |
| **Sensitive** | Half-hourly consumption (occupancy-revealing) | Row-filtered by region/role; aggregate access preferred |
| **Internal** | Asset IDs, feeder topology, network model | Role-gated |
| **Open** | Aggregated regional statistics | Broad read |

Enforced by `rbac_utils.enforce_rbac()` **at the data layer, before engine
registration**. Column aliasing, subqueries, CTEs and `SELECT *` cannot
recover a masked value, because the value is absent from the relation the
engine ever sees. This is a stronger guarantee than SQL rewriting and is
worth making explicitly in a CISO conversation.

---

## 7. ETP integration columns (required, not built)

To carry ETP's tamper-evidence into the lakehouse, ingest must persist:

| Column | Type | Meaning |
|---|---|---|
| `etp_block_hash` | string | Block hash from the ETP-verified reading |
| `etp_verified_at` | timestamp | When verification occurred |
| `etp_sentinel_score` | double | AI Sentinel anomaly score at ingest |
| `etp_chain_ref` | string | Anchor reference for external verification |

Without these, the end-to-end trust claim breaks at the ingest boundary:
ETP can prove a reading was untampered on the wire, and Iceberg can prove
a row was untampered at rest, but nothing joins the two. Tracked as GAP-07.

---

## 8. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T13:40:00Z | Baseline issue; pushdown limitation stated; retention guard documented |
