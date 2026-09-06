# Business Architecture — Utility & Energy Sector

**Document ID:** ARC-002
**Version:** 1.0
**Issued:** 2026-09-05T13:35:00Z
**TOGAF ADM:** Phase A (Vision) and Phase B (Business Architecture)
**Status:** Baseline

---

## 1. Business drivers

| # | Driver | Evidence / pressure | Platform response |
|---|---|---|---|
| D1 | Metering data volume growth | Half-hourly settlement across national meter estates; billions of readings per year per operator | Iceberg manifest pruning, partition + column projection pushdown |
| D2 | Regulatory retention | Multi-year audit windows under sector rules and UK GDPR accountability | Iceberg snapshot history; retention-guarded expiry |
| D3 | Cyber obligations on essential services | NIS Regulations 2018; NCSC Cyber Assessment Framework | Data-layer RBAC, tenant isolation, structured audit trail |
| D4 | Consumer privacy | Consumption data reveals occupancy and behaviour — special-category-adjacent | Column masking, row filtering, data minimisation at egress |
| D5 | Net-zero and DER complexity | EV charging, heat pumps, rooftop solar, storage, flexibility markets | Graph analytics over network topology; multi-source joins |
| D6 | Asset lifecycle vs vendor lifecycle | Grid assets run 20–40 years; vendors do not | Open table format; no proprietary storage lock-in |
| D7 | Analyst scarcity | Domain experts outnumber SQL-fluent staff | Natural-language interface bounded to deterministic execution |

---

## 2. Stakeholder map

| Stakeholder | Primary concern | What they need from the platform | Architecture view they read |
|---|---|---|---|
| **CIO / CDO** | Cost, lock-in, strategic fit | Open formats, credible roadmap, TCO | ARC-001, BC-001 |
| **Head of Data / Chief Data Architect** | Model quality, governance, lineage | Medallion structure, schema evolution, catalog | ARC-003 |
| **CISO** | Breach exposure, assurance evidence | Isolation proof, audit trail, egress control | ARC-004, SEC records |
| **Data Protection Officer** | Lawful basis, minimisation, subject rights | Masking policy, retention, egress boundary | ARC-004 §5 |
| **Regulatory / Compliance lead** | Auditability, settlement defensibility | Immutable history, deterministic computation | ARC-003 §5, ADR-0003 |
| **Grid / Network Operations** | Answers during an event, at speed | Sub-minute query on recent data; anomaly views | FUNC-001 |
| **Settlement / Revenue** | Correctness, reconciliation | Deterministic SQL, time travel, replay | ADR-0003 |
| **Field Engineering** | Asset history, failure patterns | Asset joins, graph traversal | FUNC-001 |
| **Procurement** | Vendor viability, exit plan | Data portability, standards conformance | ARC-001 §3 P3 |

**Note on sequencing.** The CISO and DPO are the stakeholders who can stop
a deployment outright, and they are the ones whose concerns the platform
currently serves least well (inference egress, GAP-01). Sales sequencing
that reaches them late is sales sequencing that fails late and expensively.

---

## 3. Business capability model

Legend: ● built · ◐ partial · ○ not built

| Capability | Sub-capability | Status | Implementation |
|---|---|---|---|
| **Data acquisition** | Batch file ingest | ● | `ingest_csv_to_iceberg` |
| | Streaming telemetry | ◐ | `kafka_consumer.py` — no schema registry, no DLQ |
| | SCADA / historian connect | ○ | No OPC-UA or PI adapter |
| | ETP verified-block ingest | ○ | GAP-07 |
| **Data governance** | Catalog & namespaces | ● | `MeldraCatalog` |
| | Schema evolution | ● | Iceberg `update_schema` |
| | Multi-tenant isolation | ● | `tenancy.py` + context binding |
| | Column masking / row filter | ● | `rbac_utils` PEP |
| | Lineage | ◐ | `lineage_graph.py` — table-level only, not column-level |
| | Data quality rules | ◐ | `meldra/validator.py` — not enforced at ingest |
| | Retention policy enforcement | ◐ | Property-based guard added; no automated lifecycle |
| **Analytics** | SQL analytics | ● | DuckDB over Iceberg |
| | Graph / topology analytics | ● | Apache AGE + NetworkX |
| | Python transforms | ● | AST-sandboxed executor |
| | Natural-language query | ● | LangChain agent |
| | Time travel / replay | ● | Iceberg snapshots |
| | Forecasting / ML | ○ | Not in scope of this baseline |
| **Assurance** | Structured audit log | ● | `observability/audit_log.py` |
| | Tamper-evident audit store | ○ | Log is append-only by convention, not cryptographically |
| | Access review reporting | ○ | No periodic entitlement report |
| | Data residency control | ○ | **GAP-01** |
| **Operations** | Table maintenance | ◐ | Bounded compaction; distributed rewrite not wired |
| | Observability / metrics | ◐ | `traffic_bus`; no SLO instrumentation |
| | DR / backup | ○ | Not documented |

