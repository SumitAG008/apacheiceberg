# FUNC-001 — Functional Specification

**Document ID:** FUNC-001 · **Version:** 1.0 · **Issued:** 2026-09-05T14:05:00Z
**Status:** Baseline · **Audience:** Product, engineering, QA, pre-sales

Legend: ● implemented · ◐ partial · ○ planned

---

## 1. Actors

| Actor | Description |
|---|---|
| Grid analyst | Domain expert, limited SQL. Primary agent user. |
| Data engineer | Builds pipelines, ingests, transforms. |
| Data architect | Owns schema and namespace standards. |
| Consultant | External, time-boxed, deny-by-default. |
| Executive (CIO/COO/Viewer) | Dashboards only. |
| Administrator | Roles, policies, tenants. |
| Upstream system | Batch or streaming data source. |

---

## 2. Functional requirements

### FR-1 Data ingestion

| ID | Requirement | Status | Implementation |
|---|---|---|---|
| FR-1.1 | Ingest CSV into an Iceberg table with schema casting | ● | `ingest_csv_to_iceberg` |
| FR-1.2 | Create tables with explicit typed schemas | ● | `create_iceberg_table` |
| FR-1.3 | Consume streaming telemetry from Kafka | ◐ | `kafka_consumer.py` — no schema registry or DLQ (GAP-13) |
| FR-1.4 | Validate on ingest and quarantine failures | ○ | `validator.py` exists, not wired (GAP-12) |
| FR-1.5 | Verify and persist ETP block hashes at ingest | ○ | GAP-07 |
| FR-1.6 | Ingest from SCADA/historian (OPC-UA, PI) | ○ | GAP-14 |

### FR-2 Catalog and governance

| ID | Requirement | Status |
|---|---|---|
| FR-2.1 | Create, list, delete namespaces (tenant-scoped) | ● |
| FR-2.2 | List tables, inspect schema, properties, snapshot history | ● |
| FR-2.3 | Evolve schema (add / drop / rename column) | ● |
| FR-2.4 | Tag tables with medallion layer | ● |
| FR-2.5 | Compact small files, with a memory ceiling | ◐ Capped at 5M rows (GAP-10) |
| FR-2.6 | Expire snapshots, blocked on retention-governed tables | ● |
| FR-2.7 | Table-level lineage | ◐ Column-level absent (GAP-11) |

### FR-3 Query

| ID | Requirement | Status | Notes |
|---|---|---|---|
| FR-3.1 | Execute SQL against Iceberg via DuckDB | ● | |
| FR-3.2 | Cross-namespace joins | ● | Registered as `namespace__table` |
| FR-3.3 | Row-filter pushdown at scan planning | ● | Via `job.filters` |
| FR-3.4 | Column-projection pushdown | ● | Via `job.projection` |
| FR-3.5 | Derive pushdown from the SQL `WHERE` clause | ○ | **GAP-09** — see [TD-004](../technical/TD-004-scan-pushdown.md) |
| FR-3.6 | Return an EXPLAIN plan | ● | Includes materialisation mode |
| FR-3.7 | Graph algorithms (pagerank, centrality, components, cycles, shortest path, community) | ● | |
| FR-3.8 | Cypher against Apache AGE | ● | |
| FR-3.9 | Sandboxed Python transforms | ● | AST-guarded |
| FR-3.10 | Multi-engine fan-out (max 10) | ● | |
| FR-3.11 | Time-travel query by snapshot ID | ● | |
| FR-3.12 | Return the snapshot ID with every result | ○ | **GAP-08** |
| FR-3.13 | Truncation signalling and pagination | ● | |

### FR-4 Natural-language interface

