# Meldra Data Studio — Observability & Customer Trust Standard

This document defines the twin architectural pillars of **Observability** and **Customer Trust** across Meldra Data Studio (built on Apache Iceberg) and specialized domain protocols such as the **Energy Trust Protocol (ETP)**.

---

## 1. The Four Pillars of Observability

Observability in Meldra ensures every telemetry stream, pipeline execution, SQL query, and AI Agent action is fully transparent, measurable, and auditable.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          OBSERVABILITY ENGINE                               │
├───────────────────┬───────────────────┬───────────────────┬─────────────────┤
│ Pipeline Metrics  │ Execution Telemetry│ Schema Drift      │ Cost & Compute  │
│ • Run status      │ • Latency (ms)    │ • Type changes    │ • S3 bytes      │
│ • Retry counts    │ • Rows scanned    │ • New columns     │ • Memory / CPU  │
│ • SLA tracking    │ • Correlation IDs │ • Unmapped fields │ • Query cost    │
└───────────────────┴───────────────────┴───────────────────┴─────────────────┘
```

### 1.1 Pipeline Run Telemetry
* **Correlation Tracking:** Every ingestion job or query receives a unique `correlation_id` (UUIDv4) passed across frontend API calls, backend FastAPI routes, DuckDB query execution, and audit log DB entries.
* **Execution Metrics:** Standardized measurement of execution duration (`duration_ms`), rows processed (`rows_scanned`, `rows_written`), and error codes.
* **Failure Alerts:** Automated failure routing to configured webhooks (Slack/Teams/Email) when a Data Quality contract or pipeline execution fails.

### 1.2 Schema Drift Monitoring
* **Automated Detection:** Detects unexpected field additions, type shifts, or missing columns between Bronze (raw) and Silver (clean) tiers.
* **Structural Diffing:** Logs visual schema diffs before applying DDL evolutions on Iceberg tables.

### 1.3 Cost & Resource Telemetry
* **Storage Footprint:** Tracks raw Parquet/Iceberg file storage per namespace (`bronze`, `silver`, `gold`).
* **Query Compute Attribution:** Attributes query runtimes and scanned byte counts to specific user roles and tenant accounts for cost allocation.

---

## 2. The Five Pillars of Customer Trust

Customer Trust guarantees that data is accurate, governed, un-tampered, and accessible without proprietary vendor lock-in.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CUSTOMER TRUST ENGINE                            │
├───────────────────┬───────────────────┬───────────────────┬─────────────────┤
│ Inline DQ Gates   │ Data-Layer RBAC   │ Immutable Audit   │ Open Storage    │
│ • Block bad data  │ • Column masking  │ • Cryptographic   │ • Apache Iceberg│
│ • Zero corruption │ • Row filtering   │   hash chaining   │ • S3 ownership  │
└───────────────────┴───────────────────┴───────────────────┴─────────────────┘
```

### 2.1 Inline Data Quality Gates ("Trust at Ingestion")
* **Gatekeeper Model:** Data Quality contracts act as strict gates. Corrupted, out-of-bounds, or unverified records are blocked at the `Bronze ➔ Silver` boundary rather than being fixed post-hoc.
* **Trust Score Metric:** Every dataset computes a real-time Data Trust Score ($\text{Pass Rate} = \frac{\text{Valid Records}}{\text{Total Records}} \times 100\%$).

### 2.2 Data-Layer RBAC & Fine-Grained Redaction
* **Boundary Enforcement:** RBAC policies ([rbac_utils.py](file:///c:/Users/sumit/Documents/icebergAgent/backend/rbac_utils.py)) apply at the DataFrame boundary before execution engines (DuckDB, AST Python sandbox) receive data.
* **Zero Bypass:** Column aliasing or subquery wrapping in SQL cannot bypass masking rules (`###.##`, `***`, or full redaction).

### 2.3 Cryptographic & Tamper-Evident Audit Trails
* **Append-Only Ledger:** Audit logs store actor ID, role, action, target table, timestamp, and payload hash.
* **Hash-Chaining:** High-security tiers chain audit hashes ($\text{Hash}_n = \text{SHA256}(\text{Data}_n \parallel \text{Hash}_{n-1})$) to guarantee log immutability.

### 2.4 Point-in-Time Snapshot Reproducibility (Iceberg Time Travel)
* **Permanent Snapshots:** Every table mutation (append, update, compaction) writes a new Iceberg snapshot ID.
* **Audit Reproducibility:** Historical compliance, tax, or energy certificate audits can query the exact state of any table as of any past timestamp.

### 2.5 Open Data Sovereignty (Zero Vendor Lock-In)
* **S3 Ownership:** All data resides in open Apache Iceberg format on the customer's own cloud storage (S3/GCS/Azure Blob).
* **Engine Interoperability:** Data can be queried by Spark, Trino, Snowflake, or DuckDB at any time without proprietary export fees.

---

## 3. Energy Trust Protocol (ETP) Observability & Trust Mapping

For Energy Trust Protocol applications, Observability & Customer Trust translate into specific grid and certificate guarantees:

| ETP Requirement | Observability Mechanism | Customer Trust Mechanism |
| :--- | :--- | :--- |
| **Meter Telemetry Ingestion** | Real-time Kafka consumer throughput & payload latency telemetry. | HMAC-SHA256 signature verification on IoT payloads. |
| **Grid Anomaly Detection** | AST-sandboxed ML execution monitoring Z-score anomalies. | Blocking invalid kWh generation spikes at the `Bronze` gate. |
| **Double-Claim Prevention** | Graph engine topology visualization ([graph_db.py](file:///c:/Users/sumit/Documents/icebergAgent/backend/graph_db.py)). | Graph validation ensuring 1 MWh Certificate $\rightarrow$ 1 Consumer. |
| **Certificate Provenance** | Correlation ID tracking from meter read to Gold certificate. | Iceberg Time Travel snapshot pinning for 24/7 CFE audits. |
| **Consumer Privacy** | Audit tracking of regional energy query counts. | Automatic PII masking of residential account numbers & addresses. |