Honest read: **governance and analytics are genuinely strong; assurance
and operations are where a utility procurement process will find gaps.**
That is a normal profile for a product at this stage, and it is fixable —
but it should not be presented as complete.

---

## 4. Value streams

### VS-1 — Settlement query (Revenue)

```
Meter reading  →  ETP verification  →  Bronze ingest  →  Silver conform
   →  Gold aggregate  →  Analyst question  →  Deterministic SQL
   →  Result + snapshot ID  →  Regulator-defensible answer
```

The critical property is the **snapshot ID returned with the result**. It
lets anyone re-run the identical query months later against the identical
data and get the identical number. Without it, "the figure we submitted in
March" is unreproducible, which is a settlement dispute waiting to happen.

### VS-2 — Grid event investigation (Operations)

```
Anomaly detected  →  Analyst asks in natural language  →  Agent emits SQL
   →  Pushdown-pruned scan of recent partitions  →  Topology graph traversal
   →  Affected feeder / customer set  →  Audited read record
```

Time-to-answer is the value here; the audit record is the cost of doing it
on regulated data. Both matter.

### VS-3 — Regulatory response (Compliance)

```
Regulator request  →  Time-travel to the historical snapshot
   →  Query as-of that date  →  Audit log evidencing who read what, when
   →  Response package
```

---

## 5. Business services and SLOs

| Service | Consumer | Proposed SLO | Instrumented? |
|---|---|---|---|
| Query API | Analysts, applications | p95 < 5s (Gold), 99.5% availability | No |
| Ingest | Upstream systems | < 15 min batch latency | No |
| Catalog | Data engineering | 99.9% availability | No |
| Audit trail | CISO, compliance | 100% capture, ≥13-month retention | Partial |

**These SLOs are proposals, not measurements.** Nothing currently
instruments them. A utility RFP will ask for evidence, not targets —
closing this is [GAP-06](06-gap-analysis.md).

---

## 6. Segment applicability

| Segment | Fit | Dominant driver | Principal blocker |
|---|---|---|---|
| Electricity distribution (DNO/DSO) | **Strong** | AMI volume, flexibility markets | GAP-01 egress |
| Electricity transmission (TSO) | Strong | SCADA + PMU volume, criticality | GAP-01, higher CAF bar |
| Smart metering / MSP | **Strongest — lead here** | Settlement, DCC obligations | GAP-01, GAP-07 (ETP seam) |
| Gas networks | Good | Asset integrity, leak analytics | Sensor adapters (○) |
| Oil & gas midstream | Good | Pipeline telemetry, predictive maintenance | Historian adapters (○) |
| Water | Moderate | Leakage, quality compliance | Lower budget density |
| Renewables / storage operators | Moderate | Asset performance, curtailment | Smaller data estates |

**Recommended entry point: smart metering / MSP.** It is where the data
volume argument is most obviously true, where the ETP story is native
rather than adapted, and where the buyer already has settlement pain that
a lakehouse demonstrably solves.

---

## 7. Business case summary

Full workings in [../business/BC-001-business-case.md](../business/BC-001-business-case.md).

**Cost position.** Iceberg on object storage with query-time compute
separates storage from compute. For an estate at half-hourly granularity,
compressed Parquet in the low tens of terabytes per year is object-storage
priced, against warehouse pricing that charges for the same bytes at a
large multiple. The saving is real, but it is a *storage* saving; do not
model it as a total-cost saving without modelling compute.

**Risk position.** The commercial risk is not competitive, it is
assurance. The platform will be evaluated by a CISO and a DPO before it is
evaluated by a data team. GAP-01 is therefore the highest-value item on
the roadmap by a wide margin — it converts the platform from
"interesting" to "procurable."

---

## 8. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T13:35:00Z | Baseline issue |
