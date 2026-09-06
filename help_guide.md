# meldra & ETP Help Guide

Plain-language guide to what meldra and EnergyTrust Protocol (ETP) are, what everything is called, and how it fits together. Written for someone using the platform, not building it.

---

## 1. What meldra is, in one paragraph

meldra is an agentic data platform for Apache Iceberg smart meter lakehouses. At its center is an AI agent that reads what you're trying to do — in plain English — and carries it out by calling the same tools a data engineer would use by hand: ingest smart meter telemetry, run a query, check grid topology in the graph, or verify ETP cryptographic proofs. Underneath, everything it touches lands in your own cloud storage as Apache Iceberg — verified at the gateway via Moving Target Defense (MTD), versioned, never silently overwritten. You own the storage. Nothing is locked into a vendor's proprietary database, and every step the agent takes is one of a fixed, visible set of tools.

---

## 2. Speak meldra & ETP

| Term you'll see in the app | What it actually means |
|---|---|
| **Apache Iceberg** | The open table format your telemetry is saved in. Remembers every past version of itself and never silently loses data. |
| **ETP (EnergyTrust Protocol)** | Patented security layer for smart meter ingestion featuring Moving Target Defense (MTD) routes, deception honeypots, and first-class verification state in Iceberg. |
| **MPAN** | Meter Point Administration Number — the unique identifier for an electricity smart meter (MPRN for gas). |
| **Moving Target Defense (MTD)** | Dynamically rotating HTTPS ingress routes (`/api/v1/telemetry/rotated_<hash>`) derived from time windows and secrets to defeat port scanners. |
| **Phantom Grid** | An isolated deception honeypot that catches unauthenticated or stale-route probes, returning plausible synthetic data while logging threat intelligence. |
| **Monotonic Nonce** | An ever-increasing integer assigned per meter that prevents telemetry replay attacks. |
| **Catalog** | The index that knows which tables exist and where their Iceberg metadata files live. |
| **Warehouse** | The storage location (an S3 bucket or local directory) where your Parquet table files sit. |
| **Namespace** | A folder grouping related tables — e.g. `<tenant>__bronze`, `<tenant>__silver`, `<tenant>__gold`. |
| **Bronze / Silver / Gold** | Medallion architecture: Bronze = raw telemetry as-received; Silver = conformed, deduplicated, and verified; Gold = settlement aggregates. |
| **Merkle Tree Checkpoint** | Daily cryptographic tree built over meter readings to prove data has not been altered since ingest, anchored to RFC 3161 Timestamp Authorities. |
| **Snapshot / Time Travel** | Every write creates a snapshot. Time Travel lets you re-run queries as of an exact historical snapshot ID for regulatory disputes. |
| **Data Contract** | Rules on a table (e.g. `reading_kwh` non-null, valid voltage bounds) that block corrupt loads. |
| **RBAC & Column Masking** | Access control rules hiding restricted columns (like customer PII or raw MPANs) for unauthorized analyst roles. |
| **DuckDB** | The fast compute engine running SQL queries directly over Iceberg Parquet files on object storage. |

---

## 3. How Data Flows Through the Platform

```
Smart Meter Telemetry / HES Extracts
        │
        ▼
   ETP Gateway ──── Checks Nonces (CAS) & ECDSA Signatures (Blocks tampered data)
        │
        ▼
   Bronze Table (raw, append-only, etp_verify_status recorded on your S3)
        │
        ▼
   Silver Table (cleaned, deduplicated, chain gaps tagged)
        │
        ▼
   Gold Table (settlement-ready aggregates, verified proofs)
        │
        ▼
   Query Lab / Agent / Graph ── Analysts and Engineers query data safely
        │
        ▼
   Everything above is logged to the Audit tab with immutable correlation IDs
```

---

## 4. Who Uses Which Tab (The Four Personas)

| Persona | What They Mainly Do |
|---|---|
| **AMI / Data Engineer** | Connects HES feeds, builds Bronze → Silver → Gold pipelines, sets Data Contracts, monitors micro-batch writes. |
| **Utility Data Architect & CISO** | Approves schema changes, sets naming standards, manages 7-year retention locks and PII masking rules. |
| **Settlement Analyst / Ops Engineer** | Queries natural language interface, verifies settlement proofs, investigates feeder voltage anomalies. |
| **Admin** | Manages user accounts, RBAC policy configuration, and ETP key rotation workflows. |

---

## 5. What's Live Today vs. Roadmap

| Feature | Status |
|---|---|
| ETP Rotating Ingress Route Scrambling (MTD) | **Live** |
| Nonce CAS Replay Protection & ECDSA Hash Checks | **Live** |
| Apache Iceberg Telemetry Ingestion (Micro-Batch Parquet) | **Live** |
| Medallion Silver/Gold Pipeline Execution | **Live** |
| Data Quality Contracts & Schema Evolution | **Live** |
| Time Travel & Snapshot-Based Settlement Proofs | **Live** |
| Column-Level RBAC Masking & Data Classification | **Live** |
| The meldra Agent (Plain-English tool-calling) | **Live** |
| Audit Logging (UTC ISO-8601 millisecond trails) | **Live** |
| Phantom Grid Honeypot Deception Routing | **Live (Harness Demo)** |
| Daily Merkle Tree Checkpointing & RFC 3161 Anchoring | **Design Specification (HLD/LLD)** |
| Apache AGE Grid Topology & Threat Propagation Graph | **Live (Cypher Query Subset)** |

---

## 6. Getting Started (First 10 Minutes)

1. Launch local test environment.
2. Go to **Ingest**, load sample meter telemetry dataset (`vendors_10k_50col.csv` or meter extracts).
3. Review auto-detected Iceberg column types (`mpan`, `reading_kwh`, `reading_ts`).
4. Go to **Query Lab**, run a `SELECT * FROM bronze_ami_readings LIMIT 10`.
5. Ask the **Agent** in plain English: *"Show me average consumption by feeder in the last 24 hours"*.
6. Go to **Audit** to inspect the full tool-call log.
