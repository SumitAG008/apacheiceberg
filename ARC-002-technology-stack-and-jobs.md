# ARC-002 — Technical Architecture, Technology Stack & Background Job Registry

**Document ID:** ARC-002  
**Version:** 2.0  
**Issued:** 2026-09-23T23:00:00Z  
**Status:** Approved Specification  

---

## 1. Executive Summary & Branding Evolution: Tally

This specification defines the technology stack, background job processing pathways, architectural frameworks, AI-era agent ground-truth mechanisms, and UI/UX design standards for **Tally** (operating the **Tally Protocol**, formerly ETP).

### 🏷️ Branding & Origin: Tally
> **Why Tally?**  
> Historically, a **tally stick** was a split piece of wood used in financial settlement—each counterparty kept half, and the unique physical grain alignment proved neither side had altered their record.  
> As the standard instrument of English exchequer settlement for 600 years, **Tally** embodies *tallying* (counting and reconciling) and *tamper-evident shared recordkeeping between counterparties*.
> 
> * **Tally**: The enterprise platform and company.
> * **Tally Protocol**: The open cryptographic telemetry protocol (preserving the open standards adoption path).

---

## 2. End-to-End Technical Architecture & Data Pathways

```
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                                EDGE / INGESTION LAYER                             │
 │  • Smart Meters / IoT Edge (DLMS/COSEM, IEC 62351)                               │
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
 │                       AI AGENT & ANALYTICAL PROVENANCE LAYER                      │
 │  • Model Context Protocol (MCP) Server — backend/mcp_server.py headline interface │
 │  • JSON-LD / W3C PROV-O Output — Standard prov:wasDerivedFrom provenance emission  │
 │  • DuckDB Engine — High-speed embedded SQL execution over Iceberg Parquet files   │
 │  • Data-Layer RBAC & Column Masking — Automated cell/column security masking     │
 │  • Apache Arrow Flight SQL Server — Zero-copy high-speed streaming server (p8889)│
 └─────────────────────────┬─────────────────────────────────────────────────────────┘
                           │
                           ▼
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │                              UI & CONTROL PLANE LAYER                             │
 │  • FastAPI Backend — Async REST & WebSockets (/ws/traffic, /ws/chat)             │
 │  • React + TypeScript (Vite) — Modular screens (src/screens/*, typed src/api.ts) │
 │  • Zero-Trust Counterparty Verification Portal — Public, zero-login proof pack    │
 └───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Background Job Registry & Execution Pathways

The platform operates **5 asynchronous background jobs** executing independently of the main API event loop:

| Job ID | Job Name | Engine / Script | Cadence / Trigger | Architectural Responsibility |
|---|---|---|---|---|
| **JOB-01** | **Micro-Batch Lakehouse Writer** | `backend/etp/writer.py` (PyArrow + PyIceberg) | Continuous (Every **30s** or **50,000 blocks**) | Flushes in-memory Arrow `RecordBatch` streams to compressed Parquet files committed directly into `bronze_ami_readings` Iceberg tables. |
| **JOB-02** | **Daily Merkle Checkpointer** | `backend/etp/checkpointer.py` | Cron (**Daily at 00:05 UTC**) | Scans the previous day's telemetry, builds per-meter and estate-wide Merkle trees, detects monotonic sequence gaps (`SP 24–29 missing`), persists `etp_checkpoints.json`, and anchors roots to external RFC 3161 Timestamping Authorities (TSA) or WORM locks. |
| **JOB-03** | **Kafka Streaming Telemetry Consumer** | `backend/kafka_consumer.py` | Continuous daemon | Consumes real-time smart meter topics from Apache Kafka, executes fast route/signature verification, and passes blocks to the lakehouse writer. |
| **JOB-04** | **Arrow Flight Data Server** | `backend/arrow_flight_server.py` | Background daemon (Port **8889**) | Listens for high-speed client analytics requests, serving DuckDB query result sets directly via **Apache Arrow Flight SQL** with zero JSON serialization overhead. |
| **JOB-05** | **Live Traffic & Audit Event Bus** | `backend/traffic_bus.py` & `observability.audit_log` | Asynchronous event loop | Broadcasts real-time HTTP/ETP traffic telemetry over WebSockets to UI monitoring dashboards and appends immutable JSON-lines (`audit_log.jsonl`) for SOC compliance. |

---

## 4. AI-Era Architecture: "We Are the Ground Truth Autonomous Agents Run On"

Autonomous AI agents do not need another chat interface—**they need inputs they can verify**. When an autonomous agent acts on a financial settlement figure, grid headroom calculation, or carbon audit, it must verify whether underlying telemetry was complete and unaltered.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AI Agent Ground-Truth Architecture                       │
│                                                                             │
│  Autonomous AI Agent (Claude, GPT, Custom)                                  │
│        │                                                                    │
│        ▼ Model Context Protocol (MCP) / REST                                │
│  ┌───────────────┐                                                          │
│  │ mcp_server.py │ ──► Requests Verified Snapshot                            │
│  └───────┬───────┘                                                          │
│          │                                                                  │
│          ▼ JSON-LD / W3C PROV-O Response                                    │
│  {                                                                          │
│    "@context": "https://www.w3.org/ns/prov-one#",                           │
│    "prov:wasDerivedFrom": "urn:tally:snapshot:2026-09-22:84719",            │
│    "observedLeafCount": 42,                                                 │
│    "expectedPeriodCount": 48,                                               │
│    "tally:sequenceStatus": "ANCHORED_WITH_GAPS"                             │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Four Key AI-Era Architectural Pillars

1. **Model Context Protocol (MCP) First-Class Server (`backend/mcp_server.py`):**  
   MCP is elevated from a secondary utility to a headline interface. AI agents connect via standard MCP protocols to query certified tables, inspect Merkle proofs, and execute verification checks.
2. **Machine-Readable JSON-LD & W3C PROV-O Output:**  
   Query response objects emit standard **JSON-LD** metadata with `prov:wasDerivedFrom`, `observedLeafCount`, `expectedPeriodCount`, and `merkleRoot`. Any agent can verify data integrity using standard W3C PROV parsers without custom SDKs.
3. **Scoped Agent Authentication & Scoped API Tokens:**  
   Autonomous agents operate under dedicated, short-lived, rate-limited JWT/API tokens (`_create_api_token`). Agent actions are tagged with unique `agent_id` scopes in audit logs, strictly separate from human user sessions.
4. **Model Training Data Provenance (EU AI Act Compliance):**  
   Anchors exact Apache Iceberg snapshot IDs (`snapshot_id`) used to train or fine-tune grid forecasting models, satisfying EU AI Act requirements for training dataset traceability.

---

## 5. C++ Native Core Hardening Roadmap (`libetp_core`)

The C++ core (`~1,100 lines` across `gateway.cpp`, `route_mutator.cpp`, `merkle.cpp`, `pybind_bindings.cpp`) is built for high throughput. The engineering roadmap matures it through 4 ranked steps:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    C++ Core Hardening Pipeline                              │
│                                                                             │
│  1. Sanitizers in CI  ──►  2. libFuzzer Harness  ──►  3. Microbenchmarks    │
│  (ASan/LSan/UBSan)          (cpp/fuzz/)                (Google Benchmark)   │
│                                                                │            │
│                                                                ▼            │
│                                                     4. OEM Wheel Packaging  │
│                                                        (ETP_CORE_VERSION)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **Automated Sanitizers in CI (Completed):**  
   Added `-DCMAKE_BUILD_TYPE=Debug` step in `.github/workflows/ci-cd.yml` enforcing **AddressSanitizer (ASan)**, **LeakSanitizer (LSan)**, and **UndefinedBehaviorSanitizer (UBSan)** on every push.
2. **libFuzzer Target (`cpp/fuzz/fuzz_gateway.cpp`):**  
   Fuzz target testing `hex_to_bytes`, DER string handling, and canonical payload parsing against arbitrary attacker-controlled byte streams.
3. **Google Microbenchmarks (`cpp/bench/bench_etp_core.cpp`):**  
   Standardized benchmarks measuring `compute_canonical_hash` and `verify_ecdsa_signature` to validate the `35,000 ops/sec/node` benchmark under real CPU hardware.
4. **OEM C++ Packaging & Versioning:**  
   Explicit `ETP_CORE_VERSION` (1.0.0), C++ `install()` targets, and standalone PyBind11 wheel builds for OEM gateway integration.

---

## 6. UI Architecture & Quality Engineering

### 6.1 Frontend Modularization Strategy
To resolve UI maintenance friction from monolithic files (`main.ts` and `index.html`), the UI is structured into modular screen components:

```
frontend/vite-project/src/
├── api.ts                  # Single typed API client (live backend vs mock separation)
├── components/             # Reusable UI widgets (cards, navigation, chips)
├── screens/                # Modular screen controllers
│   ├── omissions.ts        # Omission Register & 60s Dispute Flow
│   ├── checkpoints.ts      # Merkle Checkpoints & TSA Anchors
│   ├── verification.ts     # Query Verifier & Proof Pack Validator
│   ├── audit.ts            # Audit Ledger & Threat Sentinel
│   └── telemetry.ts        # Live Ingestion & MTD Gateway Feed
└── main.ts                 # Light application router & entrypoint
```

### 6.2 Playwright UI Automated Testing in CI
Wired existing Playwright specs (`tests/ui/`) into GitHub Actions CI, adding spec coverage for the **Omission Register** and **Zero-Trust Counterparty Verification Portal**.

---

## 7. Technology Stack Mapping

| Layer / Domain | Technology Component | Architectural Purpose |
|---|---|---|
| **Native Performance Core** | **C++20 (`libetp_core` via PyBind11)** | Zero-allocation RAII OpenSSL hex parsing, byte-level block hashing, and ECDSA P-256 (NIST secp256r1) signature verification (~22,900 single-thread verifications/sec baseline, scalable across multi-core node pools). |
| **API & Business Logic** | **Python 3.11+ (FastAPI, Asyncio, Pydantic v2)** | High-performance async API backend, JWT/MFA auth, rate-limiting, and data-layer RBAC column masking. |
| **Lakehouse Format** | **Apache Iceberg + Apache Polaris (REST Catalog)** | Open ACID lakehouse table format supporting Parquet storage, time-travel, schema evolution, and cross-engine catalog metadata. |
| **In-Memory & Streaming Transport** | **Apache Arrow & Apache Arrow Flight SQL** | Zero-copy columnar memory representation for micro-batch buffers and gRPC analytics streaming. |
| **Event Streaming** | **Apache Kafka** | Distributed event bus streaming real-time telemetry into ingestion gateways and lakehouse writers. |
| **Graph & Network Topology** | **PostgreSQL 16 + Apache AGE** | Open-source graph extension storing IEC CIM electrical grid topology (Substation → Feeder → Transformer → Meter) with Cypher query support. |
| **In-Memory State Store** | **Redis / Valkey** | Clustered atomic memory store executing $O(1)$ monotonic nonce CAS checks in $<50\ \mu\text{s}$. |
| **Analytical Query Engine** | **DuckDB** | Embedded vectorized query engine executing SQL over Iceberg Parquet files with pushdown filters and dynamic column masking. |
| **AI / ML Mechanism** | **Tally AI Engine + MCP Server (`backend/mcp_server.py`)** | Model Context Protocol server emitting W3C PROV-O JSON-LD provenance outputs, Graph RAG, and AI Act snapshot training logs. |
| **Frontend Framework** | **React 18 + TypeScript + Vite** | Modular screen SPA with HSL design system tokens, WebSockets, typed `src/api.ts`, and Playwright test coverage. |
| **Infrastructure & CI/CD** | **Docker Compose, Kubernetes, Helm, Railway, Azure Pipelines, GitHub Actions** | Multi-container development, cloud deployment, and automated CI/CD gating (including ASan/LSan/UBSan C++ sanitizers). |

---

## 8. Document Control

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 1.0 | 2026-09-23T22:30:00Z | Lead Architect | Initial Specification defining Architecture Pathways, Job Registry, Stack Map, and UI/UX Standards |
| 2.0 | 2026-09-23T23:00:00Z | Lead Architect | Rebranded to Tally/Tally Protocol; Added AI Ground-Truth Architecture (MCP, JSON-LD, Agent Auth, EU AI Act Model Provenance); Added C++ Core Sanitizer/Fuzz/Bench Roadmap & Frontend Modularization Plan |
