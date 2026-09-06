# Gap Analysis and Roadmap

**Document ID:** ARC-006 · **Version:** 1.0 · **Issued:** 2026-09-05T13:50:00Z
**TOGAF ADM:** Phase E (Opportunities and Solutions), Phase F (Migration Planning)
**Status:** Baseline

---

## 1. How to read this

This is the register of the distance between what the platform is and what
a regulated utility deployment requires. It is deliberately unflattering.
A gap register that reads well is not being used.

Severity: **Blocker** = prevents regulated deployment · **High** = will be
raised in assurance · **Medium** = operational debt · **Low** = polish.

---

## 2. Gap register

| ID | Gap | Severity | Evidence | Resolution | Effort |
|---|---|---|---|---|---|
| **GAP-01** | **Inference egress has no residency or minimisation control** | **Blocker** | Agent calls external endpoint with query context | Redaction gateway + in-region or in-VPC inference | 3–6 weeks |
| GAP-02 | Graph path not covered by tenant scope guard | High | `graph_executor.py` addresses AGE by graph name | Extend `assert_tenant_scoped` to graph mode | 3 days |
| GAP-03 | Role-less JWT falls back to Business Analyst | High | `user.get("role", "Business Analyst")` | Reject with 403 | 1 day |
| GAP-04 | Arrow Flight server unauthenticated | High | `arrow_flight_server.py` has no auth layer | mTLS + JWT, or disable in production builds | 1 week |
| GAP-05 | Audit store not tamper-evident | High | Append-only by convention only | Object-lock / WORM sink, or hash-chained records | 2 weeks |
| GAP-06 | No SLO instrumentation | High | SLOs are proposals; nothing measures them | OpenTelemetry + dashboards | 2 weeks |
| **GAP-07** | **ETP verification not carried into the lakehouse** | **High** | No `etp_block_hash` columns; trust claim breaks at ingest | Add ETP columns + verification-on-ingest | 2–3 weeks |
| GAP-08 | Query results do not return their snapshot ID | Medium | Answers are not self-describing or re-runnable | Return `snapshot_id` in `QueryResult` | 2 days |
| GAP-09 | SQL `WHERE` predicates are not pushed to Iceberg | Medium | `job.filters` must be populated manually | sqlglot-derived pushdown ([TD-004](../technical/TD-004-scan-pushdown.md)) | 1–2 weeks |
| GAP-10 | Distributed compaction not wired | Medium | In-process rewrite capped at 5M rows | Spark `rewrite_data_files` job | 1 week |
| GAP-11 | Column-level lineage absent | Medium | Table-level only | Extend `lineage_graph.py` | 2 weeks |
| GAP-12 | Data quality rules not enforced at ingest | Medium | `validator.py` exists but is not on the write path | Wire into ingest, quarantine failures | 1 week |
| GAP-13 | Streaming ingest lacks schema registry and DLQ | Medium | `kafka_consumer.py` | Add registry + dead-letter topic | 1 week |
| GAP-14 | No SCADA/historian adapters | Medium | Blocks gas/oil segments | OPC-UA, PI connectors | 4+ weeks |
| GAP-15 | No DR/backup documentation | Medium | Not documented | Runbook + tested restore | 1 week |
| GAP-16 | No periodic entitlement review report | Low | CAF B2 expects it | Scheduled report | 3 days |
| GAP-17 | `test_query_engine.py` requires live Postgres | Low | 37 tests fail without a DB | Testcontainers in CI | 3 days |
| GAP-18 | BOM in `kafka_consumer.py` | Low | U+FEFF; breaks strict parsers | Re-save UTF-8 without BOM | 10 min |

---

## 3. Resolved in this cycle (2026-09-05)

| ID | Item | Where |
|---|---|---|
| SEC-2026-001 | Agent DQE tools bypassed tenant scoping and role binding | [security/](../security/SEC-2026-001-agent-tenant-bypass.md) |
| SEC-2026-002 | `/v1/query/explain` built an unscoped data-touching job | [security/](../security/SEC-2026-002-explain-endpoint-scope.md) |
| PERF-2026-003 | Full pandas copy + double registration on every query | [TD-003](../technical/TD-003-zero-copy-execution.md) |
| DOC-2026-004 | Docstring claimed unconditional predicate pushdown | ARC-003 §4 |
| OPS-2026-005 | `expire_snapshots()` reported success from a `pass` body | ARC-003 §5 |
| OPS-2026-006 | `optimize_table()` had no memory ceiling | ARC-003 §5 |
| HYG-2026-007 | Deprecated `datetime.utcnow()` across 7 modules | — |
| HYG-2026-008 | Junk files (`cmd.exe`, `I`) committed at repo root | — |

---

## 4. Sequencing

**Phase 1 — Make it deployable (0–6 weeks).** GAP-01, GAP-02, GAP-03,
GAP-04, GAP-05.

Everything here is a control an assurance reviewer will ask about directly.
GAP-01 is the one that decides whether a regulated pilot is possible at
all; the others are the ones that decide whether it survives review.

**Phase 2 — Make it provable (6–12 weeks).** GAP-06, GAP-07, GAP-08,
GAP-09, GAP-10.

This is where the ETP seam gets built and where the "answer plus snapshot
ID plus audit record" story becomes demonstrable end to end. It is also
where the performance claims become true rather than directional.

**Phase 3 — Make it broad (12–24 weeks).** GAP-11 through GAP-18.

Segment expansion into gas, oil and water depends on GAP-14; the remainder
is governance and operational maturity.

---

## 5. The one-paragraph version

The lakehouse, catalog, tenancy model and policy enforcement point are
genuinely well built — the isolation logic was correct before this cycle
and simply was not wired into one path. What is missing is not
architecture, it is **assurance**: egress control, tamper-evident audit,
measured SLOs, and the ETP-to-Iceberg trust seam. Those four items are what
stand between a strong demo and a signed utility contract, and none of them
is a rewrite.

---

## 6. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T13:50:00Z | Baseline issue |
