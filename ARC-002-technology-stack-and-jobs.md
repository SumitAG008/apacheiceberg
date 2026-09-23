# ARC-002 — Technical Architecture, Technology Stack & Background Job Registry

**Document ID:** ARC-002  
**Version:** 1.0  
**Issued:** 2026-09-23T22:30:00Z  
**Status:** Approved Specification  

---

## 1. Executive Summary

This specification defines the technology stack, background job processing pathways, architectural frameworks, and UI/UX design standards for the **EnergyTrust Protocol (ETP) Platform**.

It provides a comprehensive architectural blueprint covering the **Apache Ecosystem integration** (Iceberg, Polaris, Arrow, AGE, Kafka), the **native performance core** (C++20 `libetp_core`, Redis Nonce CAS, DuckDB), the **AI/ML Graph RAG engine**, and the **modern web interface standards** (REST + WebSockets + Arrow Flight SQL).

---

## 2. End-to-End Technical Architecture & Data Pathways

```
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                                EDGE / INGESTION LAYER                             │
 │  • Smart Meters (DLMS/COSEM, IEC 62351)                                          │
 │  • Apache Kafka (Real-time telemetry event streaming)                            │
 │  • C++20 Core Gateway (libetp_core) — HMAC-SHA256 route mutation, ECDSA verification│
 │  • Redis / Valkey — Atomic monotonic nonce CAS store (<50µs replay protection)   │
 │  • Phantom Grid — Active deception honeypot (silent decoy proxy)                  │
 └─────────────────────────┬─────────────────────────────────────────────────────────┘
                           │ Verified Wire Telemetry
                           ▼
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                             LAKEHOUSE PERSISTENCE LAYER                           │
 │  • Apache Arrow — In-memory columnar buffering (RecordBatch)                      │
 │  • Micro-Batch Writer — Flushes compressed Parquet micro-batches (30s / 50k rows) │
 │  • Apache Iceberg — Open lakehouse table format (ACID, Snapshots, Time-travel)   │
 │  • Apache Polaris / REST Catalog — Cross-engine catalog metadata management       │
 └─────────────────────────┬─────────────────────────────────────────────────────────┘
                           │
             ┌─────────────┴─────────────────────────────┐
             ▼                                           ▼
 ┌───────────────────────────────┐           ┌──────────────────────────────────────┐
 │   GRAPH & TOPOLOGY DATABASE   │           │    BACKGROUND JOBS & PROVENANCE     │
 │  • PostgreSQL + Apache AGE    │           │  • Daily Merkle Checkpointer         │
 │  • IEC CIM Grid Topology      │           │  • Sequence Gap Detector (SP 24–29)  │
 │  • Substation/Feeder Cypher   │           │  • External TSA Anchoring (RFC 3161) │
 └───────────┬───────────────────┘           └───────────────────┬──────────────────┘
             │                                                   │
             └─────────────────────────┬─────────────────────────┘
                                       ▼
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                             ANALYTICAL QUERY & AI LAYER                           │
 │  • DuckDB Engine — High-speed embedded SQL execution over Iceberg Parquet files   │
 │  • Data-Layer RBAC & Column Masking — Automated cell/column security masking     │
 │  • Meldra AI Agent (agent.py) — Natural Language to SQL/Cypher & Graph RAG       │
 │  • Apache Arrow Flight SQL Server — Zero-copy high-speed streaming server (p8889)│
 └─────────────────────────┬─────────────────────────────────────────────────────────┘
                           │
                           ▼
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                              UI & CONTROL PLANE LAYER                             │
 │  • FastAPI Backend — Async REST & WebSockets (/ws/traffic, /ws/chat)             │
 │  • React + TypeScript (Vite) — Modern UI with HSL theme tokens & micro-animations │
 │  • Zero-Trust Counterparty Verification Portal — Public, zero-login proof pack    │
 └───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Background Job Registry & Execution Pathways

The platform operates **5 asynchronous background jobs** that execute independently of the main API event loop:

| Job ID | Job Name | Engine / Script | Cadence / Trigger | Architectural Responsibility |
|---|---|---|---|---|
| **JOB-01** | **Micro-Batch Lakehouse Writer** | `backend/etp/writer.py` (PyArrow + PyIceberg) | Continuous (Every **30s** or **50,000 blocks**) | Flushes in-memory Arrow `RecordBatch` streams to compressed Parquet files committed directly into `bronze_ami_readings` Iceberg tables. |
| **JOB-02** | **Daily Merkle Checkpointer** | `backend/etp/checkpointer.py` | Cron (**Daily at 00:05 UTC**) | Scans the previous day's telemetry, builds per-meter and estate-wide Merkle trees, detects monotonic sequence gaps (`SP 24–29 missing`), persists `etp_checkpoints.json`, and anchors roots to external RFC 3161 Timestamping Authorities (TSA) or WORM locks. |
| **JOB-03** | **Kafka Streaming Telemetry Consumer** | `backend/kafka_consumer.py` | Continuous daemon | Consumes real-time smart meter topics from Apache Kafka, executes fast route/signature verification, and passes blocks to the lakehouse writer. |
| **JOB-04** | **Arrow Flight Data Server** | `backend/arrow_flight_server.py` | Background daemon (Port **8889**) | Listens for high-speed client analytics requests, serving DuckDB query result sets directly via **Apache Arrow Flight SQL** with zero JSON serialization overhead. |
| **JOB-05** | **Live Traffic & Audit Event Bus** | `backend/traffic_bus.py` & `observability.audit_log` | Asynchronous event loop | Broadcasts real-time HTTP/ETP traffic telemetry over WebSockets to UI monitoring dashboards and appends immutable JSON-lines (`audit_log.jsonl`) for SOC compliance. |

---

## 4. UI & UX Architecture: Why Modern REST + WebSockets + Arrow Flight (Over OData v2)

### 4.1 Evaluation of Legacy Protocols (OData v2 / SAP Fiori) vs. Modern Lakehouse UI
* **OData v2 / SAP Fiori Limitation:** Historically created for transactional SAP ERP applications. It relies on heavy XML/JSON payloads, lacks native compatibility with Apache Arrow columnar memory structures, and incurs severe serialization overhead when rendering 100,000+ row analytical telemetry views.
* **The ETP Modern UI Pattern:**
  1. **Control Plane & Admin UI (FastAPI + React Vite):** High-speed REST API for authentication, MFA, SAML/OIDC SSO, RBAC, user management, and table metadata catalog views.
  2. **Real-Time Telemetry & Threat Feeds (WebSockets / SSE):** Real-time event streaming (`/ws/traffic`, `/ws/chat`) for live route mutation visualizers, honey-pot engagement maps, and chat streaming.
  3. **High-Volume Analytical Data Streaming (Apache Arrow Flight SQL):** For multi-gigabyte analytical result sets, data is streamed directly into client dashboards or notebooks via **Apache Arrow Flight** over gRPC, completely bypassing standard REST JSON serialization bottlenecks.
  4. **Zero-Trust Counterparty Verification Portal:** A standalone, unauthenticated public page where external auditors upload ETP proof packs (`.json` / `.bin`) and execute client-side WebCrypto re-verification without needing an account or trusting the utility's servers.

### 4.2 Design System Tokens & Typography Rules
* **Color System:** HSL-tailored dark/light mode tokens (`--ground`, `--surface`, `--accent`, `--ok`, `--warn`, `--crit`).
* **Typography Rule:**
  * **IBM Plex Mono:** Mandatory for any machine-generated string (MPAN, block hash, nonce, root, token, UTC timestamp).
  * **Archivo:** Mandatory for human prose, headings, labels, and buttons.
* **Semantic Chips:** `--ok` (Verified proof), `--warn` (Sequence gaps present), `--crit` (Replay/Tamper rejection), `neutral` (Unanchored).

---

## 5. Technology Stack Mapping

| Layer / Domain | Technology Component | Architectural Purpose |
|---|---|---|
| **Native Performance Core** | **C++20 (`libetp_core` via PyBind11)** | Zero-allocation RAII OpenSSL hex parsing, byte-level block hashing, and ECDSA-P256 signature verification (>35,000 verifications/sec/node). |
| **API & Business Logic** | **Python 3.11+ (FastAPI, Asyncio, Pydantic v2)** | High-performance async API backend, JWT/MFA auth, rate-limiting, and data-layer RBAC column masking. |
| **Lakehouse Format** | **Apache Iceberg + Apache Polaris (REST Catalog)** | Open ACID lakehouse table format supporting Parquet storage, time-travel, schema evolution, and cross-engine catalog metadata. |
| **In-Memory & Streaming Transport** | **Apache Arrow & Apache Arrow Flight SQL** | Zero-copy columnar memory representation for micro-batch buffers and gRPC analytics streaming. |
| **Event Streaming** | **Apache Kafka** | Distributed event bus streaming real-time telemetry into ingestion gateways and lakehouse writers. |
| **Graph & Network Topology** | **PostgreSQL 16 + Apache AGE** | Open-source graph extension storing IEC CIM electrical grid topology (Substation → Feeder → Transformer → Meter) with Cypher query support. |
| **In-Memory State Store** | **Redis / Valkey** | Clustered atomic memory store executing $O(1)$ monotonic nonce CAS checks in $<50\ \mu\text{s}$. |
| **Analytical Query Engine** | **DuckDB** | Embedded vectorized query engine executing SQL over Iceberg Parquet files with pushdown filters and dynamic column masking. |
| **AI / ML Mechanism** | **Meldra AI Agent (`agent.py`, `tools.py`)** | LLM tool-calling agent executing natural language SQL, Cypher graph queries, Graph RAG, and topological random-walk phase prediction. |
| **Frontend Framework** | **React 18 + TypeScript + Vite** | Lightweight SPA with HSL design system tokens, WebSockets, and zero-trust verification module. |
| **Infrastructure & CI/CD** | **Docker Compose, Kubernetes, Helm, Railway, Azure Pipelines, GitHub Actions** | Multi-container development, cloud deployment, and automated CI/CD gating. |

---

## 6. Document Control

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 1.0 | 2026-09-23T22:30:00Z | Lead Architect | Initial Specification defining Architecture Pathways, Job Registry, Stack Map, and UI/UX Standards |
