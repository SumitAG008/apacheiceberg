# Meldra Grid Data Platform — Documentation

**Baseline issued:** 2026-09-05T14:15:00Z · **Version:** 1.0

Governed Apache Iceberg lakehouse, catalog and analytical query platform
for regulated utility operators — electricity, gas, oil and water.

---

## Start here

| If you are… | Read |
|---|---|
| An architect evaluating the platform | [ARC-001 Architecture Overview](architecture/01-architecture-overview.md) |
| A CISO or assessor | [ARC-004 Security Architecture](architecture/04-security-architecture.md), then [security/](security/) |
| A data architect | [ARC-003 Data Architecture](architecture/03-data-architecture.md) |
| Commercial or exec | [BC-001 Business Case](business/BC-001-business-case.md) |
| A developer joining the codebase | [ARC-001 §5](architecture/01-architecture-overview.md), [FUNC-001](functional/FUNC-001-functional-specification.md), [OPS-001](operations/OPS-001-logging-and-error-handling.md) |
| Asking "what's missing?" | [ARC-006 Gap Analysis](architecture/06-gap-analysis.md) |

---

## Index

### Architecture (TOGAF ADM)

| ID | Document | Phase |
|---|---|---|
| ARC-001 | [Architecture Overview](architecture/01-architecture-overview.md) | A, C |
| ARC-002 | [Business Architecture](architecture/02-business-architecture.md) | A, B |
| ARC-003 | [Data Architecture](architecture/03-data-architecture.md) | C |
| ARC-004 | [Security Architecture](architecture/04-security-architecture.md) | Cross-cutting |
| ARC-006 | [Gap Analysis and Roadmap](architecture/06-gap-analysis.md) | E, F |

### Functional and technical

| ID | Document |
|---|---|
| FUNC-001 | [Functional Specification](functional/FUNC-001-functional-specification.md) |
| TD-003 | [Zero-copy execution path](technical/TD-003-zero-copy-execution.md) |
| TD-004 | [Scan pushdown: state and roadmap](technical/TD-004-scan-pushdown.md) |

### Security records

| ID | Record | Severity | Status |
|---|---|---|---|
| SEC-2026-001 | [Agent tenant/RBAC bypass](security/SEC-2026-001-agent-tenant-bypass.md) | High | Remediated |
| SEC-2026-002 | [`/query/explain` scope gap](security/SEC-2026-002-explain-endpoint-scope.md) | Medium | Remediated |

### Decisions

| ID | Decision |
|---|---|
| ADR-0001 | [Apache Iceberg as the table format](adr/ADR-0001-iceberg-table-format.md) |
| ADR-0002 | [Namespace-prefix tenant isolation](adr/ADR-0002-tenant-isolation.md) |
| ADR-0003 | [The LLM boundary: models interpret, engines compute](adr/ADR-0003-llm-boundary.md) |

### Operations

| ID | Document |
|---|---|
| OPS-001 | [Logging, audit and error handling standard](operations/OPS-001-logging-and-error-handling.md) |
| BC-001 | [Business Case and Analysis](business/BC-001-business-case.md) |

---

## Documentation conventions

**Status labels are used consistently and mean what they say:**
● implemented · ◐ partial · ○ planned.

**Capabilities are never described as delivered when they are planned.**
Where the code and the intent differ, the gap is recorded in
[ARC-006](architecture/06-gap-analysis.md) rather than smoothed over. This
is architecture principle P7, and it exists because these documents will be
read during procurement and assurance, where an inflated claim discovered
by an evaluator discredits every other claim alongside it.

**All timestamps are UTC ISO-8601** with an explicit `Z`.

**Every document carries an ID, version and issue timestamp**, and a
document-control table recording changes.

---

## The two things a new reader should know

1. **The strongest part of this platform is the Policy Enforcement Point.**
   RBAC is applied to the data before it reaches any query engine, so
   column aliasing, subqueries and `SELECT *` cannot recover a masked
   value. That is a stronger guarantee than SQL rewriting and is worth
   understanding before evaluating anything else.

2. **The largest open gap is inference egress ([GAP-01](architecture/06-gap-analysis.md)).**
   Agent reasoning currently calls an external endpoint. For an operator
   inside NIS scope or a DCC-connected party, that is normally a blocking
   control failure. It is the single highest-value item on the roadmap.
