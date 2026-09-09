# Meldra Data Studio — Enterprise Product Blueprint (Smart Grid & ETP Focus)

From technical toolkit to utility-grade data platform: personas, smart grid use cases, telemetry workflows, and roadmap.

---

## 1. What Data Studio Actually Is (In Business Terms)

Data Studio is the control room of the smart meter lakehouse. Every energy enterprise and utility data platform must do five key jobs. Each maps directly to Data Studio modules:

| Job (Business Language) | What it means | Data Studio Module Today |
| :--- | :--- | :--- |
| **Get telemetry in, reliably & securely** | Ingest smart meter readings (AMI), SCADA logs, feeder telemetry, and weather feeds without unauthorized tampering. | ETP Gateway, Ingest, MCP Gateway, Connectors |
| **Make meter data trustworthy** | Validate, deduplicate, standardize, and cryptographically verify wire telemetry. | ETP Ingestion Verification, Data Quality, Schema Evolution |
| **Never lose settlement history** | Keep every reading, snapshot, and calculation versioned, reversible, and fully auditable. | ETP Merkle Checkpoints, Time Travel, Audit Log |
| **Automate telemetry pipelines** | Scheduled or event-driven ingestion pipelines with full execution visibility and anomaly alerting. | Orchestrator DAG, Triggers & Alerts, Run History |
| **Serve grid answers safely** | Ensure analysts, engineers, and regulators query verified data safely at scale without vendor tax. | ETP Provenance Verifier, SQL Console, Chat, Topology Graph |

> [!NOTE]
> **One-Line Pitch for a Utility CIO / CISO:**  
> *"Your 50-billion-row smart meter telemetry lands once in your own S3 as open Apache Iceberg—verified at the ingestion gateway via Moving Target Defense, versioned, and governed. Every team from settlement analysts to grid ops engineers works from the same certified tables with reproducible proofs for regulators."*

---

## 2. The Four Personas and Their Capabilities

### 2.1 🛠️ AMI / Data Engineer (Daily Driver)
*   **Connect Sources:** Head-end Systems (HES), Smart Meter Gateways, SCADA historians, weather API feeds, and flat telemetry extracts with instant test-connection and vaulting.
*   **Medallion Pipelines:** Build Bronze (raw append) → Silver (deduplicated & verified) → Gold (settlement aggregates) pipelines as code (SQL/Python), run, schedule, and auto-retry.
*   **Data-Quality & Cryptographic Gates:** Enforce schemas and ETP verification checks that **BLOCK** tampered or replayed telemetry loads instead of just logging them.
*   **Monitoring Hub:** Monitor run histories, view per-task runtime logs, and configure failure alerts to Slack/Teams/pager.
*   **Lifecycle Ops:** Optimize tables (compaction, snapshot expiry, partition tuning) based on automated policies for 50B+ row estates.

### 2.2 📐 Utility Data Architect & CISO (Standards Owner)
*   **Medallion Structure:** Enforce standardized naming structures (namespaces = `<tenant>__bronze`, `<tenant>__silver`, `<tenant>__gold` per region/grid domain).
*   **Schema & Protocol Governance:** Approve schema changes and cryptographic suite updates; destructive actions require dual sign-off.
*   **Lineage & Provenance Mapping:** Visualize column-level lineage to trace which raw meter reading generated which settlement KPI.
*   **Environment Promotion:** Promote changes through environments (`dev` → `staging` → `prod`) with visual schema diffs and peer sign-offs.
*   **Security & Compliance:** Set 7-year retention locks (`meldra.retention.min_days`), tag sensitive occupancy data, and apply masking policies at the column level.

### 2.3 📊 Settlement Analyst & Grid Ops Engineer (Growth Audience)
*   **Glossary Catalog:** Search the data catalog in plain business terms (e.g., searching *"half-hourly feeder demand"* returns `gold_settlement_daily` with description, owner, freshness, and certification badge).
*   **Natural Language Q&A:** Query meter data using the Chat tab grounded in the catalog (e.g., *"meters on feeder F-4471 reporting voltage outside limits in the last two hours"* shows the generated SQL with partition pushdown).
*   **Analytics & Proof Delivery:** Save views, export certified settlement reports, pin period snapshots, and re-run exact queries months later with snapshot IDs.
*   **System Abstraction:** Never exposed to IAM keys, DDL statements, compaction snapshots, or raw crypto hashes.

### 2.4 💼 Utility Executive / CISO / Regulator (One Screen, Five Numbers)
*   **Cost:** S3 storage and query compute costs broken down per grid region with trends and forecasting.
*   **Trust & Data Quality:** Platform-wide telemetry verification score, real-time view of ETP verification statuses (`VERIFIED`, `CHAIN_GAP`, `FAILED`), and replay rejection metrics.
*   **Observability:** End-to-end telemetry (pipeline latencies, block counts, correlation IDs, and clock-drift bounds).
*   **Compliance:** Live posture audits (NIS2, NERC CIP-005/007, NIST SP 800-82) showing access trails, cryptographic audit hash chains, and retention evidence.
*   **Risk & Threat Map:** Alert dashboard showing invalid route probes, Phantom Grid honeypot engagements, and suspected meter key compromise events.

---

## 3. Flagship Business Cases & Workflows