| ID | Requirement | Status |
|---|---|---|
| FR-4.1 | Answer domain questions by emitting and running queries | ● |
| FR-4.2 | Maintain conversational context | ● |
| FR-4.3 | Bind tenant and role from server context, never from model arguments | ● |
| FR-4.4 | Never compute values directly (ADR-0003) | ● Prompt-enforced |
| FR-4.5 | Display the emitted query alongside the result | ◐ Backend emits; UI surfacing to confirm |
| FR-4.6 | Emit per-tool traffic events for observability | ● `traffic_bus` |

### FR-5 Security and access

| ID | Requirement | Status |
|---|---|---|
| FR-5.1 | OIDC authentication | ● |
| FR-5.2 | Multi-factor authentication | ● |
| FR-5.3 | JWT session management | ● |
| FR-5.4 | Eight-persona RBAC with capability sets | ● |
| FR-5.5 | Deny-by-default Consultant persona | ● |
| FR-5.6 | Data-layer column masking and denial | ● |
| FR-5.7 | Data-layer row filtering | ● |
| FR-5.8 | Tenant isolation via namespace prefixing | ● |
| FR-5.9 | Refuse unscoped data-touching jobs | ● |
| FR-5.10 | Rate limiting on auth endpoints | ● |
| FR-5.11 | Control inference egress / data residency | ○ **GAP-01 — blocker** |

### FR-6 Audit and observability

| ID | Requirement | Status |
|---|---|---|
| FR-6.1 | Structured JSON audit records, UTC ISO-8601 | ● |
| FR-6.2 | Record allow, deny and error outcomes | ● |
| FR-6.3 | Redact secrets from every record | ● |
| FR-6.4 | Correlate records by request ID | ● |
| FR-6.5 | Live traffic events | ● |
| FR-6.6 | Tamper-evident audit storage | ○ GAP-05 |
| FR-6.7 | SLO instrumentation | ○ GAP-06 |
| FR-6.8 | Periodic entitlement review report | ○ GAP-16 |

---

## 3. Key user journeys

### UJ-1 Grid analyst investigates a feeder anomaly

1. Analyst asks in natural language.
2. Agent binds tenant and role from context; selects `distributed_sql_query`.
3. Executor asserts tenant scope, loads the Iceberg scan, applies RBAC (or
   takes the zero-copy path if no policy applies), runs the SQL.
4. Result returns with an EXPLAIN plan and materialisation mode.
5. `query.execute` allow record is written with tenant, role, subject,
   resource, rows scanned and duration.
6. Analyst follows up with a topology traversal over Apache AGE.

### UJ-2 Regulatory as-of response

1. Compliance identifies the date in question.
2. `run_time_travel_scan` reads the table at that snapshot.
3. The same query is run against the historical snapshot.
4. Audit records for the original period evidence who read what and when.

### UJ-3 External consultant onboarding

1. Admin creates the account with the Consultant role — access to nothing.
2. Admin grants an explicit allow on one namespace.
3. Consultant queries only that namespace; every other attempt produces a
   `rbac.check` deny record.

---

## 4. Non-functional requirements

| ID | Requirement | Target | Measured? |
|---|---|---|---|
| NFR-1 | Query latency, Gold layer | p95 < 5s | No (GAP-06) |
| NFR-2 | API availability | 99.5% | No |
| NFR-3 | Concurrent query capacity | 50 | Locust harness exists, no published result |
| NFR-4 | Audit capture completeness | 100% | Partial |
| NFR-5 | Peak memory per query | < 2× scanned bytes | Improved by TD-003, not benchmarked |
| NFR-6 | Ingest latency, batch | < 15 min | No |
| NFR-7 | Retention | ≥ regulatory window | Guard implemented |

**All NFR targets are proposals, not measurements.** A utility RFP asks for
evidence. Producing it is GAP-06 and should precede any formal bid.

---

## 5. Out of scope for this baseline

Forecasting and ML modelling; billing execution; SCADA control actions
(read-only platform); the ETP protocol internals; real-time sub-second
streaming analytics.

---

## 6. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T14:05:00Z | Baseline issue |
