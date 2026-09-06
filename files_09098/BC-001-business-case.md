# BC-001 — Business Case and Analysis

**Document ID:** BC-001 · **Version:** 1.0 · **Issued:** 2026-09-05T14:10:00Z
**Status:** Baseline · **Audience:** Exec, commercial, investors

---

## 1. Problem statement

A distribution network operator with 3 million smart meters generates
approximately **52.6 billion readings per year** at half-hourly
granularity. Retention obligations run to years. Three existing approaches
each fail differently:

| Approach | Failure mode |
|---|---|
| Cloud data warehouse | Cost scales with volume; proprietary storage; expensive exit |
| Raw object storage | Cheap and unqueryable; no ACID, schema evolution or time travel |
| Hadoop-era data lake | Ungoverned; no fine-grained access control; operationally heavy |

Meanwhile the people with the best questions — network planners, settlement
analysts, field engineering leads — are frequently not SQL-fluent, so
questions queue behind a small data team.

---

## 2. Proposition

An Apache Iceberg lakehouse with governed multi-tenancy, role-aware
data-layer masking, and a natural-language interface **bounded to
deterministic execution** — the model writes the query, the engine computes
the number, and the snapshot ID makes the answer reproducible.

The bounded-execution property (ADR-0003) is the commercial differentiator,
not the natural-language interface itself. Anyone can bolt an LLM onto a
warehouse. What a utility cannot buy easily is a natural-language system
whose every answer is re-runnable, attributable and defensible in front of
a regulator.

---

## 3. Cost model

### Storage

| Item | Value |
|---|---|
| Readings/year (3M meters, half-hourly) | 52.56 billion |
| Compressed Parquet @ ~12 bytes/reading | ~630 GB/year |
| With Silver + Gold derivatives | ~1.5–2 TB/year |
| 7-year retained estate | ~10–14 TB |
| Object storage @ ~£0.02/GB/month | **~£200–350/month** |

At warehouse storage pricing the same estate is typically an order of
magnitude more, before compute.

> **Do not present this as total cost saving.** It is a *storage* saving.
> Compute is the larger line item in practice and depends entirely on query
> discipline — which is why scan pushdown (GAP-09) is a commercial issue,
> not just a technical one. An unpruned scan of a 52-billion-row table
> converts the cost advantage into a cost incident.

### Compute

Separated from storage. DuckDB serves single-node analytics without a
cluster; Spark or Doris plug into the same `SQLBackend` interface when
scale requires. Costs scale with query volume, not with retained bytes.

---

## 4. Benefits

| Benefit | Mechanism | Measurable as |
|---|---|---|
| Storage cost reduction | Object storage + open format | £/TB/month vs incumbent |
| Faster time-to-answer | Natural language + pushdown | Median analyst request turnaround |
| Reduced data-team queue | Self-service for non-SQL users | Tickets deflected |
| Audit response cost | Time travel + audit trail | Hours per regulatory request |
| Settlement defensibility | Deterministic execution + snapshot IDs | Disputes resolved without re-derivation |
| Exit optionality | Multi-engine open format | Migration cost at contract end |

**Honest note:** the first two are demonstrable today. The last four depend
on GAP-08 (snapshot IDs), GAP-05 (tamper-evident audit) and GAP-06
(instrumentation). Claim them as roadmap, not as delivered.

---

## 5. Market segmentation

| Segment | Fit | Entry driver | Blocker |
|---|---|---|---|
| **Smart metering / MSP** | **Strongest** | Settlement volume, DCC obligations | GAP-01, GAP-07 |
| Electricity distribution (DNO/DSO) | Strong | AMI volume, flexibility markets | GAP-01 |
| Transmission (TSO) | Strong | SCADA/PMU volume, criticality | GAP-01, higher CAF bar |
| Gas networks | Good | Asset integrity, leak analytics | GAP-14 adapters |
| Oil & gas midstream | Good | Pipeline telemetry, predictive maintenance | GAP-14 |
| Water | Moderate | Leakage, quality compliance | Budget density |
| Renewables / storage | Moderate | Asset performance, curtailment | Smaller estates |

**Recommended entry: smart metering / MSP.** The volume argument is most
obviously true there, the ETP story is native rather than adapted, and the
buyer already has settlement pain a lakehouse demonstrably relieves.

---

## 6. Competitive position

| Competitor class | Their strength | Meldra's angle |
|---|---|---|
| Cloud warehouses (Snowflake, BigQuery) | Maturity, ecosystem | Open format, no storage lock-in, sector-specific governance |
| Databricks | Scale, ML depth | Lower operational burden; Iceberg neutrality; utility-specific RBAC |
| Utility point solutions (MDMS vendors) | Domain fit | General-purpose analytics; not locked to metering |
| DIY Iceberg + Trino | Full control | Governance, tenancy, audit and NL interface out of the box |

The defensible position is **the governance layer, not the lakehouse**.
Iceberg is a commodity. Tenant isolation, data-layer masking, an audit
trail designed for a regulator, and bounded LLM execution are not.

---

## 7. Commercial risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Inference egress blocks procurement** | **High** | **Critical** | GAP-01 — highest-priority item on the roadmap |
| Assurance gaps surface late in a sales cycle | High | High | Lead with CISO/DPO, not with the data team |
| Over-claiming ("zero-copy", "predicate pushdown") damages credibility | Medium | High | Corrected in code and docs; hold the line in marketing |
| Long utility sales cycles exhaust runway | High | High | Target MSPs and consultancies for shorter cycles |
| Iceberg commoditised by hyperscalers | Medium | Medium | Compete on governance, not on format |
| Key-person concentration | High | High | Documentation baseline (this set) is the first mitigation |

The first and third are the ones within immediate control. The third in
particular is cheap to fix and expensive to get wrong: a data architect who
finds one inflated claim will discount every other claim in the deck.

---

## 8. Recommendation

1. **Close GAP-01 before any regulated pilot.** It is the difference between
   a platform that demos and one that deploys.
2. **Lead commercially with governance and auditability**, not with AI.
   The buyer committee that says no is CISO and DPO; the natural-language
   interface is what makes the analyst say yes *after* they clear it.
3. **Enter via smart metering / MSP**, where the ETP seam is native.
4. **Keep the claims true.** The corrections made in this cycle —
   pushdown, zero-copy, snapshot expiry — cost nothing and remove the most
   likely reason for a technical evaluator to disqualify the product.

---

## 9. Document control

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-05T14:10:00Z | Baseline issue |
