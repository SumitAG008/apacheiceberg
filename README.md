# EnergyTrust Protocol (ETP) & Apache Iceberg Lakehouse Specification

**Baseline Issued:** 2026-09-06T17:46:00Z · **Version:** 2.1  

Patented security layer for smart meter telemetry ingestion, with an Apache Iceberg lakehouse that carries cryptographic verification from the physical gateway wire through to the analyst's query screen.

---

## 1. Master Documentation Index

| # | Specification Document | Primary Questions Answered | Key Topics Covered |
|---|---|---|---|
| 1 | **[BC-002 Business Case](BC-002-etp-business-case.md)** | Who buys ETP, who competes, and why the platform demonstrates what ETP sells? | TAM/SAM/SOM market sizing, TCO unit economics, competitive matrix vs. Databricks/CGI, customer segment ranking, regulatory compliance (NIS2, NERC CIP, NIST), IEC CIM alignment, AWS Marketplace / Siemens GTM, Monotonic Nonce IP strategy. |
| 2 | **[UC-001 Use Cases](UC-001-use-cases.md)** | What does the platform do, for whom, and with what acceptance SLAs? | Verification-Aware Query Objects (UC-02), Plausible Deception (UC-03), Monotonic Nonce Omission Detection (UC-09), Strategic Extensions (UC-10–UC-13), Traceability Matrix. |
| 3 | **[HLD-001 High-Level Design](HLD-001-high-level-design.md)** | How do system components wire together and scale to 52B rows/year? | Mermaid visual architecture maps, the 7 Core System Blocks, Escalation State Machine (S0–S5), STRIDE threat model, Redis sharded nonce store, scaling topology. |
| 4 | **[LLD-001 Low-Level Design](LLD-001-low-level-design.md)** | What are the exact cryptographic formulas, code contracts, and test matrices? | HMAC-SHA256 MTD route scrambling, byte canonicalization standards, production Python code contracts, Redis Lua atomic CAS script, domain-separated Merkle algorithms, T1–T25 test matrix. |
| 5 | **[DD-001 Data Design](DD-001-data-design.md)** | How are Apache Iceberg tables, Apache AGE graphs, and IEC CIM profiles structured? | Executable Iceberg DDLs (`bronze_ami_readings`, `_etp_checkpoints`, `_etp_threat_log`), Medallion SQL pipelines, Apache AGE Cypher graph queries, IEC CIM (IEC 61970/61968) mapping, proposed `cim:TelemetryProvenance` extension RDF schema. |

---

## 2. Core Architectural Overview

```
       ┌────────────────────────────────────────────────────────┐
       │             EnergyTrust Protocol (ETP)                 │
       └──────────────────────────┬─────────────────────────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
┌─────────────────────────────────┐       ┌──────────────────────────────────┐
│  Ingestion Boundary Protection   │       │   Lakehouse Data Provenance      │
│  • Rotating Routes (MTD)        │       │   • Verification columns in Iceberg │
│  • Silent Deception (Honeypot)  │       │   • Daily Merkle Checkpoints         │
│  • Monotonic Nonce Replay Lock  │       │   • Reproducible Snapshot Audits    │
└─────────────────────────────────┘       └──────────────────────────────────┘
```

A utility can authenticate a reading at the smart meter and separately assert that a data warehouse row is unaltered. Nothing joins the two. When a regulator requests proof of a settlement figure, substantiation requires manual, multi-week reconciliation across raw PCAP logs and warehouse exports.

**ETP solves this at the wire:**
1. **Moving Target Defense (MTD):** Telemetry routes rotate continuously based on clock windows ($W = \lfloor t/60 \rfloor$) and shared secrets.
2. **Statistically Plausible Deception:** Unauthenticated probes or stale-route scans are silently proxied to a **Phantom Grid** honeypot, responding with realistic time-of-day load curves while logging threat intelligence.
3. **Monotonic Nonce Omission Protection:** Hardware monotonic nonces prove sequence completeness, automatically flagging deleted or withheld readings (meter tampering / settlement fraud).
4. **Verification-Aware Query Objects:** Queries return figures, Iceberg snapshot IDs, SQL strings, and anchored Merkle proofs in a single unified response object.
5. **IEC CIM Integration:** Physical Iceberg schemas map directly to IEC 61970 / IEC 61968 classes (`UsagePoint`, `Meter`, `ACLineSegment`), establishing instant credibility with Siemens, GE, and Schneider Electric systems.

---

## 3. The 7 System Component Blocks

```
1 (Meter) ──► 3 (Gateway) ──► 5 (Writer) ──► 6 (Checkpointer)
                  │                              │
                  ▼                              ▼
             4 (Phantom)                     7 (Verifier)
                  ▲
                  2 (Mutator)
```

1. **Block 1 — Meter Simulator / Firmware:** Generates signed telemetry blocks with monotonic nonces.
2. **Block 2 — Route Mutator:** Pure mathematical function emitting valid rotating route sets (`w-1`, `w`, `w+1`).
3. **Block 3 — ETP Gateway:** Executes atomic Redis nonce CAS checks, hash recomputation, ECDSA verification, and deception routing.
4. **Block 4 — Phantom Grid:** Honeypot segment returning statistically plausible synthetic acknowledgements.
5. **Block 5 — Lakehouse Writer:** Micro-batches verified blocks (30s / 50k rows) into Iceberg Parquet files.
6. **Block 6 — Merkle Checkpointer:** Builds daily per-meter and estate-wide Merkle trees with domain separation (`0x00`/`0x01`); anchors roots to RFC 3161 TSAs.
7. **Block 7 — Verification Engine:** Validates analytical SQL query results against anchored Merkle checkpoints.

---

## 4. Strategic Collaboration & Distribution Channels

- **AWS Marketplace:** Transact ETP licenses on AWS paper using pre-allocated utility EDP budgets, completely bypassing sole-supplier procurement risk.
- **Siemens Xcelerator:** Integrate ETP telemetry provenance directly into Siemens GridScale via open IEC CIM profile mappings.
- **Utility CVC Scouting Channels:** Target pilot grants from National Grid Partners, Iberdrola PERSEO, E.ON Agile, EDP Starter, and Shell GameChanger.

---

## 5. Local Developer Harness & Quickstart

To build and run the 60-second local demonstration harness (Blocks 1, 2, 3, and 4):

```bash
# 1. Clone & initialize python environment
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 2. Run unit & regression test suite
pytest tests/ -v

# 3. Launch local MTD Gateway & Meter Simulator
python app.py
```

---

## 6. Document Control

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 1.0 | 2026-09-06T09:45:00Z | Lead Architect | Initial Baseline |
| 2.0 | 2026-09-06T17:40:00Z | Lead Architect | Comprehensive Update across all 5 specs |
| 2.1 | 2026-09-06T17:46:00Z | Lead Architect | Added IEC CIM Alignment, AWS Marketplace GTM, Monotonic Nonce IP Strategy, Verification-Aware Query Objects |