### ⚡ Business Case A: Verified Smart Meter Telemetry Ingestion (UC-01)
*   **Problem:** Utilities face replay attacks, unauthorized telemetry injection, and data lake tampering that compromise billing accuracy.
*   **Value:** Instant gateway rejection of replayed nonces ($<1 \text{ ms}$); first-class `etp_verify_status` columns committed directly to Iceberg.
*   **Workflow:**
    1.  **Ingest:** ETP Gateway receives rotated route payload, checks monotonic nonce, verifies ECDSA signature.
    2.  **Writer:** Micro-batches verified blocks every 30s into `bronze_ami_readings`.
    3.  **Silver Pipeline:** Deduplicates and tags chain gaps in `silver_ami_readings`.
    4.  **Audit:** Emits structured audit logs (`telemetry.ingest`, `telemetry.replay_rejected`) to audit bus.

### 💶 Business Case B: Settlement Substantiation & Dispute Audit (UC-02)
*   **Problem:** Regulators require utilities to prove settlement calculations derive from authentic, unaltered wire telemetry—a manual process taking weeks and costing £50k–£200k per dispute.
*   **Value:** 99.9% cost reduction via instant, DuckDB-powered Merkle proof generation re-runnable by auditors without vendor presence.
*   **Workflow:**
    1.  **Query:** Analyst runs settlement query for disputed period; system captures Snapshot ID and scanned partitions.
    2.  **Verification:** Verifier checks partition Merkle roots against daily anchored RFC 3161 TSA checkpoints.
    3.  **Export:** System exports audit bundle (SQL + Snapshot ID + Merkle Proof + TSA Token) for regulatory submission.

### 🛡️ Business Case C: Moving Target Defense & Honeypot Recon Containment (UC-03)
*   **Problem:** Static ingestion endpoints (`/api/v1/telemetry`) are exposed to scanners, DDoS, and zero-day API exploit attempts. Blocking alerts attackers and prompts infrastructure rotation.
*   **Value:** Active Moving Target Defense (MTD) rotates routes continuously; silent proxying to Phantom Grid honeypots traps scanners and collects STIX threat intelligence.
*   **Workflow:**
    1.  **Ingest:** Scanner hits stale or unrotated endpoint.
    2.  **Route Check:** Gateway fails route lookup, flags Source IP, and silently proxies connection to isolated Phantom Grid container.
    3.  **Deception:** Phantom Grid returns statistically plausible synthetic $HTTP\ 200\ OK$ responses.
    4.  **SIEM Export:** Threat Sentinel exports STIX 2.1 / TAXII 2.1 threat logs to enterprise SOC.

### 🔍 Business Case D: Grid Event & Feeder Anomaly Investigation (UC-04)
*   **Problem:** Voltage excursions and outages require fast correlation across millions of meters to locate common upstream transformers.
*   **Value:** Instant correlation using Apache AGE topology graph (`GSP → Substation → Feeder → Meter`) and spatial SQL filtering.
*   **Workflow:**
    1.  **Ingest:** Stream half-hourly voltage readings into Iceberg.
    2.  **Graph Analysis:** Execute Cypher query over topology graph to map anomalous meters back to common upstream substation.
    3.  **Alerting:** Push asset IDs to grid ops dashboard for immediate field dispatch.

### 🌐 Business Case E: AI Grid Digital Twin for Low-Voltage Operations (UC-05)
*   **Problem:** DNOs face an unmonitored blind spot across 800,000+ secondary distribution substations (11kV/400V) as EV charging and heat pumps cluster, with physical sensor retrofits costing over £3B.
*   **Value:** Complete software-defined LV visibility fusing physical CIM IEC 61968 electrical network graphs directly to 50B+ half-hourly smart meter readings on Apache Iceberg, delivering sub-second feeder headroom calculations and AI-driven phase identification ($L1/L2/L3$) at < 5% of physical hardware costs.
*   **Workflow:**
    1.  **Topology Mapping:** Ingest CIM XML / GIS topology into Apache AGE graph store (Substation → Feeder → Secondary Transformer → LV Cable → Cutout → MPAN).
    2.  **Telemetry Synchronization:** Synchronize half-hourly active power (kW), reactive power (kvar), and voltage (V) in Apache Iceberg with automated SQL pushdown.
    3.  **AI State Estimation:** Run in-engine topological random-walk embeddings (`AIMLEngine.generate_node_embeddings`) to cluster and predict unmapped meter phase connections ($L1, L2, L3$).
    4.  **Operational Simulation:** Execute sub-second Feeder Headroom and Reverse Power Flow queries to alert planning engineers of thermal breaches and voltage limit violations (+10% / -6%).

---

## 4. Competitive Differentiation & Capability Roadmap

### 🥊 Competing with Market Players & Upcoming Vendors
- **vs. Databricks / Snowflake:** ETP adds **wire-to-rest cryptographic provenance and Moving Target Defense** at the ingestion boundary—capabilities absent in generic cloud warehouses.
- **vs. CGI / Amperon / Grid4C / Pravāh:** Position ETP as an **ingestion security component & provenance engine** (Segment 1/2 partner) rather than competing head-on in ML forecasting.

---

## 5. Design Principles
1.  **Progressive Disclosure:** Tailor navigation based on user role; settlement analysts see query tools and verification proofs, engineering tabs stay focused on pipeline health.
2.  **Audit by Design:** Every single query execution, route lookup, or settings adjustment requires an actor and correlation ID.
3.  **Guardrails over Gates:** Standard configurations are secure by default (fail-closed, retention locks, automatic MTD route checks).
4.  **Zero Lock-In:** Retain open Apache Iceberg format compatibility on the utility's S3 with exportable DuckDB/Trino query syntax.
