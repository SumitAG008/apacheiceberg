# Repository Directory Manifest & Architecture Map

**Issued:** 2026-09-06T17:45:00Z · **Version:** 2.1  
**Repository:** `icebergAgent` (EnergyTrust Protocol & Meldra Data Studio)

---

## 1. Directory & File Navigation Index

```
icebergAgent/
├── README.md                           # Master Portal & System Quickstart
├── product_blueprint.md                # Enterprise Product Blueprint (Smart Grid Focus)
├── business_case_guide.md              # Plain-Language Business Case Guide
├── help_guide.md                       # Plain-Language Help Guide & Terminology
├── BC-002-etp-business-case.md         # BC-002: ETP Business Case & Market Strategy (Root Copy)
├── UC-001-use-cases.md                 # UC-001: Comprehensive Use Cases & Traceability Matrix (Root Copy)
├── HLD-001-high-level-design.md        # HLD-001: High-Level Architecture & Threat Model (Root Copy)
├── LLD-001-low-level-design.md        # LLD-001: Low-Level Design & Code Contracts (Root Copy)
├── DD-001-data-design.md               # DD-001: Data Design, Iceberg DDLs & IEC CIM Profile (Root Copy)
│
├── docs/                               # Formal Documentation Repository
│   ├── DIRECTORY_MANIFEST.md           # This Directory Manifest
│   ├── business/
│   │   ├── BC-001-business-case.md     # BC-001: Early Baseline Analysis
│   │   ├── BC-002-etp-business-case.md # BC-002: Formal ETP Business Case & Strategy
│   │   └── MSG-001-messaging-pack.md   # MSG-001: Verified Messaging Pack & Audience Frameworks
│   ├── functional/
│   │   └── UC-001-use-cases.md         # UC-001: Formal Use Cases Catalog
│   ├── architecture/
│   │   ├── HLD-001-high-level-design.md# HLD-001: System Context & 7-Block Design
│   │   └── DD-001-data-design.md       # DD-001: Iceberg Schemas & IEC CIM Mapping
│   ├── technical/
│   │   ├── LLD-001-low-level-design.md # LLD-001: Cryptographic Formulations & Contracts
│   │   ├── TD-003-zero-copy.md         # Zero-Copy Execution Specification
│   │   └── TD-004-scan-pushdown.md     # Scan Pushdown Optimization
│   └── adr/                            # Architecture Decision Records (ADRs)
│       ├── ADR-0001-iceberg-format.md  # ADR-1: Selection of Apache Iceberg Table Format
│       ├── ADR-0002-tenant-isolation.md# ADR-2: Multi-Tenant Namespace Scope Isolation
│       └── ADR-0003-llm-boundary.md    # ADR-3: Bounded LLM Query Execution Engine
│
├── backend/                            # Core Python Engine & Services
│   ├── etp/                            # EnergyTrust Protocol Engine (7 System Blocks)
│   │   ├── __init__.py                 # ETP Package Exports
│   │   ├── route_mutator.py            # Block 2: Moving Target Defense (HMAC-SHA256)
│   │   ├── meter.py                    # Block 1: Smart Meter Simulator & Canonical Hashing
│   │   ├── gateway.py                  # Block 3: Ingestion Gateway & Redis Nonce CAS
│   │   ├── phantom_grid.py             # Block 4: Phantom Grid Deception Honeypot
│   │   ├── writer.py                   # Block 5: Micro-Batch Iceberg Parquet Writer
│   │   ├── checkpointer.py             # Block 6: Daily Merkle Tree Builder (Domain Separated)
│   │   ├── verifier.py                 # Block 7: Verification Engine & Query Objects
│   │   ├── security.py                 # AES-256-GCM Encryption & Column Masking Guard
│   │   └── cim_exporter.py             # IEC 61970/61968 CIM RDF/XML Profile Exporter
│   │
│   ├── meldra/                         # Meldra Data Studio Core Library
│   │   ├── catalog.py                  # PyIceberg Catalog & ETP Schema Binding
│   │   ├── pipeline.py                 # Medallion Pipeline Execution (Bronze -> Silver -> Gold)
│   │   └── validator.py                # Data Quality Contracts & Validation Gates
│   │
│   ├── query_engine/                   # Serverless Query Execution Engine
│   │   ├── sql_backends.py             # DuckDB / Trino / Spark SQL Backend Drivers
│   │   └── models.py                   # Query Execution Models & Filter Pushdown
│   │
│   ├── observability/                  # Audit Trail & Telemetry Logging
│   │   └── logger.py                   # Structured Audit Event Bus (UTC ISO-8601)
│   │
│   ├── api/                            # FastAPI REST API & Endpoints
│   │   └── main.py                     # ETP Gateway & Meldra Studio API Server
│   │
│   └── tests/                          # Automated Pytest Test Suite
│       ├── test_etp_suite.py           # Exhaustive Test Matrix (T1–T25)
│       └── test_query_engine.py        # Query Engine & Pushdown Tests
│
├── frontend/                           # Meldra Data Studio Web Application (Vite + TS)
└── help-site/                          # Published Static Documentation Web Site
```

---

## 2. Security, Compliance, & Encryption Guidelines

1. **Wire-to-Rest Encrypted Telemetry:** Payloads encrypted using AES-256-GCM (`backend/etp/security.py`). Unencrypted raw wire payloads are rejected at the boundary.
2. **First-Class Provenance:** Verification statuses (`etp_verify_status`) are unmasked and written directly to Iceberg.
3. **Data Classification & RBAC Masking:** PII fields (`mpan`, customer identity) are masked before query relations reach DuckDB.
4. **Audit Logging:** Every gateway decision, route check, and query execution is logged with UTC ISO-8601 millisecond timestamps and correlation IDs.
